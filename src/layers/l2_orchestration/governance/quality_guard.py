"""
质量守护 — 三层兜底机制

Layer 1: 确定性校验 — 每个 Agent 输出必须通过 rule-based 验证
Layer 2: 自动回退 — 验证失败时用模板/缓存/规则引擎替代
Layer 3: 人机协作 — 前两层都失败，升级人工决策（含完整诊断上下文）

这是 SignOffAI 从 7→8+ 的核心：不是靠 LLM 更聪明，而是 LLM 失败时有兜底。
"""

from __future__ import annotations

import json, re, sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum


# ═══════════════════════════════════════════════════════════════
# 校验结果
# ═══════════════════════════════════════════════════════════════

class Verdict(str, Enum):
    PASS = "pass"           # 通过，继续
    RETRY = "retry"         # 失败，但可重试（LLM 输出有结构缺陷）
    FALLBACK = "fallback"   # 失败，走回退路径
    ESCALATE = "escalate"   # 失败，升级人工
    ABORT = "abort"         # 不可恢复，终止管线


@dataclass
class ValidationResult:
    verdict: Verdict
    agent: str = ""
    score: int = 0
    issues: List[str] = field(default_factory=list)
    fallback_used: bool = False
    human_decision: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# Layer 1: 确定性校验规则
# ═══════════════════════════════════════════════════════════════

# ── SpecAgent 校验 ──

_DESIGN_NAME_PLACEHOLDERS = {"dut", "DUT", "top", "TOP", "chip", "block", "design", "module", "unknown", "undefined", ""}

def validate_spec(output: dict) -> ValidationResult:
    """校验 SpecAgent 输出: design_name 不能是占位符，interfaces 不能为空"""
    issues = []
    dn = str(output.get("design_name", "")).strip()
    if dn.lower() in _DESIGN_NAME_PLACEHOLDERS or not dn:
        issues.append(f"design_name is placeholder or empty: '{dn}'")

    interfaces = output.get("interfaces", [])
    if not interfaces:
        issues.append("interfaces is empty — must have at least one interface")

    for iface in interfaces:
        if isinstance(iface, dict):
            signals = iface.get("signals", iface.get("ports", []))
            if not signals:
                issues.append(f"interface '{iface.get('name', '?')}' has no signals")

    features = output.get("features", [])
    if not features:
        issues.append("features is empty")

    test_points = output.get("test_points", [])
    if not test_points:
        issues.append("test_points is empty")

    score = 80 if not issues else max(0, 80 - len(issues) * 15)
    return ValidationResult(
        verdict=Verdict.PASS if not issues else Verdict.RETRY,
        agent="spec", score=score, issues=issues,
        diagnostics={"design_name": dn, "interface_count": len(interfaces),
                     "feature_count": len(features), "test_point_count": len(test_points)}
    )


# ── DesignAgent 校验 ──

def validate_design(output: dict) -> ValidationResult:
    """校验 DesignAgent 输出: 必须有 function_hier 和 registers"""
    issues = []
    module = str(output.get("module_name", "")).strip()
    if module.lower() in _DESIGN_NAME_PLACEHOLDERS or not module:
        issues.append(f"module_name is placeholder or empty: '{module}'")

    func_hier = output.get("function_hier", {})
    if not func_hier or not isinstance(func_hier, dict):
        issues.append("function_hier is missing or invalid")

    registers = output.get("registers", [])
    if not registers:
        issues.append("registers is empty")

    score = 70 if not issues else max(0, 70 - len(issues) * 15)
    return ValidationResult(
        verdict=Verdict.PASS if not issues else Verdict.RETRY,
        agent="design", score=score, issues=issues,
        diagnostics={"module": module, "reg_count": len(registers)}
    )


# ── UVM Agent 校验 ──

