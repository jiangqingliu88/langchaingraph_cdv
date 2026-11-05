"""签核视图 —— 门禁 + 六层证据链 + 总判定（只读一次运行目录）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.app.services.flow.evidence_summary import (
    recipe_summary as _recipe_summary,
    stimulus_summary as _stimulus_summary,
)
from src.layers.l2_orchestration.flow_shared import _num, _read_json, _read_jsonl, _resolve_run_dir

GATE_TITLES = (
    ("rtl_present", "① RTL 存在"),
    ("rtl_real", "② RTL 非占位"),
    ("regression_passed", "③ 回归全过"),
    ("coverage_collected", "④ 覆盖率已收集"),
    ("model_real", "⑤ 参考模型非占位"),
)


LAYER_TITLES = {
    "requirement_layer": "需求层",
    "design_layer": "设计层",
    "verification_layer": "验证层",
    "execution_layer": "执行层",
    "functional_coverage_layer": "功能覆盖层",
    "signoff_layer": "签核层",
}


CHECK_TITLES = {
    "req_spec_completeness": "规格完整",
    "req_test_mapping": "需求→测试映射",
    "rtl_signal_mapping": "RTL 信号/接口映射",
    "register_mapping": "寄存器映射",
    "case_coverage_P0": "P0 用例覆盖",
    "case_coverage_P1": "P1 用例覆盖",
    "case_coverage_P2": "P2 用例覆盖",
    "case_coverage_P3": "P3 用例覆盖",
}


def run_signoff(run_dir: str = "") -> Dict[str, Any]:
    """一次运行目录 → 签核判定模型。

    返回：
        {"run_dir", "verdict", "signoff_status", "pass_rate", "coverage",
         "gates": [{id,title,passed,detail}], "chain": {...}, "summary"}
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    report = _read_json(root / "report.json")
    chain_raw = _read_json(root / "docs" / "evidence_chain.json")

    gates = _build_gates(report)
    chain = _build_chain(chain_raw)

    return {
        "run_dir": str(root),
        "verdict": str((report or {}).get("verdict", "") or ""),
        "signoff_status": str((report or {}).get("signoff_status", "") or ""),
        "pass_rate": str((report or {}).get("pass_rate", "") or ""),
        "coverage": _num((report or {}).get("coverage")),
        "gates": gates,
        "chain": chain,
        # 测试点维度的签核口径（audit 写进 report.json）：
        # `{total, drivable, drivable_hit, drivable_pct, observe_only,
        #   observed, missed, unmapped}`。空 = 这一轮没有 TP IR，不是全过。
        "testpoints": (report or {}).get("testpoints") or {},
        # 软缺口（约束部分生效 / 测试点未命中等）—— 签核时要写清保留了什么。
        "caveats": list((report or {}).get("caveats") or []),
        # 证据包 v2（唯一权威）+ 审批/种子/约束/Freeze 的界面视图。
        "evidence": _evidence_v2(root),
        # Case 证据（三集合）：签核产出的第 4 块 —— 用例证明了哪些组/SVA/SB。
        "case_view": _case_view(root),
        # Verification OS：契约 / 账本 / 两级影子对账（只读）
        "os": _os_status(root),
        "summary": _summary(report, gates, chain),
    }


#: 签核包里的 Case 证据产物（与 `signoff_package.SECTION_FILES["case_view"]` 同源）
_CASE_ARTIFACTS = (
    ("coverage/case_ir.json", "用例契约（CCAT/CASE + 三集合）"),
    ("coverage/case_group_map.json", "Case ↔ group ↔ CELL 索引"),
    ("coverage/case_checker_map.json", "Case ↔ SVA/SB 索引"),
    ("coverage/case_tp.json", "用例 ↔ 测试点证据"),
    ("coverage/cell_matrix.json", "CELL 签核读数（四色）"),
    ("coverage/evd.json", "执行证据（checker 级去重）"),
    ("coverage/gates.json", "Case 门禁（blocker/warning/info）"),
    ("coverage/case_view.json", "Case 证据视图（机读）"),
    ("coverage/case_view.md", "Case 证据视图（评审材料）"),
    ("coverage/case_view.html", "Case 证据视图（网页）"),
    ("coverage/evidence_manifest.json", "派生链（每步 sha + 耗时）"),
)


