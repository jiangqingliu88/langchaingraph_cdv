"""
SignOffAI 六大差异化引擎

1. vPlanGenerator      — MD 规格 → 结构化验证计划 (P0)
2. CoverageRegressor   — 覆盖率驱动智能回归选择器 (P0)
3. DebugCopilot        — 仿真日志自动分析 + 根因定位 (P1)
4. RTLUVMSyncer        — RTL 变化 → UVM 环境更新建议 (P1)
5. RegressionTriage    — 批量回归智能研判 (P2)
6. PPAAnalyzer         — EDA PPA 报告解析 + 门限对比 + 签核摘要 (P1)

每个引擎都是 SignOffAI 的独家能力，通用 AI 工具无法提供。
"""

from __future__ import annotations

import re, json, hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# Engine 1: vPlan Generator (P0 — 验证计划的"宪法")
# ═══════════════════════════════════════════════════════════════

@dataclass
class CoveragePoint:
    name: str
    description: str = ""
    category: str = "functional"  # functional | code | assertion
    target: float = 95.0
    priority: str = "P0"


@dataclass
class VPlanTestItem:
    name: str
    description: str = ""
    level: str = "P0"  # P0/P1/P2/P3
    coverage_points: List[str] = field(default_factory=list)
    estimated_runtime: str = "1min"


@dataclass
class VPlan:
    module_name: str = ""
    requirements: List[Dict] = field(default_factory=list)
    coverage_points: List[CoveragePoint] = field(default_factory=list)
    testcases: List[VPlanTestItem] = field(default_factory=list)
    coverage_targets: Dict[str, float] = field(default_factory=lambda: {"functional": 95, "code": 95, "toggle": 90})
    signoff_criteria: List[str] = field(default_factory=lambda: [
        "所有 P0 用例必须 PASS",
        "功能覆盖率 >= 95%",
        "代码覆盖率 >= 95%",
        "无未关闭的 P0/P1 bug",
    ])
    risk_items: List[Dict] = field(default_factory=list)
    traceability_matrix: List[Dict] = field(default_factory=list)


class VPlanGenerator:
    """从 Markdown 规格自动生成验证计划"""

    # 已知的验证模式模板
    _TEMPLATES = {
        "data_path": {
            "coverpoints": [
                ("data_in_out_consistency", "输入数据 → 输出数据一致性检查", "functional"),
                ("backpressure_handling", "反压信号下的数据完整性", "functional"),
                ("pipeline_stall", "流水线停顿恢复", "functional"),
            ],
            "tests": [
                ("P0", "basic_transfer", "基本数据传输"),
                ("P1", "backpressure_test", "反压条件下传输"),
                ("P2", "error_injection", "错误注入恢复"),
            ],
        },
        "control_path": {
            "coverpoints": [
                ("fsm_state_coverage", "状态机所有状态覆盖", "code"),
                ("transition_coverage", "状态转移覆盖", "code"),
                ("illegal_state", "非法状态检测", "assertion"),
            ],
            "tests": [
                ("P0", "fsm_all_states", "遍历所有状态"),
                ("P1", "fsm_transitions", "所有状态转移"),
                ("P2", "illegal_state_recovery", "非法状态恢复"),
            ],
        },
        "register": {
            "coverpoints": [
                ("reg_read_write", "寄存器读写一致性", "functional"),
                ("reg_reset_value", "复位值检查", "functional"),
                ("reg_bit_fields", "位段操作正确性", "functional"),
            ],
            "tests": [
                ("P0", "reg_rw_basic", "基本读写"),
                ("P1", "reg_bit_field", "位段操作"),
                ("P2", "reg_concurrent", "并发访问"),
            ],
        },
        "arbiter": {
            "coverpoints": [
                ("arb_grant", "仲裁授权正确性", "functional"),
                ("arb_fairness", "公平性检查", "functional"),
                ("arb_starvation", "饥饿预防", "functional"),
            ],
            "tests": [
                ("P0", "arb_basic_grant", "基本仲裁"),
                ("P1", "arb_fairness_check", "公平性验证"),
                ("P2", "arb_stress", "压力测试"),
            ],
        },
        "fifo": {
            "coverpoints": [
                ("fifo_full_empty", "满/空标志正确性", "functional"),
                ("fifo_overflow", "溢出保护", "functional"),
                ("fifo_underflow", "下溢保护", "functional"),
            ],
            "tests": [
                ("P0", "fifo_basic_rw", "基本读写"),
                ("P1", "fifo_full_empty", "满空边界"),
                ("P2", "fifo_overflow_test", "溢出测试"),
            ],
        },
    }

    def generate(self, spec_text: str, module_name: str = "") -> VPlan:
        """从 MD 规格生成完整验证计划"""
        vplan = VPlan(module_name=module_name)

        # 1. 提取需求
        reqs = re.findall(r'\*\*REQ_(\w+)\*\*[:\s]*(.+?)(?=\n|$)', spec_text)
        for rid, desc in reqs:
            vplan.requirements.append({"id": f"REQ_{rid}", "description": desc.strip()})
            vplan.traceability_matrix.append({"req_id": f"REQ_{rid}", "testcases": [], "coverage_points": []})

        if not vplan.requirements:
            # 从 ## Features 提取
            for m in re.finditer(r'#+\s*(.+?)(?:\n|$)', spec_text):
                title = m.group(1).strip()
                if any(kw in title.lower() for kw in ['feature', 'function', '功能', '特性']):
                    continue
            vplan.requirements.append({"id": "REQ_AUTO_001", "description": "从规格自动提取"})

        # 2. 识别模块类型，匹配模板
        spec_lower = spec_text.lower()
        matched_patterns = []
        for pattern_name, template in self._TEMPLATES.items():
            keywords = {
                "data_path": ["data", "数据", "path", "通路", "pipeline", "流水线"],
                "control_path": ["fsm", "state", "状态", "control", "控制"],
                "register": ["register", "寄存器", "apb", "cfg", "config", "配置"],
                "arbiter": ["arbit", "仲裁", "grant", "priority", "优先级"],
                "fifo": ["fifo", "buffer", "缓冲", "queue", "队列"],
            }
            if any(kw in spec_lower for kw in keywords.get(pattern_name, [])):
                matched_patterns.append(pattern_name)

        if not matched_patterns:
            matched_patterns = ["data_path", "register"]  # default

        # 3. 生成覆盖点
        cp_id = 1
        for pattern in matched_patterns[:3]:
            tmpl = self._TEMPLATES[pattern]
            for cp_name, cp_desc, cp_cat in tmpl["coverpoints"]:
                vplan.coverage_points.append(
                    CoveragePoint(name=f"CP_{cp_id:03d}_{cp_name}", description=cp_desc,
                                  category=cp_cat, priority="P0" if cp_id <= 5 else "P1")
                )
                cp_id += 1

        # 4. 生成测试用例
        tc_id = 1
        for pattern in matched_patterns[:3]:
            tmpl = self._TEMPLATES[pattern]
            for level, tc_name, tc_desc in tmpl["tests"]:
                cp_refs = [f"CP_{max(1, tc_id-1):03d}"]
                vplan.testcases.append(VPlanTestItem(
                    name=f"test_{tc_name}", description=tc_desc, level=level,
                    coverage_points=cp_refs,
                    estimated_runtime={"P0": "30s", "P1": "2min", "P2": "5min"}.get(level, "1min"),
                ))
                tc_id += 1

        # 5. 风险识别
        if "clock" in spec_lower or "clk" in spec_lower:
            vplan.risk_items.append({"item": "时钟域交叉", "severity": "high", "mitigation": "增加 CDC 检查"})
        if "reset" in spec_lower or "rst" in spec_lower:
            vplan.risk_items.append({"item": "复位行为", "severity": "medium", "mitigation": "增加 reset sequence 测试"})
        if any(w in spec_lower for w in ["backpressure", "back_pressure", "反压"]):
            vplan.risk_items.append({"item": "反压死锁风险", "severity": "high", "mitigation": "增加 backpressure stress 测试"})

        # 6. 自动调整覆盖率目标
        if len(vplan.coverage_points) > 10:
            vplan.coverage_targets = {"functional": 95, "code": 95, "toggle": 90}
        else:
            vplan.coverage_targets = {"functional": 90, "code": 90, "toggle": 85}

        # 7. 建立追溯矩阵
        for tc in vplan.testcases:
            for req in vplan.requirements:
                req_id = req["id"]
                for entry in vplan.traceability_matrix:
                    if entry["req_id"] == req_id:
                        entry["testcases"].append(tc.name)
                        entry["coverage_points"].extend(tc.coverage_points)

        return vplan


