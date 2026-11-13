"""dplan（设计/模型契约）↔ VPlan（验证计划契约）的对齐映射。

两套契约**不是同一份东西**：

    dplan  : design_name / interfaces / registers / features / model_contract
             —— 决定 RTL 与参考模型怎么实现
    VPlan  : requirements / features / contracts / testpoints / cases
             —— 决定要验证什么、覆盖率与签核依据

本模块只做**对齐**（谁覆盖谁），不做相等判断，也不拿一边去覆盖另一边。
输出 `contract/dplan_map.json`：

    features[]            dplan feature → VPlan feature / requirement / contract
    coverage.dplan_unmapped        dplan 里有、VPlan 里找不到对应的 feature
    coverage.vplan_unmapped        VPlan 需求里没有任何 dplan feature 支撑的
    coverage.mapped_contracts      被 dplan feature 覆盖到的 VPlan 契约数

对齐先走确定性 token 匹配（可复现）；匹配不到就**如实留空**，不编。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set

from src.ir_plane.vplan.source import VPlanProject

SCHEMA = "dplan_map_v1"
_THRESHOLD = 0.35
_STOP = {"and", "or", "the", "for", "with", "basic", "test", "block", "mode",
         "of", "to", "in", "on", "is", "a", "an"}


def _tokens(text: Any) -> Set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", str(text or ""))
    return {w.lower() for w in words if w.lower() not in _STOP}


def _score(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def _text_of(row: Dict[str, Any], keys: Iterable[str]) -> str:
    return " ".join(str(row.get(k) or "") for k in keys if row.get(k))


def _best_feature(tokens: Set[str],
                  project: VPlanProject) -> tuple[str, float]:
    best, best_score = "", 0.0
    for feat in project.features:
        score = _score(tokens, _tokens(_text_of(
            feat, ("feature_id", "feature_l1", "feature_l2", "feature_l3",
                   "description"))))
        if score > best_score:
            best, best_score = str(feat.get("feature_id") or ""), score
    return best, best_score


def _matching_contracts(tokens: Set[str],
                        project: VPlanProject) -> List[str]:
    out: List[str] = []
    for cid, row in project.contracts.items():
        score = _score(tokens, _tokens(_text_of(
            row, ("contract_id", "class", "object", "description",
                  "content", "check_method"))))
        if score >= _THRESHOLD:
            out.append(cid)
    return sorted(set(out))


def _feature(req: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(req.get("name") or req.get("feature") or ""),
        "description": str(req.get("description") or ""),
        "priority": str(req.get("priority") or ""),
    }


def _req_by_feature(project: VPlanProject) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for req in project.requirements:
        for fid in str(req.get("feature_ids") or "").split("|"):
            if fid.strip():
                out.setdefault(fid.strip(), []).append(
                    str(req.get("req_id") or ""))
    return out


def _map_feature(feat: Dict[str, Any], project: VPlanProject,
                 req_by_feature: Dict[str, List[str]]) -> Dict[str, Any]:
    tokens = _tokens(feat["name"] + " " + feat["description"])
    vplan_feature, score = _best_feature(tokens, project)
    mapped = bool(vplan_feature) and score >= _THRESHOLD
    return {
        **feat,
        "vplan_feature_id": vplan_feature if mapped else "",
        "vplan_requirement_ids": sorted(set(
            req_by_feature.get(vplan_feature, []))) if mapped else [],
        "vplan_contract_ids": _matching_contracts(tokens, project),
        "score": round(score, 3),
        "mapped": mapped,
    }


def _map_features(dplan_features: List[Dict[str, Any]],
                  project: VPlanProject) -> tuple[List[Dict[str, Any]],
                                                  Set[str], Set[str]]:
    req_by_feature = _req_by_feature(project)
    rows: List[Dict[str, Any]] = []
    mapped_features: Set[str] = set()
    mapped_contracts: Set[str] = set()
    for feat in dplan_features:
        row = _map_feature(feat, project, req_by_feature)
        rows.append(row)
        if row["vplan_feature_id"]:
            mapped_features.add(row["vplan_feature_id"])
        mapped_contracts.update(row["vplan_contract_ids"])
    return rows, mapped_features, mapped_contracts


def _map_behavior(beh: Dict[str, Any], project: VPlanProject) -> Dict[str, Any]:
    tokens = _tokens(_text_of(beh, ("name", "when", "expect")))
    best_tp, best_score = "", 0.0
    for tp in project.testpoints:
        score = _score(tokens, _tokens(_text_of(
            tp, ("test_point", "stimulus", "expected"))))
        if score > best_score:
            best_tp, best_score = str(tp.get("tp_id") or ""), score
    return {
        "name": str(beh.get("name") or ""),
        "vplan_tp_id": best_tp if best_score >= _THRESHOLD else "",
        "vplan_contract_ids": _matching_contracts(tokens, project),
        "score": round(best_score, 3),
        "mapped": best_score >= _THRESHOLD,
    }


def _map_behaviors(contract: Dict[str, Any],
                   project: VPlanProject) -> List[Dict[str, Any]]:
    return [_map_behavior(beh, project)
            for beh in ((contract.get("model_contract") or {})
                        .get("behaviors") or []) if isinstance(beh, dict)]


def _coverage(rows: List[Dict[str, Any]], behaviors: List[Dict[str, Any]],
              project: VPlanProject, mapped_features: Set[str],
              mapped_contracts: Set[str]) -> Dict[str, Any]:
    covered = {r for row in rows for r in row["vplan_requirement_ids"]}
    return {
        "dplan_mapped": sum(1 for r in rows if r["mapped"]),
        "dplan_unmapped": [r["name"] for r in rows if not r["mapped"]],
        "vplan_feature_mapped": sorted(mapped_features),
        "vplan_unmapped_requirements": [
            str(r.get("req_id") or "") for r in project.requirements
            if str(r.get("req_id") or "") not in covered],
        "behaviors_mapped": sum(1 for b in behaviors if b["mapped"]),
        "behaviors_unmapped": [b["name"] for b in behaviors
                               if not b["mapped"]],
        "mapped_contracts": sorted(mapped_contracts),
        "contract_count": len(project.contracts),
    }


def build_dplan_map(contract: Dict[str, Any],
                    project: VPlanProject) -> Dict[str, Any]:
    """dplan 契约 + VPlan 项目 → 对齐映射（确定性，可重放）。"""
    dplan_features = [_feature(f) for f in (contract.get("features") or [])
                      if isinstance(f, dict)]
    rows, mapped_features, mapped_contracts = _map_features(
        dplan_features, project)
    module_rows = _map_features(
        [{"name": str(m.get("name") or ""),
          "description": str(m.get("function") or m.get("description") or ""),
          "priority": str(m.get("level") or "")}
         for m in (contract.get("modules") or []) if isinstance(m, dict)],
        project)[0]
    behaviors = _map_behaviors(contract, project)
    model = contract.get("model_contract") or {}
    return {
        "schema": SCHEMA,
        "module": str(contract.get("design_name") or project.module),
        "dplan": {
            "interfaces": len(contract.get("interfaces") or []),
            "features": len(dplan_features),
            "model_ports": len(model.get("ports") or []),
            "modules": len(module_rows),
            "model_behaviors": len(model.get("behaviors") or []),
        },
        "features": rows,
        "modules": module_rows,
        "behaviors": behaviors,
        "coverage": _coverage(rows, behaviors, project, mapped_features,
                              mapped_contracts),
    }



# ── CSV / MD / HTML 视图（dplan 以人读文档为主，JSON 只作机器 sidecar）──

_MODULE_FIELDS = ("name", "level", "parent", "method", "function",
                  "combinational", "sequential", "interfaces")
_IFACE_FIELDS = ("module", "name", "direction", "data_width", "protocol",
                 "description")
_MAP_FIELDS = ("kind", "name", "vplan_feature", "vplan_requirements",
               "vplan_contracts", "vplan_tp", "score", "mapped")


def _write_csv(path, fields, rows) -> None:
    import csv

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fields),
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _modules_table(contract):
    rows = []
    for m in contract.get("modules") or []:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        rows.append({
            "name": m.get("name", ""),
            "level": m.get("level", ""),
            "parent": m.get("parent", ""),
            "method": m.get("method", ""),
            "function": m.get("function") or m.get("description", ""),
            "combinational": " | ".join(str(x) for x in
                                        (m.get("combinational") or [])),
            "sequential": " | ".join(str(x) for x in
                                     (m.get("sequential") or [])),
            "interfaces": " | ".join(
                str(i.get("name")) for i in (m.get("interfaces") or [])
                if isinstance(i, dict)),
        })
    return rows


def _interfaces_table(contract):
    rows = []
    for itf in contract.get("interfaces") or []:
        if isinstance(itf, dict) and itf.get("name"):
            rows.append({"module": contract.get("design_name", ""), **itf})
    for m in contract.get("modules") or []:
        if not isinstance(m, dict):
            continue
        for itf in m.get("interfaces") or []:
            if isinstance(itf, dict) and itf.get("name"):
                rows.append({"module": m.get("name", ""), **itf})
    return rows


def _features_table(contract):
    return [dict(f) for f in (contract.get("features") or [])
            if isinstance(f, dict) and f.get("name")]


def _behaviors_table(contract):
    out = []
    for b in ((contract.get("model_contract") or {}).get("behaviors") or []):
        if isinstance(b, dict) and b.get("name"):
            out.append({**b, "checks": " | ".join(
                str(x) for x in (b.get("checks") or []))})
    return out


def _map_table(doc):
    if not doc:
        return []
    rows = []
    for kind in ("features", "modules", "behaviors"):
        for row in doc.get(kind) or []:
            rows.append({
                "kind": kind, "name": row.get("name", ""),
                "vplan_feature": row.get("vplan_feature_id", ""),
                "vplan_requirements": "|".join(
                    row.get("vplan_requirement_ids") or []),
                "vplan_contracts": "|".join(
                    row.get("vplan_contract_ids") or []),
                "vplan_tp": row.get("vplan_tp_id", ""),
                "score": row.get("score", ""),
                "mapped": row.get("mapped", False),
            })
    return rows


def _write_markdown(base, contract, doc) -> None:
    arch = contract.get("architecture") or {}
    lines = [
        f"# dplan — {contract.get('design_name', '')}",
        "",
        "设计/模型契约（**怎么实现**）。VPlan 契约（**验证什么**）在 `../vplan/`；",
        "两者通过 `dplan_map.csv` / `dplan_map.json` 对齐，不是同一份东西。",
        "",
        "## 架构",
        "",
        f"- top: `{arch.get('top') or contract.get('design_name', '')}`",
        f"- method: {arch.get('method') or '-'}",
        f"- stages: {' -> '.join(arch.get('stages') or []) or '-'}",
        "",
        "## 文件",
        "",
        "| 文件 | 内容 |",
        "|---|---|",
        "| `modules.csv` | 模块划分（接口 / 组合逻辑 / 时序逻辑 / 方法） |",
        "| `interfaces.csv` | 顶层与各模块端口 |",
        "| `features.csv` | 设计功能点 |",
        "| `behaviors.csv` | 模型行为契约 |",
        "| `dplan_map.csv` | dplan ↔ VPlan 对齐与覆盖 |",
        "| `dplan_view.html` | 人读视图 |",
        "",
    ]
    if doc:
        cov = doc["coverage"]
        lines += [
            "## 与 VPlan 对齐",
            "",
            f"- dplan feature 已对齐 {cov['dplan_mapped']}/{doc['dplan']['features']}",
            f"- dplan module 已对齐 {cov.get('modules_mapped', 0)}/{doc['dplan'].get('modules', 0)}",
            f"- VPlan 需求未覆盖 {len(cov['vplan_unmapped_requirements'])} 条",
            f"- VPlan 契约命中 {len(cov['mapped_contracts'])}/{cov['contract_count']}",
            "",
        ]
    (base / "architecture.md").write_text("\n".join(lines), encoding="utf-8")


def _html_rows(rows, fields) -> str:
    import html

    head = "".join(f"<th>{html.escape(f)}</th>" for f in fields)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(r.get(f, '')))}</td>"
                        for f in fields) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _write_html(base, contract, doc) -> None:
    import html

    title = html.escape(f"dplan — {contract.get('design_name', '')}")
    parts = [
        "<!doctype html><meta charset='utf-8'>",
        f"<title>{title}</title>",
        "<style>body{font-family:sans-serif;margin:24px}"
        "table{border-collapse:collapse;margin:12px 0 24px}"
        "th,td{border:1px solid #ccc;padding:4px 8px;font-size:13px}"
        "th{background:#f3f3f3}</style>",
        f"<h1>{title}</h1>",
        "<h2>模块</h2>", _html_rows(_modules_table(contract), _MODULE_FIELDS),
        "<h2>接口</h2>", _html_rows(_interfaces_table(contract),
                                    _IFACE_FIELDS),
        "<h2>功能</h2>", _html_rows(_features_table(contract),
                                    ("name", "priority", "description")),
        "<h2>模型行为</h2>", _html_rows(_behaviors_table(contract),
                                        ("name", "when", "expect", "checks")),
        "<h2>dplan ↔ VPlan</h2>", _html_rows(
            _map_table(doc), _MAP_FIELDS),
    ]
    (base / "dplan_view.html").write_text("".join(parts), encoding="utf-8")


def _write_tables(base, contract, doc) -> None:
    _write_csv(base / "modules.csv", _MODULE_FIELDS, _modules_table(contract))
    _write_csv(base / "interfaces.csv", _IFACE_FIELDS,
               _interfaces_table(contract))
    _write_csv(base / "features.csv",
               ("name", "priority", "description"), _features_table(contract))
    _write_csv(base / "behaviors.csv",
               ("name", "when", "expect", "checks"),
               _behaviors_table(contract))
    _write_csv(base / "dplan_map.csv", _MAP_FIELDS, _map_table(doc))
    _write_markdown(base, contract, doc)
    _write_html(base, contract, doc)


def write_dplan_contracts(run_dir: str | Path,
                          contract: Dict[str, Any],
                          project: VPlanProject | None = None
                          ) -> Dict[str, Any]:
    """把 dplan 契约落进 `<run>/inputs/dplan/`（run 的输入，不是生成物）。

    文件：
        design_contract.json   design_name / overview / interfaces / registers / features
        model_contract.json    module / ports / state / behaviors / scoreboard
        modules.csv / interfaces.csv / features.csv / behaviors.csv
        architecture.md / dplan_view.html / dplan_map.csv
        dplan_map.json         dplan ↔ VPlan 对齐（有 VPlan 项目时）
    同时在 `contract/dplan_map.json` 留一份 sidecar 给 gate/审计读。
    """
    from pathlib import Path

    from src.runtime_plane.core.runtime.atomic import atomic_write_json, atomic_write_text

    root = Path(run_dir)
    base = root / "inputs" / "dplan"
    base.mkdir(parents=True, exist_ok=True)
    design = {k: contract.get(k) for k in
              ("design_name", "overview", "interfaces", "registers", "features",
               "architecture", "modules")
              if contract.get(k) is not None}
    model = contract.get("model_contract") or {}
    atomic_write_json(base / "design_contract.json", design)
    atomic_write_json(base / "model_contract.json", model)
    if contract.get("modules"):
        atomic_write_json(base / "modules.json", contract.get("modules"))
    doc = build_dplan_map(contract, project) if project is not None else None
    _write_tables(base, contract, doc)
    atomic_write_text(
        base / "README.md",
        "# inputs/dplan — 设计/模型契约（dplan）：CSV/HTML/MD 为主；"
        "JSON 只作机器 sidecar。VPlan 在 ../vplan/，通过 dplan_map 对齐。")
    result = {
        "base": str(base),
        "design": str(base / "design_contract.json"),
        "model": str(base / "model_contract.json"),
        "modules": str(base / "modules.json") if contract.get("modules") else "",
    }
    if project is not None and doc is not None:
        atomic_write_json(base / "dplan_map.json", doc)
        sidecar = root / "contract" / "dplan_map.json"
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(sidecar, doc)
        result["map"] = str(base / "dplan_map.json")
        result["sidecar"] = str(sidecar)
    return result

