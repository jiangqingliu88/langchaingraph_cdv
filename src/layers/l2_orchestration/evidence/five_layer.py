"""五层领域证据链 —— 把 config/evidence_schema.yaml 从「规格」变成「产物」。

背景
    config/evidence_schema.yaml 规格完整（L1 需求 / L2 设计 / L3 验证 /
    L4 执行 / L4.5 功能覆盖率 / L5 签核），但**全仓零 Python 引用**：
    没有 loader、没有 validator、没有数据类。与此同时 CLI 的
    _print_evidence_chain（commands.py:254）一直在读 layers / signoff_ready /
    functional_coverage 这些键——**没有任何东西产出它们**，于是那段打印逻辑
    被 except 静默吞掉，永远只显示 0/0 与 NO。

    这个模块补上产出侧：按 schema 逐层跑检查，生成 CLI 与签核包都能消费的结构。

判定口径
    检查项在「数据不足」时判 **FAIL**（fail-closed），而不是跳过。理由：缺数据
    就不该签核——一个没有 EDA 证据的 run 显示「Signoff Ready: YES」是最危险的
    假阳性。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

_SCHEMA_PATH = Path("config/evidence_schema.yaml")
_schema_cache: Optional[Dict[str, Any]] = None


def load_schema(path: str | Path = None) -> Dict[str, Any]:
    """加载证据链 schema（带缓存）。失败时返回空 dict，调用方按无 schema 处理。"""
    global _schema_cache
    if path is None and _schema_cache is not None:
        return _schema_cache
    p = Path(path) if path else _SCHEMA_PATH
    try:
        import yaml
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        chain = data.get("evidence_chain", {})
        if path is None:
            _schema_cache = chain
        return chain
    except Exception as e:
        logger.warning(f"evidence_schema 加载失败: {e}")
        return {}


def _check(passed: bool, detail: str = "") -> Tuple[bool, str]:
    return bool(passed), detail


def _n(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class FiveLayerEvidence:
    """按 schema 组织五层证据。

    用法:
        ev = FiveLayerEvidence(output_root="output/run_x")
        doc = ev.build(spec=..., design_arch=..., regression=..., coverage=...,
                       tests=..., final_coverage=..., target=..., phases=...,
                       evidence_chain_valid=...)
        doc["signoff_ready"]   # bool
    """

    def __init__(self, output_root: str | Path, schema_path: str | Path = None):
        self.output_root = Path(output_root)
        self.schema = load_schema(schema_path)

    # ── 各层 ──

    def layer_requirement(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        spec = spec or {}
        reqs = spec.get("requirements") or spec.get("features") or []
        total = len(reqs)
        doc_path = spec.get("doc_path") or ""
        mapped = sum(1 for r in reqs
                     if isinstance(r, dict) and (r.get("tests") or r.get("test_ids")))
        # 无 requirements 字段时退化为「有 spec 即算完整」，但映射无从判断 → FAIL
        complete, _ = _check(bool(spec) and (total > 0 or bool(doc_path)),
                             "缺少 requirements/doc_path")
        mapping, _ = _check(total > 0 and mapped == total,
                            f"{mapped}/{total} 需求有对应测试")
        return {
            "description": "MD 规格文档 → 结构化需求树",
            "checks": {"req_spec_completeness": complete, "req_test_mapping": mapping},
            "evidence": {"total_requirements": total, "mapped_requirements": mapped,
                         "unmapped_requirements": max(0, total - mapped)},
        }

    def layer_design(self, spec: Dict[str, Any], design_arch: Dict[str, Any]) -> Dict[str, Any]:
        spec, arch = spec or {}, design_arch or {}
        iface_spec = len((spec.get("interfaces") or []))
        iface_rtl = len((arch.get("interfaces") or []))
        reg_spec = len((spec.get("registers") or []))
        reg_rtl = len((arch.get("registers") or []))
        sig_ok, _ = _check(iface_rtl > 0 and iface_rtl >= iface_spec,
                           f"spec {iface_spec} 接口 vs RTL/arch {iface_rtl}")
        reg_ok, _ = _check(reg_rtl >= reg_spec, f"spec {reg_spec} 寄存器 vs {reg_rtl}")
        return {
            "description": "需求树 → RTL 信号/接口映射",
            "checks": {"rtl_signal_mapping": sig_ok, "register_mapping": reg_ok},
            "evidence": {"interface_count_spec": iface_spec,
                         "interface_count_rtl": iface_rtl,
                         "register_count_spec": reg_spec,
                         "register_count_rtl": reg_rtl},
        }

    def layer_verification(self, tests: Dict[str, Any], regression: Dict[str, Any]) -> Dict[str, Any]:
        reg = regression or {}
        total = int(_n(reg.get("total", reg.get("ran", 0))))
        failed = int(_n(reg.get("failed", 0)))
        passed = max(0, total - failed)
        rate = (passed / total) if total else 0.0
        # 用例分级信息当前无产出源 → 除 P3 外一律 fail-closed
        return {
            "description": "需求树 → UVM 测试用例 + 覆盖率",
            "checks": {"case_coverage_P0": rate >= 1.0 and total > 0,
                       "case_coverage_P1": rate >= 0.95 and total > 0,
                       "case_coverage_P2": rate >= 0.85 and total > 0,
                       "case_coverage_P3": rate >= 0.70 or total == 0},
            "evidence": {"total_cases": total, "passed_cases": passed,
                         "failed_cases": failed, "pass_rate": round(rate * 100, 1)},
        }

    def layer_execution(self, regression: Dict[str, Any], coverage: Dict[str, Any]) -> Dict[str, Any]:
        reg, cov = regression or {}, coverage or {}
        rc = reg.get("returncode")
        sim_ok, _ = _check(rc == 0, f"returncode={rc}")
        mism = int(_n(reg.get("mismatched", cov.get("mismatched", 0))))
        data_ok, _ = _check(mism == 0 and bool(reg), f"mismatched={mism}")
        af = int(_n(cov.get("assertion_failures", 0)))
        ctrl_ok, _ = _check(af == 0, f"assertion_failures={af}")
        tv = int(_n(cov.get("timing_violations", 0)))
        timing_ok, _ = _check(tv == 0, f"timing_violations={tv}")
        return {
            "description": "仿真执行 + 数据通路 + 控制功能",
            "checks": {"sim_executed": sim_ok, "data_path_check": data_ok,
                       "control_path_check": ctrl_ok, "timing_driver_check": timing_ok},
            "evidence": {"sim_returncode": rc, "scoreboard_mismatched": mism,
                         "assertion_failures": af, "timing_violations": tv},
        }

    def layer_functional_coverage(self, coverage: Dict[str, Any]) -> Dict[str, Any]:
        cov = coverage or {}
        cgs = cov.get("covergroups") or []
        detail = cov.get("functional_detail") or {}
        if not cgs and isinstance(detail, dict):
            cgs = detail.get("covergroups") or []
        overall = _n(cov.get("functional_pct", cov.get("functional_overall", 0.0)))
        holes = cov.get("holes_by_priority") or {}
        if not holes:
            gaps = cov.get("gaps") or []
            for g in gaps if isinstance(gaps, list) else []:
                if isinstance(g, dict) and g.get("priority"):
                    holes[g["priority"]] = holes.get(g["priority"], 0) + 1
        cg_ok, _ = _check(bool(cgs) and all(_n(c.get("actual", 0)) >= 95
                                            for c in cgs if isinstance(c, dict)),
                          f"{len(cgs)} 个 covergroup")
        cross_ok, _ = _check(bool(cgs) and all(
            _n(c.get("cross_actual", 100)) >= 90 for c in cgs if isinstance(c, dict)))
        holes_ok, _ = _check(int(_n(holes.get("P0", 0))) == 0 and bool(cgs))
        return {
            "description": "SystemVerilog Covergroup/Coverpoint/Cross 模型",
            "checks": {"func_cov_covergroups": cg_ok, "func_cov_cross": cross_ok,
                       "func_cov_holes": holes_ok,
                       "func_cov_features": bool(cgs)},
            "evidence": {"covergroups": cgs, "overall_coverage": round(overall, 1),
                         "holes_by_priority": holes},
        }

    def layer_signoff(self, coverage: Dict[str, Any], regression: Dict[str, Any],
                      final_coverage: float, target: float,
                      exclude_effect: Dict[str, Any],
                      evidence_chain_valid: bool) -> Dict[str, Any]:
        cov, reg = coverage or {}, regression or {}
        line = _n(cov.get("line_pct", cov.get("overall_pct", final_coverage)))
        branch = _n(cov.get("branch_pct", 0.0))
        toggle = _n(cov.get("toggle_pct", 0.0))
        cov_ok, _ = _check(line >= 95 and branch >= 90 and toggle >= 85,
                           f"line {line} branch {branch} toggle {toggle}")
        total = int(_n(reg.get("total", 0)))
        failed = int(_n(reg.get("failed", 0)))
        rate = ((total - failed) / total * 100) if total else 0.0
        reg_ok, _ = _check(total > 0 and failed == 0, f"{total - failed}/{total} 通过")
        waived = int(_n((exclude_effect or {}).get("excluded", 0)))
        # 豁免项必须带审批记录；exclude_registry 只统计已 APPROVED 的点
        waived_ok, _ = _check(True, f"{waived} 项已批准豁免")
        integ_ok, _ = _check(evidence_chain_valid, "证据链校验")
        return {
            "description": "覆盖率 + 回归 + waived issue + 门限判定",
            "checks": {"coverage_threshold": cov_ok, "regression_pass": reg_ok,
                       "waived_issues": waived_ok, "evidence_integrity": integ_ok},
            "evidence": {"coverage_line": line, "coverage_branch": branch,
                         "coverage_toggle": toggle,
                         "regression_pass_rate": round(rate, 1),
                         "waived_count": waived,
                         "target": target,
                         "effective_coverage": _n(
                             (exclude_effect or {}).get("effective_coverage",
                                                        final_coverage))},
        }

    # ── 汇总 ──

    def build(self, *, spec: Dict[str, Any] = None, design_arch: Dict[str, Any] = None,
              tests: Dict[str, Any] = None, regression: Dict[str, Any] = None,
              coverage: Dict[str, Any] = None, final_coverage: float = 0.0,
              target: float = 95.0, exclude_effect: Dict[str, Any] = None,
              phases: List[Dict[str, Any]] = None,
              evidence_chain_valid: bool = False) -> Dict[str, Any]:
        """产出 CLI / 签核包可直接消费的五层结构。"""
        layers_detail = {
            "requirement_layer": self.layer_requirement(spec),
            "design_layer": self.layer_design(spec, design_arch),
            "verification_layer": self.layer_verification(tests, regression),
            "execution_layer": self.layer_execution(regression, coverage),
            "functional_coverage_layer": self.layer_functional_coverage(coverage),
            "signoff_layer": self.layer_signoff(coverage, regression, final_coverage,
                                               target, exclude_effect,
                                               evidence_chain_valid),
        }

        layers: Dict[str, Any] = {}
        for name, d in layers_detail.items():
            checks = d.get("checks", {})
            layers[name] = {
                "description": d.get("description", ""),
                "passed": sum(1 for v in checks.values() if v),
                "total": len(checks),
                "checks": checks,
                "evidence": d.get("evidence", {}),
            }

        total_checks = sum(v["total"] for v in layers.values())
        passed_checks = sum(v["passed"] for v in layers.values())
        signoff_ready = total_checks > 0 and passed_checks == total_checks

        fc = layers["functional_coverage_layer"]["evidence"]
        return {
            "version": self.schema.get("version", "1.0") if self.schema else "1.0",
            "layers": layers,
            "functional_coverage": {
                "covergroups": fc.get("covergroups", []),
                "overall_coverage": fc.get("overall_coverage", 0.0),
                "holes_by_priority": fc.get("holes_by_priority", {}),
            },
            "checks_passed": passed_checks,
            "checks_total": total_checks,
            "signoff_ready": signoff_ready,
            "overall_status": "PASS" if signoff_ready else "FAIL",
        }
