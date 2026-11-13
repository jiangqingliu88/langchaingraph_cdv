"""VPlan 原生执行引擎 —— 执行期唯一门面。

`executors/`、`tools/` 只 import 这里，不再直接碰运行期实现细节：

    run_testpoints / run_uvm_tests / run_uvm_batches
    run_covergroups / run_coverage_plan
    run_constraints / run_association

输入统一是 `VPlanProject`（由 `load_project_from` 从 run 的 `inputs/vplan/`
或项目根加载）。运行期模型（runtime model）仍然由 `execution.py` 从
`data/*.csv` + `cases/*.yaml` 确定性投影，只是不再落盘给旧建模引擎解析。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .execution import build_runtime_model
from .source import VPlanProject, load_project


def load_project_from(root: str | Path) -> VPlanProject:
    """run 的 `inputs/vplan/` 或项目根 → `VPlanProject`。"""
    return load_project(Path(root))


def project_for(spec: Any, run_root: str | Path) -> Optional[VPlanProject]:
    """这次 run 若是 VPlan 项目 → `VPlanProject`；否则 None（不猜、不回退）。"""
    from src.layers.l1_infrastructure.layout import find_vplan_root

    try:
        root = find_vplan_root(spec, run_root)
        return load_project_from(root) if root is not None else None
    except Exception:                      # noqa: BLE001 读不出项目就当作没有
        return None


def model_text(project: VPlanProject) -> str:
    """运行期模型 → YAML 文本（运行期实现层的唯一输入）。"""
    return yaml.safe_dump(build_runtime_model(project), allow_unicode=True,
                          sort_keys=False)


def load_exec_assets(project: VPlanProject) -> Dict[str, Any]:
    """`data/*.csv` → 执行资产 dict（维度/字段/断言/SCB/交叉/配置）。"""
    from .execution import _load_asset_model

    return _load_asset_model(project.root)


def _models(text: str):
    from .runtime.domain import CaseModelError
    from .runtime.repository import load_models_from_text

    try:
        return load_models_from_text(text, source="<vplan>"), None
    except CaseModelError as exc:
        return None, {"error": str(exc)}


# ═══════════════════════════════════════════════════════════════
# 测试点 IR
# ═══════════════════════════════════════════════════════════════

def testpoints_from_text(text: str, *, env_name: str = "",
                         agents: Optional[Dict[str, List[str]]] = None,
                         module_name: str = "",
                         max_tests: Optional[int] = None) -> Dict[str, Any]:
    from .runtime.plan import run_testpoints as _impl

    return _impl(text, env_name=env_name, agents=agents,
                 module_name=module_name, max_tests=max_tests)


def run_testpoints(project: VPlanProject, *, env_name: str = "",
                   agents: Optional[Dict[str, List[str]]] = None,
                   module_name: str = "",
                   max_tests: Optional[int] = None) -> Dict[str, Any]:
    return testpoints_from_text(
        model_text(project), env_name=env_name, agents=agents,
        module_name=module_name, max_tests=max_tests)


# ═══════════════════════════════════════════════════════════════
# UVM environment.tests / environment.batches
# ═══════════════════════════════════════════════════════════════

def _ascii_key(text: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").lower() or "attr"


def run_uvm_tests(project: VPlanProject, *,
                  dimensions: Optional[List[str]] = None,
                  max_tests: Optional[int] = None) -> Dict[str, Any]:
    """模型取值点 → `environment.tests`（一条 = 一个 UVM_TEST）。"""
    models, error = _models(model_text(project))
    if error:
        return error
    from .runtime.plan import iter_value_points

    model = models[0].resolve()
    wanted = set(dimensions or ())
    picked: List[Dict[str, Any]] = []
    for dim, _fld, _index, point, int_value, tp_id in iter_value_points(model):
        if wanted and not (wanted & {dim.id, dim.name, dim.key}):
            continue
        entry: Dict[str, Any] = {
            "dimension": dim.id or dim.name,
            "value": point.token,
            "key": _ascii_key(dim.id or dim.name),
            "int_value": int_value,
            "tp_id": tp_id,
            "_boundary": bool(point.boundary),
        }
        drive_field = getattr(dim, "stimulus_field", "") or ""
        if drive_field:
            entry["field"] = drive_field
        if str(getattr(dim, "realization_kind", "")).lower() == "backdoor":
            path = str(getattr(dim, "realization_path", "") or "").strip()
            if path:
                entry["backdoor_path"] = path
        if str(getattr(dim, "realization_kind", "")).lower() == "sequence":
            seq_name = str(getattr(dim, "realization_sequence", "") or "").strip()
            if seq_name:
                entry["sequence"] = seq_name
            by_token = getattr(dim, "realization_sequences", {}) or {}
            seq_values = list(by_token.get(str(point.token), []) or [])
            if not seq_values:
                seq_values = list(getattr(dim, "realization_values", []) or [])
            if seq_values:
                entry["sequence_values"] = seq_values
        picked.append(entry)

    total = len(picked)
    truncated = max_tests is not None and 0 <= max_tests < total
    notes: List[str] = []
    if truncated:
        order = sorted(range(total), key=lambda i: (not picked[i]["_boundary"], i))
        keep = sorted(order[:max_tests])
        picked = [picked[i] for i in keep]
        notes.append(
            f"tests 截断到 {max_tests} 条，丢弃 {total - len(picked)} 条"
            f"（优先保留边界取值）；用 --max-tests 调整")
    tests = [{k: v for k, v in entry.items() if not k.startswith("_")}
             for entry in picked]
    return {
        "count": len(tests),
        "total_before_cap": total,
        "truncated": truncated,
        "dropped": total - len(tests),
        "notes": notes,
        "dimensions_used": sorted({t["dimension"] for t in tests}),
        "tests": tests,
        "tests_yaml": yaml.safe_dump({"tests": tests}, allow_unicode=True,
                                     sort_keys=False),
    }


def run_uvm_batches(project: VPlanProject,
                    module_name: str = "dut") -> Dict[str, Any]:
    """VPlan cases → `environment.batches`（一条 = 一个批次/专题）。"""
    text = model_text(project)
    models, error = _models(text)
    if error:
        return error
    from .runtime.associate import _raw_themes, theme_policy_map
    from .runtime.coverage import sv_ident

    model = models[0].resolve()
    raw_themes = _raw_themes(text)
    policy_names = theme_policy_map(raw_themes)
    declared: Dict[str, str] = {}
    for _t in raw_themes:
        if _t["method"]:
            declared[_t["key"]] = _t["method"]
            if _t.get("name"):
                declared.setdefault(_t["name"], _t["method"])
    batches: List[Dict[str, Any]] = []
    notes: List[str] = []
    for th in model.themes:
        raw = str(th.test or "").strip()
        if not raw:
            notes.append(f"专题 {th.key} 没写 `test` —— 出不了 test 类，"
                         f"回归里这一批跑不了")
            continue
        name = sv_ident(raw, "")
        if not name:
            notes.append(f"专题 {th.key} 的 test 名 {raw!r} 折不成合法标识符 —— 跳过")
            continue
        if name != raw:
            notes.append(f"专题 {th.key} 的 test 名 {raw!r} 含非标识符字符，"
                         f"已折成 {name}（回归的 +UVM_TESTNAME 要用折后的）")
        policy = policy_names.get(th.key) or policy_names.get(th.name, "")
        said = declared.get(th.key) or declared.get(th.name, "")
        if said and not policy:
            notes.append(f"专题 {th.key} 声明了 method={said!r}，但它没有对应的约束策略"
                         f" —— 这一批的批次 test 不 set 策略名，sequence 会退回默认组合器")
        batches.append({
            "name": name,
            "theme": th.key,
            "dimensions": ",".join(d.id or d.name or d.key for d in (th.dims or [])),
            "method": th.method or "",
            "policy": policy,
            "priority": th.priority or "",
            "checks": ",".join(th.checks or []),
        })
    if not batches:
        return {"error": "模型里没有任何带 `test` 的专题"} if not model.themes else {
            "count": 0, "batches": [], "batches_yaml": "", "notes": notes}
    return {
        "count": len(batches),
        "batches": batches,
        "batches_yaml": yaml.safe_dump({"batches": batches}, allow_unicode=True,
                                       sort_keys=False),
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════
# 覆盖率 / 覆盖率计划
# ═══════════════════════════════════════════════════════════════

def covergroups_from_text(text: str, module_name: str = "dut",
                          extra_signals: List[Dict[str, Any]] = None,
                          tp_bitmap_width: int = 0) -> Dict[str, Any]:
    models, error = _models(text)
    if error:
        return error
    from .runtime.coverage import (
        cov_interface_meta, coverage_model, dut_bins, probe_ports,
        render_covergroup, render_cov_interface, render_probe,
    )

    model = models[0].resolve()
    cm = coverage_model(model, module_name)
    payload = cm.as_dict()
    payload["covergroup_code"] = render_covergroup(cm)
    payload["probe_code"] = render_probe(cm, model.sampling)
    payload["probe_ports"] = [cp.signal for cp in probe_ports(cm)]
    payload["sampling"] = dict(model.sampling)
    payload["cov_interface"] = cov_interface_meta(
        cm, model.sampling, extra_signals=extra_signals,
        tp_bitmap_width=tp_bitmap_width) or {}
    payload["cov_interface_code"] = render_cov_interface(
        cm, model.sampling, extra_signals=extra_signals,
        tp_bitmap_width=tp_bitmap_width)
    payload["dut_bins"] = dut_bins(cm)
    if probe_ports(cm) and not payload["probe_code"]:
        payload["notes"].append(
            "模型里有 `sample: dut` 的字段，但没有 `sampling.dut_module` —— "
            "生成不出 bind 探针（不知道挂到哪个模块上）。")
    return payload


def run_covergroups(project: VPlanProject, module_name: str = "dut",
                    extra_signals: List[Dict[str, Any]] = None,
                    tp_bitmap_width: int = 0) -> Dict[str, Any]:
    return covergroups_from_text(model_text(project), module_name,
                                 extra_signals=extra_signals,
                                 tp_bitmap_width=tp_bitmap_width)


def case_rows_from_text(text: str, module_name: str = "dut",
                        max_cases: Optional[int] = None) -> Dict[str, Any]:
    from .runtime.registry_bridge import case_rows

    return case_rows(text, module_name, max_cases=max_cases)


def coverage_plan_from_text(text: str,
                            module_name: str = "dut") -> Dict[str, Any]:
    models, error = _models(text)
    if error:
        return error
    from .runtime.coverage import coverage_model, coverage_plan

    model = models[0].resolve()
    cm = coverage_model(model, module_name)
    plan = coverage_plan(model, cm, module_name)
    return {"plan": plan,
            "plan_yaml": yaml.safe_dump(plan, allow_unicode=True, sort_keys=False),
            **plan["summary"]}


def run_coverage_plan(project: VPlanProject,
                      module_name: str = "dut") -> Dict[str, Any]:
    return coverage_plan_from_text(model_text(project), module_name)


# ═══════════════════════════════════════════════════════════════
# 约束 / 关联报告
# ═══════════════════════════════════════════════════════════════

def run_constraints(project: VPlanProject, ports: Optional[List[Any]] = None,
                    agent_fields: Optional[Dict[str, List[str]]] = None
                    ) -> Dict[str, Any]:
    from .runtime.associate import build_constraint

    return build_constraint(model_text(project), ports=ports,
                            agent_fields=agent_fields)


def coverage_model_text(project: VPlanProject,
                        module_name: str = "dut") -> str:
    """覆盖率模型的 JSON 文本（`associate` 吃文本）。"""
    import json

    models, error = _models(model_text(project))
    if error:
        return "{}"
    from .runtime.coverage import coverage_model, coverage_model_to_dict

    model = models[0].resolve()
    return json.dumps(coverage_model_to_dict(coverage_model(model, module_name)),
                      ensure_ascii=False)


def run_association(case_text: str, coverage_text: str,
                    constraint_text: str = "") -> Dict[str, Any]:
    """三份模型文本 → 关联表（调用方仍从 run 产物拼文本）。"""
    from .runtime.associate import associate

    return associate(case_text, coverage_text, constraint_text)


__all__ = [
    "case_rows_from_text", "coverage_model_text", "coverage_plan_from_text",
    "covergroups_from_text",
    "load_exec_assets", "load_project_from", "model_text",
    "project_for", "run_association", "run_constraints", "run_coverage_plan",
    "run_covergroups", "run_testpoints", "run_uvm_batches", "run_uvm_tests",
    "testpoints_from_text",
]