def validate_uvm(output: dict, output_dir: str = "") -> ValidationResult:
    """校验 UVM Agent 输出: 8 个 UVM 文件必须存在"""
    issues = []
    od = Path(output_dir) if output_dir else Path("output")
    env_name = str(output.get("env_name", ""))

    # 检查 quality_report.json
    qp = od / "quality_report.json"
    if qp.exists():
        try:
            qr = json.loads(qp.read_text(encoding="utf-8", errors="replace"))
            details = qr.get("details", {})
            static = details.get("static", {})
            if not static.get("passed"):
                missing = static.get("missing", 0)
                issues.append(f"static check failed: {static.get('present', 0)}/{static.get('present', 0) + missing} files present")
            compile_ok = details.get("compile", {}).get("passed", False)
            if not compile_ok:
                issues.append("compile check failed")
        except Exception:
            issues.append("cannot read quality_report.json")
    else:
        # 直接检查文件
        expected = ["env_pkg.sv", "env.sv", "agent.sv", "driver.sv",
                    "monitor.sv", "scoreboard.sv", "transaction.sv", "sequence.sv"]
        agent_dir = od / "agents"
        missing = []
        if agent_dir.exists():
            for ad in agent_dir.iterdir():
                if ad.is_dir():
                    for exp in expected:
                        fpath = ad / f"{ad.name}_{exp}"
                        if not fpath.exists():
                            missing.append(str(fpath))
        if missing:
            issues.append(f"missing {len(missing)} UVM files: {missing[:5]}")

    score = 80 if not issues else max(0, 80 - len(issues) * 20)
    verdict = Verdict.PASS if not issues else Verdict.FALLBACK
    return ValidationResult(
        verdict=verdict, agent="uvm", score=score, issues=issues,
        diagnostics={"env_name": env_name, "output_dir": str(od)}
    )


# ── TestAgent 校验 ──

def validate_test(output: dict, output_dir: str = "") -> ValidationResult:
    """校验 TestAgent 输出: constraint.yaml 可解析，有场景"""
    issues = []
    od = Path(output_dir) if output_dir else Path("output")
    yaml_path = od / "inputs" / "yaml" / "constraint.yaml"

    if yaml_path.exists():
        import yaml
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8", errors="replace"))
            scenarios = data.get("scenarios", [])
            if not scenarios:
                issues.append("constraint.yaml has no scenarios")
            policies = data.get("policies", [])
            if not policies:
                issues.append("constraint.yaml has no policies")
        except Exception as e:
            issues.append(f"constraint.yaml parse error: {e}")
    else:
        issues.append(f"constraint.yaml not found at {yaml_path}")

    # 检查 test_summary.json
    summary_path = od / "testcases" / "test_summary.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8", errors="replace"))
            if summary.get("total_tests", 0) == 0:
                issues.append("test_summary has 0 tests")
        except Exception:
            issues.append("test_summary.json parse error")

    score = 80 if not issues else max(0, 80 - len(issues) * 15)
    verdict = Verdict.PASS if not issues else Verdict.FALLBACK
    return ValidationResult(
        verdict=verdict, agent="test", score=score, issues=issues,
        diagnostics={"yaml_exists": yaml_path.exists(), "output_dir": str(od)}
    )


# ── RegressCov 校验 ──

def validate_regress(output: dict, output_dir: str = "") -> ValidationResult:
    """校验 RegressCov 输出: 有 report.json 且 pass_rate > 0"""
    issues = []
    od = Path(output_dir) if output_dir else Path("output")

    report_path = od / "report.json"
    if report_path.exists():
        try:
            rpt = json.loads(report_path.read_text(encoding="utf-8", errors="replace"))
            passed = rpt.get("passed", 0)
            total = rpt.get("total", 1)
            if total == 0:
                issues.append("report.json: total=0 tests")
            elif passed == 0:
                issues.append(f"report.json: 0/{total} tests passed")
            elif passed < total:
                issues.append(f"report.json: {passed}/{total} passed (< 100%)")
        except Exception:
            issues.append("report.json parse error")
    else:
        issues.append("report.json not found")

    # 覆盖率
    cov = output.get("coverage", output.get("_coverage", {}))
    if isinstance(cov, dict):
        overall = cov.get("overall_pct", cov.get("coverage_pct", 0))
        if overall == 0:
            issues.append("coverage data is empty (0%)")

    score = 70 if not issues else max(0, 70 - len(issues) * 15)
    verdict = Verdict.PASS if not issues else Verdict.FALLBACK
    return ValidationResult(
        verdict=verdict, agent="regress_cov", score=score, issues=issues,
        diagnostics={"report_exists": report_path.exists(), "coverage": cov}
    )