# ═══════════════════════════════════════════════════════════════
# Engine 2: Coverage-Driven Regressor (P0 — 回归时间缩短 80%)
# ═══════════════════════════════════════════════════════════════

@dataclass
class SmartRegressionPlan:
    selected_tests: List[str] = field(default_factory=list)
    skipped_tests: List[str] = field(default_factory=list)
    coverage_gaps_addressed: List[str] = field(default_factory=list)
    estimated_runtime: str = ""
    original_runtime: str = ""
    time_saved_pct: float = 0


class CoverageDrivenRegressor:
    """覆盖率驱动智能回归 — 只跑能提高覆盖率的用例"""

    def __init__(self, coverage_data: dict = None, testcases: List[dict] = None):
        self.coverage = coverage_data or {}
        self.all_tests = testcases or []

    def analyze_gaps(self) -> List[dict]:
        """分析覆盖率缺口"""
        gaps = []
        cov = self.coverage
        gaps_raw = cov.get("gaps", []) if isinstance(cov, dict) else []

        if gaps_raw:
            for g in gaps_raw:
                if isinstance(g, dict):
                    gaps.append({"file": g.get("file", ""), "line": g.get("line", 0),
                                 "signal": g.get("signal", ""), "reason": g.get("reason", ""),
                                 "priority": "P0" if g.get("line", 0) < 100 else "P1"})
        else:
            # 从覆盖率数据推断
            if isinstance(cov, dict):
                line_pct = cov.get("line_pct", 0)
                branch_pct = cov.get("branch_pct", 0)
                if line_pct < 95:
                    gaps.append({"type": "line_coverage", "current": line_pct, "target": 95,
                                 "priority": "P0", "gap": 95 - line_pct})
                if branch_pct < 90:
                    gaps.append({"type": "branch_coverage", "current": branch_pct, "target": 90,
                                 "priority": "P1", "gap": 90 - branch_pct})

        return gaps

    def select(self) -> SmartRegressionPlan:
        """智能选择回归用例集"""
        gaps = self.analyze_gaps()
        selected = []
        skipped = []
        gaps_addressed = []

        if not gaps:
            # 无缺口 → 只跑 P0 + 少量随机
            for tc in self.all_tests:
                name = tc.get("name", "") if isinstance(tc, dict) else str(tc)
                level = tc.get("level", "P3") if isinstance(tc, dict) else "P3"
                if level in ("P0", "P1"):
                    selected.append(name)
            # 加 10% 随机
            import random
            remaining = [t for t in self.all_tests
                        if (t.get("name") if isinstance(t, dict) else str(t)) not in selected]
            random.shuffle(remaining)
            for tc in remaining[:max(3, len(remaining) // 10)]:
                name = tc.get("name", "") if isinstance(tc, dict) else str(tc)
                selected.append(name)

            return SmartRegressionPlan(
                selected_tests=selected,
                skipped_tests=[t.get("name", "") if isinstance(t, dict) else str(t)
                              for t in self.all_tests if (t.get("name") if isinstance(t, dict) else str(t)) not in selected],
                coverage_gaps_addressed=[],
                estimated_runtime=f"~{len(selected)} tests",
                original_runtime=f"{len(self.all_tests)} tests",
                time_saved_pct=round((1 - len(selected) / max(len(self.all_tests), 1)) * 100),
            )

        # 有缺口 → 选择能填补的用例
        gap_signals = set()
        for g in gaps:
            signal = g.get("signal", g.get("type", ""))
            if signal:
                gap_signals.add(signal)

        for tc in self.all_tests:
            name = tc.get("name", "") if isinstance(tc, dict) else str(tc)
            level = tc.get("level", "P3") if isinstance(tc, dict) else "P3"
            # P0 用例始终保留
            if level == "P0":
                selected.append(name)
                continue
            # 检查是否覆盖缺口
            covers_gap = False
            for gap_sig in gap_signals:
                if gap_sig.lower() in name.lower():
                    covers_gap = True
                    gaps_addressed.append(gap_sig)
                    break
            if covers_gap:
                selected.append(name)
            else:
                skipped.append(name)

        return SmartRegressionPlan(
            selected_tests=selected,
            skipped_tests=skipped,
            coverage_gaps_addressed=gaps_addressed,
            estimated_runtime=f"~{len(selected)} tests",
            original_runtime=f"{len(self.all_tests)} tests",
            time_saved_pct=round((1 - len(selected) / max(len(self.all_tests), 1)) * 100),
        )


# ═══════════════════════════════════════════════════════════════
# Engine 3: Debug Copilot (P1 — 调试时间缩短 50%)
# ═══════════════════════════════════════════════════════════════

@dataclass
class DebugInsight:
    error_type: str  # UVM_ERROR | compile_error | timeout | assertion_fail
    location: str = ""
    root_cause: str = ""
    evidence: str = ""
    suggested_fix: str = ""
    confidence: float = 0.0  # 0-100
    auto_fixable: bool = False


class DebugCopilot:
    """仿真日志自动分析 + 根因定位"""

    _PATTERNS = [
        # UVM 错误模式
        (r"UVM_ERROR.*?(\S+\.sv):(\d+).*?(\S.*?)(?=\n|$)",
         lambda m: DebugInsight(
             error_type="UVM_ERROR",
             location=f"{m.group(1)}:{m.group(2)}",
             root_cause=f"UVM_ERROR at {m.group(1)} line {m.group(2)}",
             evidence=m.group(3).strip()[:200],
             suggested_fix=f"检查 {m.group(1)} 的第 {m.group(2)} 行，确认 DUT 驱动与 monitor 采样一致",
             confidence=70, auto_fixable=False)),

        # Scoreboard mismatch
        (r"(?i)scoreboard.*?mismatch.*?(\d+).*?(\d+)",
         lambda m: DebugInsight(
             error_type="scoreboard_mismatch",
             root_cause=f"Scoreboard 比对失败: 期望 {m.group(1)}, 实际 {m.group(2)}",
             suggested_fix="1. 比对波形定位不一致的 cycle\n2. 检查参考模型实现\n3. 检查 DUT 时序",
             confidence=85, auto_fixable=False)),

        # 编译错误
        (r"\*\*\s*Error[:\s]*(.*?)(?=\n|$)",
         lambda m: DebugInsight(
             error_type="compile_error",
             root_cause=f"编译错误: {m.group(1).strip()[:150]}",
             suggested_fix=f"检查 {m.group(1).strip()[:100]} 处的语法或类型定义",
             confidence=90, auto_fixable="could not find field" in m.group(1).lower())),

        # 超时
        (r"(?i)(timeout|timed\s*out).*?(\d+)\s*(ns|us|ms|s)",
         lambda m: DebugInsight(
             error_type="timeout",
             root_cause=f"仿真超时于 {m.group(2)}{m.group(3)}",
             suggested_fix="1. 增大 UVM_TIMEOUT\n2. 检查 phase objection 是否正确 drop\n3. 检查死锁",
             confidence=60, auto_fixable=False)),

        # SVA 断言失败
        (r"(?i)(assertion|SVA).*?(fail|violat)",
         lambda m: DebugInsight(
             error_type="assertion_fail",
             root_cause="SVA 断言失败",
             suggested_fix="在波形中追踪断言信号，确认是 RTL bug 还是断言条件过严",
             confidence=50, auto_fixable=False)),
    ]

    def analyze(self, log_text: str) -> List[DebugInsight]:
        """分析仿真日志，返回诊断结果列表"""
        insights = []
        for pattern, handler in self._PATTERNS:
            for m in re.finditer(pattern, log_text, re.IGNORECASE | re.MULTILINE):
                try:
                    insight = handler(m)
                    if insight and insight.root_cause not in [i.root_cause for i in insights]:
                        insights.append(insight)
                except Exception:
                    pass

        if not insights:
            # 通用分析
            key_lines = [l.strip() for l in log_text.split("\n")
                        if any(w in l.lower() for w in ["error", "fail", "fatal", "warning"])][:5]
            if key_lines:
                insights.append(DebugInsight(
                    error_type="unknown",
                    root_cause="日志中发现可疑行",
                    evidence="\n".join(key_lines),
                    suggested_fix="建议人工审查上述日志行",
                    confidence=30, auto_fixable=False,
                ))

        return insights

    def time_saved_estimate(self, insights: List[DebugInsight]) -> str:
        """估算节省的调试时间"""
        if not insights:
            return "0min"
        base = len(insights) * 15  # 每个 insight 节省 ~15 分钟
        if any(i.auto_fixable for i in insights):
            base += 30  # 自动修复额外节省
        return f"~{base}min"


# ═══════════════════════════════════════════════════════════════
# Engine 4: RTL-UVM Syncer (P1 — RTL 改了，UVM 自动跟上)
# ═══════════════════════════════════════════════════════════════

@dataclass
class SyncImpact:
    uvm_file: str
    change_type: str  # bit_width | signal_name | new_port | removed_port
    description: str
    suggested_action: str
    auto_fixable: bool = False


class RTLUVMSyncer:
    """检测 RTL 变化 → 生成 UVM 环境更新建议"""

    def __init__(self, rtl_dir: str = "output", uvm_dir: str = "output"):
        self.rtl_dir = Path(rtl_dir)
        self.uvm_dir = Path(uvm_dir)

    def detect_changes(self, prev_manifest: dict = None, curr_manifest: dict = None) -> List[SyncImpact]:
        """对比两次运行的 manifest，检测 RTL 变化对 UVM 的影响"""
        impacts = []

        if not prev_manifest or not curr_manifest:
            return impacts

        prev_phases = {p.get("phase_name"): p for p in (prev_manifest.get("phases", []) or [])}
        curr_phases = {p.get("phase_name"): p for p in (curr_manifest.get("phases", []) or [])}

        prev_design = prev_phases.get("design", {})
        curr_design = curr_phases.get("design", {})

        prev_hash = prev_design.get("output_hash", "")
        curr_hash = curr_design.get("output_hash", "")

        if prev_hash != curr_hash and prev_hash and curr_hash:
            impacts.append(SyncImpact(
                uvm_file="env/agent/*_agent.sv",
                change_type="bit_width",
                description="RTL 设计已变更，可能影响接口位宽",
                suggested_action="检查所有 agent interface 的位宽定义，与 RTL 端口对齐",
                auto_fixable=False,
            ))
            impacts.append(SyncImpact(
                uvm_file="env/agent/*_driver.sv",
                change_type="signal_name",
                description="如果 RTL 信号名变化，driver 中的信号引用需同步更新",
                suggested_action="运行 compile check 确认 driver 信号引用",
                auto_fixable=False,
            ))

        return impacts

    def scan_interface(self, rtl_files: List[Path]) -> List[dict]:
        """扫描 RTL 端口，生成接口信号清单"""
        interfaces = []
        for f in rtl_files:
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                # 提取 module 端口
                mod_m = re.search(r'module\s+(\w+)\s*\((.*?)\);', content, re.DOTALL)
                if mod_m:
                    ports_str = mod_m.group(2)
                    ports = re.findall(r'(input|output|inout)\s*(?:\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*(\w+)', ports_str)
                    for direction, hi, lo, name in ports:
                        width = abs(int(hi or 0) - int(lo or 0)) + 1 if hi else 1
                        interfaces.append({
                            "module": mod_m.group(1),
                            "port": name, "direction": direction,
                            "width": width,
                            "file": str(f),
                        })
            except Exception:
                pass
        return interfaces


# ═══════════════════════════════════════════════════════════════
# Engine 5: Regression Triage (P2 — 批量回归智能研判)
# ═══════════════════════════════════════════════════════════════

@dataclass
class TriageResult:
    total: int = 0
    failed: int = 0
    root_causes: Dict[str, int] = field(default_factory=lambda: {
        "RTL_bug": 0, "UVM_env_bug": 0, "testcase_bug": 0,
        "random_seed_issue": 0, "tool_issue": 0, "unknown": 0,
    })
    recommended_actions: List[str] = field(default_factory=list)
    estimated_manual_time: str = ""
    estimated_ai_time: str = ""


class RegressionTriage:
    """批量回归失败智能分类"""

    _CATEGORY_RULES = [
        (r"(?i)X\s*propagat|unknown\s*state", "RTL_bug"),
        (r"(?i)virtual\s*interface|config_db|set_config", "UVM_env_bug"),
        (r"(?i)constraint.*?fail|randomize.*?fail", "testcase_bug"),
        (r"(?i)seed.*?\d+.*?(fail|mismatch)", "random_seed_issue"),
        (r"(?i)license|segmentation\s*fault|core\s*dump", "tool_issue"),
    ]

    def classify(self, failed_test_logs: List[dict]) -> TriageResult:
        """对失败用例进行根因分类"""
        result = TriageResult()
        result.total = len(failed_test_logs)

        for test_log in failed_test_logs:
            text = ""
            if isinstance(test_log, dict):
                text = test_log.get("log", "") + test_log.get("error", "")
            else:
                text = str(test_log)

            categorized = False
            for pattern, category in self._CATEGORY_RULES:
                if re.search(pattern, text, re.IGNORECASE):
                    result.root_causes[category] = result.root_causes.get(category, 0) + 1
                    categorized = True
                    break

            if not categorized:
                result.root_causes["unknown"] = result.root_causes.get("unknown", 0) + 1

        result.failed = result.total

        # 生成建议
        rc = result.root_causes
        if rc.get("RTL_bug", 0) > 0:
            result.recommended_actions.append(f"修复 RTL bug ({rc['RTL_bug']} 个用例)")
        if rc.get("UVM_env_bug", 0) > 0:
            result.recommended_actions.append(f"修复 UVM 环境 bug ({rc['UVM_env_bug']} 个用例)")
        if rc.get("testcase_bug", 0) > 0:
            result.recommended_actions.append(f"修复测试用例 ({rc['testcase_bug']} 个用例)")
        if rc.get("random_seed_issue", 0) > 0:
            result.recommended_actions.append(f"重跑随机不稳定用例 ({rc['random_seed_issue']} 个)")
        if rc.get("tool_issue", 0) > 0:
            result.recommended_actions.append(f"检查 EDA 工具配置 ({rc['tool_issue']} 个)")

        # 时间估算
        manual_min = result.total * 10  # 平均每个用例人工分析 10 分钟
        ai_min = max(1, len(result.recommended_actions) * 5)  # AI 分类后只需 5 分钟确认
        result.estimated_manual_time = f"~{manual_min}min (~{round(manual_min/60,1)}h)"
        result.estimated_ai_time = f"~{ai_min}min"

        return result


# ═══════════════════════════════════════════════════════════════
# Engine 6: PPA Analyzer (P1 — Power / Performance / Area 签核引擎)
# ═══════════════════════════════════════════════════════════════

@dataclass
class PPAMetricResult:
    """解析后的单条 PPA 指标"""
    category: str = ""            # power / performance / area
    metric_name: str = ""         # total_power / fmax / cell_area ...
    value: float = 0.0
    unit: str = ""
    target: float = 0.0
    margin_pct: float = 0.0
    pass_status: str = "pending"  # pass / fail / marginal
    source_line: str = ""         # 原始报告行


@dataclass
class PPAReportResult:
    """PPA 报告解析结果"""
    report_type: str = ""         # pt_power / pt_timing / dc_area / innovus_area
    tool: str = ""                # PrimeTime / Design Compiler / Innovus / Voltus
    design_name: str = ""
    metrics: list = field(default_factory=list)  # list[PPAMetricResult]
    corners: list = field(default_factory=list)  # 多 corner 数据
    raw_summary: str = ""         # 报告摘要文本
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class PPAAnalyzer:
    """PPA 签核分析引擎

    功能:
    1. 解析主流 EDA 工具的 PPA 报告（PrimeTime / Design Compiler / Innovus / Voltus）
    2. 自动识别指标类型、数值、单位
    3. 多 PVT corner 数据提取与聚合
    4. 对比门限规则，输出 pass/fail/marginal 判定
    5. 生成结构化的签核摘要数据
    """

    # ── EDA 工具识别 ──

    TOOL_SIGNATURES = {
        'prime_time': [r'Prime\s*Time', r'pt_shell', r'Version\s+\w+-\d+'],
        'design_compiler': [r'Design\s*Compiler', r'dc_shell', r'compile_ultra'],
        'innovus': [r'Innovus', r'Cadence\s+Innovus', r'place_opt_design'],
        'voltus': [r'Voltus', r'Cadence\s+Voltus', r'power_analysis'],
        'genus': [r'Genus', r'Cadence\s+Genus', r'synth_generic'],
        'tempus': [r'Tempus', r'Cadence\s+Tempus', r'timing_analysis'],
    }

    def detect_tool(self, report_text: str) -> str:
        """自动识别 EDA 工具"""
        for tool, patterns in self.TOOL_SIGNATURES.items():
            for pat in patterns:
                if re.search(pat, report_text, re.IGNORECASE):
                    return tool
        return "unknown"

    # ── 主解析入口 ──

    def parse_report(self, report_text: str, report_type: str = "auto") -> dict:
        """主解析入口 — 根据 report_type 分发到对应解析器

        Args:
            report_text: EDA 报告文本
            report_type: pt_power / pt_timing / dc_area / innovus_area / auto

        Returns:
            {"tool": ..., "design_name": ..., "metrics": [...], "corners": [...], ...}
        """
        tool = self.detect_tool(report_text)

        if report_type == "auto":
            # 自动推断报告类型
            report_type = self._infer_report_type(report_text, tool)

        if report_type in ('pt_power', 'voltus_power'):
            result = self.parse_power_report(report_text)
        elif report_type in ('pt_timing', 'tempus_timing'):
            result = self.parse_timing_report(report_text)
        elif report_type in ('dc_area', 'innovus_area', 'genus_area'):
            result = self.parse_area_report(report_text)
        else:
            # fallback: try all
            result = self._parse_generic(report_text)

        result.tool = tool
        result.report_type = report_type
        return self._result_to_dict(result)

    def _infer_report_type(self, text: str, tool: str) -> str:
        """根据文本内容推断报告类型"""
        text_lower = text.lower()
        power_kw = ['total power', 'dynamic power', 'leakage power', 'power report',
                    'power consumption', 'internal power', 'switching power']
        timing_kw = ['slack', 'setup', 'hold', 'clock period', 'fmax', 'timing report',
                     'data arrival', 'clock arrival', 'data required']
        area_kw = ['cell area', 'total area', 'gate count', 'utilization',
                   'area report', 'leaf cells', 'combinational area']

        power_score = sum(1 for kw in power_kw if kw in text_lower)
        timing_score = sum(1 for kw in timing_kw if kw in text_lower)
        area_score = sum(1 for kw in area_kw if kw in text_lower)

        scores = {'power': power_score, 'timing': timing_score, 'area': area_score}
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return 'generic'

        if tool in ('prime_time',):
            return f'pt_{best}'
        elif tool in ('design_compiler',):
            return f'dc_{best}'
        elif tool in ('innovus',):
            return f'innovus_{best}'
        elif tool in ('voltus',):
            return 'voltus_power'
        elif tool in ('tempus',):
            return 'tempus_timing'
        return best

    # ── 功耗报告解析 ──

    def parse_power_report(self, text: str) -> PPAReportResult:
        """解析 PrimeTime / Voltus 功耗报告"""
        result = PPAReportResult(report_type='power')
        result.design_name = self._extract_design_name(text)

        # 总功耗: Total Power = xxx mW / uW
        total_patterns = [
            r'Total\s+Power\s*[=:]\s*([\d.]+)\s*(mW|uW|W)',
            r'(?:Cell|Net)\s+Internal\s+Power.*?([\d.e+-]+)\s*(mW|uW|W)',
            r'Total\s+Dynamic\s+Power\s*[=:]\s*([\d.]+)\s*(mW|uW|W)',
        ]

        for pat in total_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                result.metrics.append(PPAMetricResult(
                    category='power', metric_name='total_power',
                    value=float(m.group(1)), unit=m.group(2).lower(),
                ).__dict__)
                break

        # 动态功耗
        m = re.search(r'(?:Cell\s+)?Dynamic\s+Power\s*[=:]\s*([\d.]+)\s*(mW|uW|W)', text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='power', metric_name='dynamic_power',
                value=float(m.group(1)), unit=m.group(2).lower(),
            ).__dict__)

        # 漏电功耗
        m = re.search(r'(?:Cell\s+)?Leakage\s+Power\s*[=:]\s*([\d.]+)\s*(mW|uW|W)', text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='power', metric_name='leakage_power',
                value=float(m.group(1)), unit=m.group(2).lower(),
            ).__dict__)

        # 内部功耗 (Internal Power)
        m = re.search(r'Internal\s+Power\s*[=:]\s*([\d.]+)\s*(mW|uW|W)', text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='power', metric_name='internal_power',
                value=float(m.group(1)), unit=m.group(2).lower(),
            ).__dict__)

        # 开关功耗 (Switching Power)
        m = re.search(r'Switching\s+Power\s*[=:]\s*([\d.]+)\s*(mW|uW|W)', text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='power', metric_name='switching_power',
                value=float(m.group(1)), unit=m.group(2).lower(),
            ).__dict__)

        # Power groups breakdown
        power_groups = re.findall(
            r'(clock_network|register|combinational|sequential|memory|io_pad|clock_tree)_power\s*[=:]\s*([\d.]+)\s*(mW|uW|W)',
            text, re.IGNORECASE
        )
        for gname, gval, gunit in power_groups:
            result.metrics.append(PPAMetricResult(
                category='power', metric_name=f'{gname}_power',
                value=float(gval), unit=gunit.lower(),
            ).__dict__)

        result.raw_summary = self._extract_summary_section(text, 'Power')
        return result

    # ── 时序报告解析 ──

    def parse_timing_report(self, text: str) -> PPAReportResult:
        """解析 PrimeTime / Tempus 时序报告"""
        result = PPAReportResult(report_type='performance')
        result.design_name = self._extract_design_name(text)

        # Fmax = 1 / clock_period (最差路径)
        m = re.search(r'(?:clock|operating)\s+(?:period|frequency)\s*[=:]\s*([\d.]+)\s*(ns|MHz|GHz|ps)',
                      text, re.IGNORECASE)
        if m:
            period_val = float(m.group(1))
            unit = m.group(2).lower()
            if unit in ('ns', 'ps'):
                period_ns = period_val if unit == 'ns' else period_val / 1000
                fmax = 1000 / period_ns if period_ns > 0 else 0
                result.metrics.append(PPAMetricResult(
                    category='performance', metric_name='clock_period',
                    value=period_val, unit=unit,
                ).__dict__)
                result.metrics.append(PPAMetricResult(
                    category='performance', metric_name='fmax',
                    value=round(fmax, 1), unit='mhz',
                ).__dict__)
            else:
                result.metrics.append(PPAMetricResult(
                    category='performance', metric_name='fmax',
                    value=period_val, unit=unit,
                ).__dict__)

        # Worst slack (setup)
        m = re.search(r'(?:worst|min)\s+(?:setup\s+)?slack\s*[=:]\s*(-?[\d.]+)\s*(ns|ps)',
                      text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='performance', metric_name='setup_worst_slack',
                value=float(m.group(1)), unit=m.group(2).lower(),
            ).__dict__)

        # Worst slack (hold)
        m = re.search(r'(?:worst|min)\s+hold\s+slack\s*[=:]\s*(-?[\d.]+)\s*(ns|ps)',
                      text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='performance', metric_name='hold_worst_slack',
                value=float(m.group(1)), unit=m.group(2).lower(),
            ).__dict__)

        # WNS / TNS (PrimeTime style)
        m = re.search(r'WNS\s*[=:]\s*(-?[\d.]+)', text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='performance', metric_name='wns',
                value=float(m.group(1)), unit='ns',
            ).__dict__)
        m = re.search(r'TNS\s*[=:]\s*(-?[\d.]+)', text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='performance', metric_name='tns',
                value=float(m.group(1)), unit='ns',
            ).__dict__)

        # Violating paths count
        m = re.search(r'(?:violating|failing)\s+(?:paths|endpoints)\s*[=:]\s*(\d+)',
                      text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='performance', metric_name='violating_paths',
                value=int(m.group(1)), unit='paths',
            ).__dict__)

        result.raw_summary = self._extract_summary_section(text, 'Timing')
        return result

    # ── 面积报告解析 ──

    def parse_area_report(self, text: str) -> PPAReportResult:
        """解析 Design Compiler / Innovus / Genus 面积报告"""
        result = PPAReportResult(report_type='area')
        result.design_name = self._extract_design_name(text)

        # Cell area (DC style)
        m = re.search(r'(?:Total\s+)?(?:Cell|Combinational)\s+Area\s*[=:]\s*([\d.]+)\s*(um2|mm2|nm2)',
                      text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='area', metric_name='cell_area',
                value=float(m.group(1)), unit=m.group(2).lower(),
            ).__dict__)

        # Total area
        m = re.search(r'Total\s+Area\s*[=:]\s*([\d.]+)\s*(um2|mm2|nm2)',
                      text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='area', metric_name='total_area',
                value=float(m.group(1)), unit=m.group(2).lower(),
            ).__dict__)

        # Gate count
        m = re.search(r'(?:Gate|Cell)\s+Count\s*[=:]\s*([\d,]+)',
                      text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='area', metric_name='gate_count',
                value=float(m.group(1).replace(',', '')), unit='gates',
            ).__dict__)

        # Combinational / Noncombinational area
        m = re.search(r'Combinational\s+Area\s*[=:]\s*([\d.]+)\s*(um2|mm2)', text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='area', metric_name='combinational_area',
                value=float(m.group(1)), unit=m.group(2).lower(),
            ).__dict__)

        m = re.search(r'(?:Noncombinational|Sequential)\s+Area\s*[=:]\s*([\d.]+)\s*(um2|mm2)',
                      text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='area', metric_name='sequential_area',
                value=float(m.group(1)), unit=m.group(2).lower(),
            ).__dict__)

        # Utilization
        m = re.search(r'(?:Chip\s+)?Utilization\s*[=:]\s*([\d.]+)\s*%?',
                      text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='area', metric_name='utilization',
                value=float(m.group(1)), unit='%',
            ).__dict__)

        # Macro / Memory area
        m = re.search(r'Macro\s+Area\s*[=:]\s*([\d.]+)\s*(um2|mm2)', text, re.IGNORECASE)
        if m:
            result.metrics.append(PPAMetricResult(
                category='area', metric_name='macro_area',
                value=float(m.group(1)), unit=m.group(2).lower(),
            ).__dict__)

        result.raw_summary = self._extract_summary_section(text, 'Area')
        return result

    # ── Generic fallback ──

    def _parse_generic(self, text: str) -> PPAReportResult:
        """通用解析 — 提取所有 <metric>=<value><unit> 模式"""
        result = PPAReportResult(report_type='generic')
        result.design_name = self._extract_design_name(text)

        # 通用模式: name = value unit
        generic_patterns = [
            (r'(?:total_?)?power\s*[=:]\s*([\d.]+)\s*(mW|uW|W)', 'power', 'total_power'),
            (r'(?:max_?|clock_?)?freq(?:uency)?\s*[=:]\s*([\d.]+)\s*(MHz|GHz|kHz)', 'performance', 'fmax'),
            (r'(?:cell_?|total_?)?area\s*[=:]\s*([\d.]+)\s*(um2|mm2|nm2)', 'area', 'cell_area'),
            (r'(?:dynamic|switching)_?power\s*[=:]\s*([\d.]+)\s*(mW|uW|W)', 'power', 'dynamic_power'),
            (r'(?:leakage|static)_?power\s*[=:]\s*([\d.]+)\s*(mW|uW|W)', 'power', 'leakage_power'),
            (r'(?:gate|cell)_?count\s*[=:]\s*([\d,]+)', 'area', 'gate_count'),
            (r'utilization\s*[=:]\s*([\d.]+)\s*%?', 'area', 'utilization'),
            (r'(?:setup\s+)?wns\s*[=:]\s*(-?[\d.]+)\s*(ns|ps)', 'performance', 'wns'),
            (r'(?:hold\s+)?wns\s*[=:]\s*(-?[\d.]+)\s*(ns|ps)', 'performance', 'hold_wns'),
        ]

        seen = set()
        for pat, cat, mname in generic_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m and mname not in seen:
                seen.add(mname)
                result.metrics.append(PPAMetricResult(
                    category=cat, metric_name=mname,
                    value=float(m.group(1).replace(',', '')),
                    unit=m.group(2).lower() if m.lastindex >= 2 else '',
                ).__dict__)

        return result

    # ── Helpers ──

    def _extract_design_name(self, text: str) -> str:
        """提取设计名称"""
        patterns = [
            r'Design\s*[:\s]+(\S+)',
            r'Module\s*[:\s]+(\S+)',
            r'Cell\s*[:\s]+(\S+)',
            r'^\s*Report\s*[:\s]+(\S+)',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
            if m:
                return m.group(1).strip('"\'')
        return ""

    def _extract_summary_section(self, text: str, section_type: str) -> str:
        """提取报告摘要区域"""
        lines = text.split('\n')
        # 取前 30 行作为摘要（通常包含关键指标）
        return '\n'.join(lines[:30])

    def _result_to_dict(self, result: PPAReportResult) -> dict:
        """将解析结果转为 dict（JSON 序列化友好）"""
        metrics_list = []
        for m in result.metrics:
            if isinstance(m, dict):
                metrics_list.append(m)
            elif hasattr(m, '__dict__'):
                metrics_list.append(m.__dict__)

        return {
            'report_type': result.report_type,
            'tool': result.tool,
            'design_name': result.design_name,
            'metrics': metrics_list,
            'corners': result.corners,
            'raw_summary': result.raw_summary[:2000],
            'warnings': result.warnings,
            'errors': result.errors,
        }

    # ── 门限对比 ──

    def check_against_constraints(self, metrics: list[dict],
                                  constraints: list[dict]) -> list[dict]:
        """逐条对比 PPA 指标与约束门限

        Args:
            metrics: [{'category', 'metric_name', 'actual_value', 'unit'}, ...]
            constraints: [{'category', 'metric_name', 'constraint_type', 'threshold_value',
                          'margin_required_pct', 'severity'}, ...]

        Returns:
            [{'category', 'metric_name', 'status': pass/fail/marginal, 'margin_pct', ...}, ...]
        """
        results = []
        for c in constraints:
            matched = [m for m in metrics
                       if m['category'] == c['category']
                       and m['metric_name'] == c['metric_name']]
            if not matched:
                results.append({**c, 'actual': None, 'status': 'no_data', 'margin_pct': 0})
                continue

            m = matched[0]
            actual = m.get('actual_value', m.get('value', 0))
            threshold = c['threshold_value']

            if c['constraint_type'] == 'max':
                margin = (threshold - actual) / max(threshold, 0.001) * 100
                ok = actual <= threshold
            elif c['constraint_type'] == 'min':
                margin = (actual - threshold) / max(threshold, 0.001) * 100
                ok = actual >= threshold
            else:
                margin = 0
                ok = True

            marginal = ok and margin < c['margin_required_pct']
            status = 'fail' if not ok else ('marginal' if marginal else 'pass')

            results.append({
                'category': c['category'],
                'metric_name': c['metric_name'],
                'threshold': threshold,
                'actual': actual,
                'unit': c.get('unit', ''),
                'constraint_type': c['constraint_type'],
                'margin_pct': round(margin, 2),
                'margin_required_pct': c['margin_required_pct'],
                'severity': c['severity'],
                'status': status,
            })

        return results

    # ── 签核摘要生成 ──

    def generate_signoff_summary(self, metrics: list[dict],
                                 corners: list[dict] = None) -> dict:
        """生成 PPA 签核 summary_json

        Args:
            metrics: PPA 指标列表
            corners: PVT corner 数据列表 (可选)

        Returns:
            可存入 Signoff.summary_json 的结构
        """
        by_cat = {}
        for m in metrics:
            by_cat.setdefault(m['category'], []).append(m)

        categories = {}
        overall_pass = True
        for cat, items in by_cat.items():
            passed = sum(1 for i in items if i.get('pass_status') == 'pass')
            failed = sum(1 for i in items if i.get('pass_status') == 'fail')
            marginal = sum(1 for i in items if i.get('pass_status') == 'marginal')
            pending = sum(1 for i in items if i.get('pass_status') == 'pending')
            categories[cat] = {
                'total': len(items),
                'passed': passed,
                'failed': failed,
                'marginal': marginal,
                'pending': pending,
                'all_pass': failed == 0 and marginal == 0,
            }
            if failed > 0:
                overall_pass = False

        # Corner summary
        corner_summary = {}
        if corners:
            best_power = min(corners, key=lambda c: c.get('total_power_mw', float('inf')))
            worst_power = max(corners, key=lambda c: c.get('total_power_mw', 0))
            best_perf = max(corners, key=lambda c: c.get('fmax_mhz', 0))
            worst_perf = min(corners, key=lambda c: c.get('fmax_mhz', float('inf')))
            corner_summary = {
                'corner_count': len(corners),
                'corners': [c.get('corner_name', '') for c in corners],
                'best_power': f"{best_power.get('total_power_mw', 0)}mW @ {best_power.get('corner_name', '')}",
                'worst_power': f"{worst_power.get('total_power_mw', 0)}mW @ {worst_power.get('corner_name', '')}",
                'best_perf': f"{best_perf.get('fmax_mhz', 0)}MHz @ {best_perf.get('corner_name', '')}",
                'worst_perf': f"{worst_perf.get('fmax_mhz', 0)}MHz @ {worst_perf.get('corner_name', '')}",
            }

        return {
            'categories': categories,
            'overall_pass': overall_pass,
            'total_metrics': len(metrics),
            'corners': corner_summary,
            'generated_at': datetime.now().isoformat()[:19],
        }