def _os_status(root: Path) -> Dict[str, Any]:
    """Verification OS 视图；老 run 没有契约/账本时如实返回 `available: false`。"""
    try:
        from src.layers.l3_decision.contract import status_summary

        data = status_summary(root)
    except Exception as exc:                        # noqa: BLE001 页面不该挂
        return {"available": False, "note": str(exc)}
    return {"available": bool((data.get("contract") or {}).get("ok")),
            **data}


def _case_view(root: Path) -> Dict[str, Any]:
    """Case 证据在**签核产出**里的状态：有没有生成、进没进证据包。"""
    gates = _read_json(root / "coverage" / "gates.json") or {}
    cells = _read_json(root / "coverage" / "cell_matrix.json") or {}
    case_ir = _read_json(root / "coverage" / "case_ir.json") or {}
    evd = _read_json(root / "coverage" / "evd.json") or {}
    package_manifest = _read_json(root / "signoff_evidence" / "manifest.json") or {}
    packaged = {str(f.get("source") or "")
                for f in (package_manifest.get("files") or [])
                if isinstance(f, dict)}
    rows = [{"path": rel, "label": label,
             "exists": (root / rel).is_file(),
             "in_package": rel in packaged}
            for rel, label in _CASE_ARTIFACTS]
    case_cov = root / "coverage" / "case_cov"
    return {
        "available": bool(gates or cells or case_ir),
        "gate": {"verdict": str(gates.get("verdict") or ""),
                 "counts": gates.get("counts") or {}},
        "cells": cells.get("counts") or {},
        "cases": case_ir.get("counts") or {},
        "evd": evd.get("counts") or {},
        "case_cov_files": (len(list(case_cov.rglob("*.json")))
                           if case_cov.is_dir() else 0),
        "artifacts": rows,
        "package_available": (root / "signoff_evidence" / "manifest.json").is_file(),
    }