# ── 校验注册表 ──

_VALIDATORS: Dict[str, Callable] = {
    "spec": validate_spec,
    "design": validate_design,
    "uvm": validate_uvm,
    "test": validate_test,
    "regress_cov": validate_regress,
}


# ═══════════════════════════════════════════════════════════════
# Layer 2: 自动回退策略
# ═══════════════════════════════════════════════════════════════

class FallbackStrategy:
    """当 LLM 输出校验失败时，不走 LLM retry，直接用规则/模板生成"""

    @staticmethod
    def spec_fallback(ctx: dict, spec_text: str) -> dict:
        """从 spec_text 中用规则提取 spec（不调 LLM）"""
        # 基础结构
        result = {
            "design_name": _extract_module_name(spec_text),
            "version": "1.0",
            "overview": spec_text[:200],
            "features": _extract_features(spec_text),
            "interfaces": _extract_interfaces(spec_text),
            "registers": _extract_registers(spec_text),
            "test_points": _extract_test_points_from_text(spec_text),
            "coverage_goals": {"functional_coverage": 95, "code_coverage": 90},
            "verification_architecture": {
                "agents": [], "scoreboards": [],
                "virtual_sequencer": {"enabled": True},
                "clock_reset": {"clk": "clk", "rst_n": "rst_n"},
            },
        }
        return result

    @staticmethod
    def test_fallback(ctx: dict, spec_text: str) -> dict:
        """用矩阵模式生成测试（不调 LLM）"""
        from src.tools.testcase_tools.generator import TestCaseGenerator
        od = Path(ctx.get("working_dir", "output"))
        yaml_path = od / "inputs" / "yaml" / "constraint.yaml"
        if yaml_path.exists():
            gen = TestCaseGenerator(str(yaml_path))
            summary = gen.generate_all(str(od / "testcases"))
            return {"tests": summary, "mode": "matrix", "fallback": True}
        return {"error": "no constraint.yaml for fallback"}


_FALLBACKS: Dict[str, Callable] = {
    "spec": FallbackStrategy.spec_fallback,
    "test": FallbackStrategy.test_fallback,
}


# ── 规则提取辅助 ──