def _build_gates(report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(report, dict):
        return {"available": False, "rows": [],
                "note": "没有 report.json —— 这次运行还没跑到 audit（签核审查）"}
    raw = report.get("gates") or {}
    if not isinstance(raw, dict):
        raw = {}
    rows: List[Dict[str, Any]] = []
    for gate_id, title in GATE_TITLES:
        if gate_id not in raw:
            continue                      # 老报告可能没有某道门 —— 不凭空补
        rows.append({"id": gate_id, "title": title,
                     "passed": bool(raw.get(gate_id)),
                     "detail": _gate_detail(gate_id, report, raw)})
    return {"available": True, "rows": rows, "note": ""}


def _gate_detail(gate_id: str, report: Dict[str, Any], raw: Dict[str, Any]) -> str:
    """给每道门配一句"为什么"——门禁不给理由的话，人只会看到一片红。"""
    if gate_id == "rtl_present":
        files = raw.get("rtl_files") or []
        return f"{len(files)} 个 .sv" + (f"：{'、'.join(files[:4])}" if files else "")
    if gate_id == "rtl_real":
        return "RTL 是真实互连" if raw.get("rtl_real") else "顶层是占位骨架（LLM 连线失败回退）"
    if gate_id == "regression_passed":
        return f"通过 {report.get('pass_rate', '?')}"
    if gate_id == "coverage_collected":
        cov = _num(report.get("coverage"))
        return f"覆盖率 {cov:g}%" if cov is not None else "覆盖率缺失"
    if gate_id == "model_real":
        if raw.get("model_real"):
            return "参考模型为真实实现"
        return str(raw.get("model_placeholder_reason", "") or "参考模型是模板占位")
    return ""


def _build_chain(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("layers"), dict):
        return {"available": False, "layers": [], "signoff_ready": False,
                "checks_passed": 0, "checks_total": 0,
                "note": "没有 docs/evidence_chain.json —— 这次运行还没跑到 finalize"}
    layers: List[Dict[str, Any]] = []
    for layer_id, body in (raw.get("layers") or {}).items():
        if not isinstance(body, dict):
            continue
        layers.append({
            "id": layer_id,
            "title": LAYER_TITLES.get(layer_id, layer_id),
            "description": str(body.get("description", "") or ""),
            "passed": int(body.get("passed", 0) or 0),
            "total": int(body.get("total", 0) or 0),
            "checks": _checks_of(body),
        })
    return {
        "available": True,
        "layers": layers,
        "signoff_ready": bool(raw.get("signoff_ready")),
        "overall_status": str(raw.get("overall_status", "") or ""),
        "checks_passed": int(raw.get("checks_passed", 0) or 0),
        "checks_total": int(raw.get("checks_total", 0) or 0),
        "note": "",
    }


def _checks_of(layer: Dict[str, Any]) -> List[Dict[str, Any]]:
    checks = layer.get("checks") or {}
    if not isinstance(checks, dict):
        return []
    return [{"id": name, "title": CHECK_TITLES.get(name, name),
             "passed": bool(value)} for name, value in checks.items()]


def _summary(report: Optional[Dict[str, Any]], gates: Dict[str, Any],
             chain: Dict[str, Any]) -> str:
    """一句话总判定 —— 界面顶部那行大字。

    口径：**门禁与证据链都通过才算真正可签核**。任一缺失都如实说出来，
    不因为"文件还没生成"就报绿。
    """
    if not gates.get("available") and not chain.get("available"):
        return "这次运行还没有签核信息（既没有 report.json 也没有证据链）。"

    bits: List[str] = []
    if gates.get("available"):
        rows = gates["rows"]
        ok = sum(1 for r in rows if r["passed"])
        verdict = str((report or {}).get("verdict", "") or "")
        bits.append(f"门禁 {ok}/{len(rows)} 通过" + (f"（{verdict}）" if verdict else ""))
    else:
        bits.append("门禁未知（未跑到 audit）")

    if chain.get("available"):
        state = "证据链闭合" if chain["signoff_ready"] else "证据链未闭合"
        bits.append(f"{state} {chain['checks_passed']}/{chain['checks_total']}")
    else:
        bits.append("证据链未知（未跑到 finalize）")

    ready = (gates.get("available") and chain.get("available")
             and all(r["passed"] for r in gates["rows"]) and chain["signoff_ready"])
    return ("可以签核：" if ready else "暂不可签核：") + "；".join(bits) + "。"


def _evidence_v2(root: Path) -> Dict[str, Any]:
    """签核证据包 v2 → 界面可读的一节。

    读不到就 `available: false`（老 run / 还没跑到 audit），**不编**。
    v1 `signoff_evidence.json` 只作为兼容视图，界面明确标 deprecated。
    """
    manifest = _read_json(root / "signoff_evidence" / "manifest.json")
    v1 = _read_json(root / "signoff_evidence.json")
    seed = _read_json(root / "coverage" / "seed_diversity.json")
    constraint = _read_json(root / "coverage" / "constraint_status.json")
    recipe = _read_json(root / "signoff_evidence" / "replay" / "recipe.json")
    stimulus = _read_json(root / "coverage" / "stimulus_plan.json")
    approvals = _read_jsonl(root / "approvals.jsonl")
    freeze = root / "freeze.json"

    verdict = (manifest or {}).get("verdict") or {}
    raw = [c for c in (verdict.get("raw_caveats") or []) if isinstance(c, dict)]
    return {
        "available": isinstance(manifest, dict),
        "schema": (manifest or {}).get("schema", ""),
        "package_hash": (manifest or {}).get("package_hash", ""),
        "manifest_hash": (manifest or {}).get("manifest_hash", ""),
        "file_count": len((manifest or {}).get("files") or []),
        "hard_ok": verdict.get("hard_ok"),
        "verdict": verdict.get("verdict", ""),
        "raw_caveat_codes": [c.get("code") for c in raw],
        "accepted_codes": list(verdict.get("accepted_codes") or []),
        "effective_codes": list(verdict.get("effective_codes") or []),
        "coverage": (manifest or {}).get("coverage") or {},
        "tp_matrix": (manifest or {}).get("tp_matrix") or {},
        "seed_diversity": (manifest or {}).get("seed_diversity") or seed or {},
        "sim_reward": (manifest or {}).get("sim_reward")
                      or _read_json(root / "coverage" / "sim_reward.json") or {},
        "knowledge_graph": (manifest or {}).get("knowledge_graph")
                          or _read_json(root / "coverage" / "knowledge_graph.json") or {},
        "recipe": _recipe_summary(recipe),
        "stimulus_plan": _stimulus_summary(stimulus),
        "reference_models": (manifest or {}).get("reference_models") or {},
        "lineage": (manifest or {}).get("lineage") or {},
        "regression_config": (manifest or {}).get("regression_config") or {},
        "constraint_status": constraint or {},
        "approval_count": len(approvals),
        "latest_approval": approvals[-1] if approvals else {},
        "freeze": {"present": freeze.is_file(), "path": str(freeze)},
        "replay_cmd": f'python "{root / "signoff_evidence" / "replay" / "replay.py"}"',
        "v1_deprecated": bool((v1 or {}).get("deprecated")),
    }