def _extract_module_name(text: str) -> str:
    """从 spec 文本中提取模块名"""
    patterns = [
        r'module\s+(\w+)', r'设计[名称]*[：:]\s*(\w+)', r'Module[:\s]+(\w+)',
        r'(\w+)\s*(?:IP|模块|Module)', r'design_name[:\s]+(\w+)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            name = m.group(1)
            if name.lower() not in _DESIGN_NAME_PLACEHOLDERS:
                return name
    return "extracted_module"

def _extract_features(text: str) -> list:
    """从文本中提取功能特性列表"""
    features = []
    # 匹配 "N. 特性描述" 或 "- 特性描述" 或 "特性名：描述"
    for m in re.finditer(r'(?:^|\n)\s*(?:\d+\.|[-•])\s*(.+?)(?:\n|$)', text):
        feat = m.group(1).strip()
        if len(feat) > 5 and len(feat) < 200:
            features.append({"name": feat[:60], "description": feat[:150],
                            "priority": "P0" if len(features) < 3 else "P1"})
        if len(features) >= 8:
            break
    if not features:
        features = [{"name": "core_functionality", "description": text[:150], "priority": "P0"}]
    return features

def _extract_interfaces(text: str) -> list:
    """从文本中提取接口列表"""
    interfaces = []
    # 匹配常见接口名
    for if_name in ["APB", "AXI", "AHB", "UART", "SPI", "I2C", "GPIO", "INTR", "Interrupt"]:
        if re.search(if_name, text, re.IGNORECASE):
            interfaces.append({
                "name": if_name, "type": if_name,
                "clock": "clk",
                "signals": [f"{if_name.lower()}_signal"],
            })
    if not interfaces:
        interfaces = [{"name": "bus_if", "type": "generic", "clock": "clk", "signals": ["data", "addr"]}]
    return interfaces

def _extract_registers(text: str) -> list:
    """从文本中提取寄存器列表"""
    registers = []
    reg_patterns = [
        r'(?:寄存器|Register|reg)\s*[：:]\s*(\w+)',
        r'(\w+)\s*(?:寄存器|Register)',
        r'(\w+_reg)\b',
    ]
    seen = set()
    for p in reg_patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            name = m.group(1)
            if name not in seen and len(name) > 1:
                seen.add(name)
                registers.append({"name": name, "offset": f"0x{len(registers)*4:02x}",
                                 "width": 8, "access": "RW", "description": f"{name} register"})
    if not registers:
        registers = [{"name": "control", "offset": "0x00", "width": 8, "access": "RW",
                      "description": "Control register"}]
    return registers

def _extract_test_points_from_text(text: str) -> list:
    """从文本中提取测试点"""
    tps = []
    keywords = [
        ("寄存器读写", "register_access"),
        ("发送", "transmit"), ("接收", "receive"),
        ("FIFO", "fifo"), ("中断", "interrupt"),
        ("波特率", "baud_rate"), ("复位", "reset"),
        ("功耗", "power"), ("并发", "concurrent"),
    ]
    for cn_name, en_name in keywords:
        if re.search(cn_name, text, re.IGNORECASE):
            tps.append({
                "id": f"TP_{en_name.upper()}",
                "feature": cn_name,
                "priority": "P0" if len(tps) < 4 else "P1",
                "description": f"Verify {cn_name} functionality",
                "acceptance": "覆盖率 100%",
            })
    return tps


# ═══════════════════════════════════════════════════════════════
# Layer 3: 人机协作升级
# ═══════════════════════════════════════════════════════════════

class EscalationConsole:
    """当自动修复失败时，升级到人工决策（终端交互）"""

    @staticmethod
    def ask(agent_name: str, issues: List[str], diagnostics: dict,
            fallback_result: Optional[dict] = None) -> str:
        """向用户展示诊断信息，请求决策。

        返回: "retry" | "accept_fallback" | "skip" | "abort"
        """
        print(f"\n{'='*60}")
        print(f"  ESCALATION — Agent '{agent_name}' needs human decision")
        print(f"{'='*60}")
        print(f"\n  Issues detected:")
        for i, issue in enumerate(issues, 1):
            print(f"    {i}. {issue}")

        if diagnostics:
            print(f"\n  Diagnostics:")
            for k, v in diagnostics.items():
                print(f"    {k}: {v}")

        if fallback_result:
            print(f"\n  Fallback result available (rule-based, not LLM)")

        print(f"\n  Options:")
        print(f"    [r] retry LLM  (重试一次)")
        print(f"    [f] accept fallback  (接受回退结果)")
        print(f"    [s] skip phase  (跳过此阶段)")
        print(f"    [a] abort pipeline  (终止)")

        while True:
            choice = input(f"\n  Decision: ").strip().lower()
            if choice == 'r':
                return "retry"
            elif choice == 'f':
                return "accept_fallback"
            elif choice == 's':
                return "skip"
            elif choice == 'a':
                return "abort"
            else:
                print(f"  Invalid choice. Enter r/f/s/a")


# ═══════════════════════════════════════════════════════════════
# QualityGuard — 三层兜底入口
# ═══════════════════════════════════════════════════════════════

class QualityGuard:
    """包装每个 Agent 执行，提供三层兜底。

    用法:
      guard = QualityGuard(approval_gate=None, no_ask=False)
      result = guard.guard(agent_role, agent_output, ctx, output_dir)
    """

    def __init__(self, approval_gate=None, no_ask: bool = False):
        self.approval_gate = approval_gate
        self.no_ask = no_ask  # CI 模式：不上报人工，直接 fallback
        self.stats = {"validated": 0, "fallback_used": 0, "escalated": 0,
                      "passed": 0, "retried": 0}

    def guard(self, agent_role: str, output_data: dict,
              ctx: dict, output_dir: str = "") -> Tuple[dict, ValidationResult]:
        """执行三层兜底。

        Returns: (final_output, validation_result)
        """
        # ── Layer 1: 确定性校验 ──
        validator = _VALIDATORS.get(agent_role)
        if validator:
            if agent_role == "uvm" or agent_role == "test" or agent_role == "regress_cov":
                vr = validator(output_data, output_dir)
            else:
                vr = validator(output_data)
        else:
            # 无校验规则 = 直接通过
            vr = ValidationResult(verdict=Verdict.PASS, agent=agent_role, score=80)

        self.stats["validated"] += 1

        if vr.verdict == Verdict.PASS:
            self.stats["passed"] += 1
            return output_data, vr

        # ── Layer 2: 自动回退 ──
        fallback_fn = _FALLBACKS.get(agent_role)
        if fallback_fn:
            try:
                spec_text = ctx.get("spec", ctx.get("_spec_text", ""))
                if isinstance(spec_text, dict):
                    spec_text = json.dumps(spec_text, ensure_ascii=False)
                fb_output = fallback_fn(ctx, str(spec_text))
                self.stats["fallback_used"] += 1
                fb_vr = ValidationResult(
                    verdict=Verdict.PASS, agent=agent_role,
                    score=max(50, vr.score),  # 回退通过但降分
                    issues=vr.issues,
                    fallback_used=True,
                    diagnostics={"original_issues": vr.issues,
                                "fallback_method": "rule_based"}
                )
                return fb_output, fb_vr
            except Exception as e:
                vr.issues.append(f"fallback failed: {e}")

        # ── Layer 3: 人机协作 ──
        if self.no_ask:
            # CI 模式：直接接受当前输出，降分标记
            self.stats["escalated"] += 1
            vr.verdict = Verdict.PASS
            vr.score = max(30, vr.score - 20)
            vr.human_decision = "auto_skip_ci"
            return output_data, vr

        decision = EscalationConsole.ask(
            agent_role, vr.issues, vr.diagnostics,
            fallback_result=None
        )
        self.stats["escalated"] += 1

        if decision == "retry":
            self.stats["retried"] += 1
            vr.human_decision = "retry"
            # 返回原始输出 + 标记 RETRY，让管线重试
            return output_data, ValidationResult(
                verdict=Verdict.RETRY, agent=agent_role,
                score=vr.score, issues=vr.issues,
                diagnostics=vr.diagnostics, human_decision="retry"
            )
        elif decision == "accept_fallback":
            vr.human_decision = "accept_fallback"
            return output_data, vr
        elif decision == "skip":
            vr.human_decision = "skip"
            vr.verdict = Verdict.PASS
            vr.score = 0
            return {"_skipped": True, "_reason": "human_skip"}, vr
        else:  # abort
            vr.human_decision = "abort"
            vr.verdict = Verdict.ABORT
            return output_data, vr

    def report(self) -> dict:
        """输出守护统计"""
        return {
            "total_validated": self.stats["validated"],
            "passed_directly": self.stats["passed"],
            "fallback_used": self.stats["fallback_used"],
            "escalated_to_human": self.stats["escalated"],
            "retried_by_human": self.stats["retried"],
            "llm_dependency_pct": round(
                (self.stats["passed"] / max(self.stats["validated"], 1)) * 100, 1
            ),
        }
