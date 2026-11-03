"""Case 关联视图 —— **四层证据落到"用例 / 功能契约 / 路径矩阵 / 缺口"四个人类视图**。

`tp_cov_evidence.json` 是按 TP 的机器证据；这里把它滚动成人能直接评审的四张表：

    视图1 用例 × 证据层     哪个用例提供了哪层证据
    视图2 功能契约 × 证据层 哪个 Feat 的证据链还缺
    视图3 功能组 × 路径     哪个功能在哪条路径上证据不足
    视图4 缺口与豁免        缺口怎么补、谁负责、什么状态

数据源全部是已落盘产物（`case_cov` / `tp_cov_evidence` / `coverage_plan` /
`waves/manifest`），不重跑仿真、不重跑 vcover。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.tools.checking.coverage_tools.tp_evidence import (
    LAYERS, build_tp_evidence, _case_records)

SCHEMA = "case_associate_view_v1"

#: 层名（与 tp_evidence 同一份顺序）
_LAYER_LABEL = {key: name for key, name, *_ in LAYERS}

#: 缺口动作建议（按层）—— 只给建议，不自动执行。
_ACTION = {
    "functional": "补定向激励/覆盖仓，或修 monitor 采样条件",
    "timing": "补 SVA / DUT_CHK 规则，或修时序窗口",
    "data": "补 scoreboard 比对项",
    "path": "补 PATH 序列/种子，或接 PATH 后端",
}


def _status(*statuses: str) -> str:
    """多值 → 一个展示态：红 > 黄 > 绿 > na。"""
    values = [s for s in statuses if s]
    if any(s in ("MISSING", "UNMAPPED", "NOT_VERIFIED", "red") for s in values):
        return "red"
    if any(s in ("PARTIAL", "PENDING_BACKEND", "yellow") for s in values):
        return "yellow"
    if values and all(s in ("PROVEN", "VERIFIED", "green") for s in values):
        return "green"
    return "na"


def _case_coverage(entries: List[Dict[str, Any]], rec: Dict[str, Any]) -> Dict[str, str]:
    if rec.get("error"):
        return {"status": "red", "detail": f"覆盖率库错误：{rec['error']}"}
    if not entries:
        return {"status": "na", "detail": "没有关联 TP"}
    pcts = [e.get("pct") for e in entries if e.get("pct") is not None]
    ok = sum(1 for p in pcts if p >= 100)
    detail = "、".join(f"{e.get('tp_id')}:{e.get('pct')}%" for e in entries[:4])
    if pcts and ok == len(pcts):
        return {"status": "green", "detail": detail or "全部仓命中"}
    if any((p or 0) > 0 for p in pcts):
        return {"status": "yellow", "detail": detail}
    return {"status": "red", "detail": detail or "覆盖仓全部未命中"}


def _case_sva(rec: Dict[str, Any]) -> Dict[str, str]:
    a = rec.get("assertions") or {}
    rules, fired = int(a.get("rules") or 0), int(a.get("fired") or 0)
    timing_ok = rec.get("timing_ok")
    if fired or int(rec.get("uvm_errors") or 0) or timing_ok is False:
        return {"status": "red", "detail": f"规则触发/fired={fired}，"
                                          f"timing_ok={timing_ok}"}
    if rules or timing_ok is True:
        return {"status": "green", "detail": f"{rules} 条规则，0 触发"
                                            f"（timing_ok={timing_ok}）"}
    return {"status": "yellow", "detail": "未声明/未执行 SVA 规则"}


def _case_scb(rec: Dict[str, Any]) -> Dict[str, str]:
    scb = rec.get("scb") or {}
    matched, mismatched = scb.get("matched"), scb.get("mismatched")
    if matched is None:
        return {"status": "yellow", "detail": "没有 SCB 比对结论"}
    if int(mismatched or 0) > 0:
        return {"status": "red", "detail": f"matched={matched} mismatched={mismatched}"}
    if int(matched) > 0:
        return {"status": "green", "detail": f"matched={matched} mismatched=0"}
    return {"status": "yellow", "detail": "SCB 有结论但 0 条比对"}


def _path_of(tp_evs: List[Dict[str, Any]]) -> Dict[str, str]:
    layers = [t["evidence_layers"]["path"] for t in tp_evs
              if t["evidence_layers"]["path"]["status"] != "NOT_APPLICABLE"]
    if not layers:
        return {"status": "na", "detail": "未声明 PATH 组"}
    detail = "、".join(
        f"{l['source'].get('path_group')}.{l['source'].get('path_bin')}"
        f"({l['status']})" for l in layers[:3])
    return {"status": _status(*[l["status"] for l in layers]), "detail": detail}


def _conclusion(statuses: Dict[str, str]) -> str:
    if all(s == "green" for s in statuses.values()):
        return "已验证"
    reds = [k for k, s in statuses.items() if s == "red"]
    yellows = [k for k, s in statuses.items() if s == "yellow"]
    if reds:
        return "证据链不完整（" + "、".join(reds) + "）"
    if yellows:
        return "待补（" + "、".join(yellows) + "）"
    return "不适用"


def _case_rows(tp_ev: Dict[str, Any],
               records: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {t["tp_id"]: t for t in tp_ev.get("tps") or []}
    rows = []
    for task, rec in sorted(records.items()):
        entries = [e for e in (rec.get("tp") or []) if isinstance(e, dict)]
        tps = [by_id[e["tp_id"]] for e in entries if e.get("tp_id") in by_id]
        feats = sorted({t.get("requirement") for t in tps if t.get("requirement")})
        coverage = _case_coverage(entries, rec)
        sva = _case_sva(rec)
        scoreboard = _case_scb(rec)
        path = _path_of(tps)
        rows.append({
            "name": str(rec.get("test") or task),
            "task": task,
            "feats": feats,
            "desc": str(rec.get("test_name") or task),
            "coverage": coverage, "sva": sva,
            "scoreboard": scoreboard, "path": path,
            "conclusion": _conclusion({"功能覆盖": coverage["status"],
                                       "SVA": sva["status"],
                                       "Scoreboard": scoreboard["status"],
                                       "PATH": path["status"]}),
        })
    return rows


def _feature_status(tps: List[Dict[str, Any]], key: str) -> str:
    statuses = [t["evidence_layers"][key]["status"] for t in tps]
    if not statuses:
        return "na"
    return _status(*statuses)


def _feature_rows(tp_ev: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for tp in tp_ev.get("tps") or []:
        key = str(tp.get("requirement") or f"dim:{tp.get('dimension_name') or tp.get('dimension')}")
        groups.setdefault(key, []).append(tp)
    rows = []
    for key, tps in sorted(groups.items()):
        layers = {k: _feature_status(tps, k) for k, *_rest in LAYERS}
        label = next((t.get("dimension_name") for t in tps if t.get("dimension_name")),
                     key)
        gap = [name for (k, name, *_r) in LAYERS
               if layers[k] in ("red", "yellow")]
        rows.append({"id": key, "desc": label or key, **layers,
                     "status": ("可签核" if all(v == "green" for v in layers.values())
                                else ("证据链不完整" if any(v == "red" for v in layers.values())
                                      else f"待补（{'、'.join(gap)}）"))})
    return rows


def _attribute_groups(tp_ev: Dict[str, Any]) -> tuple:
    """属性 TP → `(groups, {group: [tp]})`（PATH/行为 TP 不进功能组列）。"""
    by_group: Dict[str, List[Dict[str, Any]]] = {}
    for tp in tp_ev.get("tps") or []:
        if tp.get("domain") != "attribute":
            continue
        name = str(tp.get("dimension_name") or tp.get("dimension") or "")
        if name:
            by_group.setdefault(name, []).append(tp)
    return sorted(by_group), by_group


def _group_cells(groups: List[str], by_group: Dict[str, List[Dict[str, Any]]],
                 declared: set) -> Dict[str, str]:
    cells = {}
    for name in groups:
        if declared and name not in declared:
            cells[name] = "na"
            continue
        tps = by_group.get(name) or []
        cells[name] = ("green" if any(t.get("signed_off") for t in tps)
                       else ("yellow" if tps else "na"))
    return cells


def _matrix(tp_ev: Dict[str, Any]) -> Dict[str, Any]:
    """功能组 × 生命周期路径：组证据的**汇总**，不是逐格仿真交叉。"""
    groups, by_group = _attribute_groups(tp_ev)
    paths = tp_ev.get("groups", {}).get("path") or []
    rows = []
    for group in paths:
        cells = _group_cells(groups, by_group, set(group.get("groups") or []))
        for bin_ in group.get("bins") or []:
            rows.append({"path": f"{group.get('id')}.{bin_.get('name')}",
                         "cells": dict(cells)})
    if not rows:
        rows.append({"path": "（未声明 PATH 组）",
                     "cells": _group_cells(groups, by_group, set())})
    return {"groups": groups, "rows": rows}


def _gaps(tp_ev: Dict[str, Any], case_tp: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for tp in tp_ev.get("tps") or []:
        if tp.get("contract_status") in ("VERIFIED", "PENDING_BACKEND"):
            continue
        for key, name, *_rest in LAYERS:
            layer = (tp.get("evidence_layers") or {}).get(key) or {}
            status = layer.get("status")
            if status in ("MISSING", "UNMAPPED", "PARTIAL"):
                out.append({
                    "type": "证据缺失" if status != "PARTIAL" else "证据不完整",
                    "item": f"{tp.get('tp_id')} {name}",
                    "root": layer.get("proves") or status,
                    "action": _ACTION.get(key, "补证据"),
                    "owner": "待分配", "status": "未开始",
                })
    for item in (case_tp.get("signed_off_missing_wave") or [])[:50]:
        out.append({"type": "波形缺失", "item": str(item.get("tp_id")),
                    "root": "已签核但 manifest 里找不到波形",
                    "action": "重跑 wave 业务 / 检查 manifest", "owner": "待分配",
                    "status": "未开始"})
    for item in (case_tp.get("timing_warn") or [])[:50]:
        out.append({"type": "时序超窗", "item": str(item.get("tp_id")),
                    "root": "expect_cycles 超窗（序列型只 WARN）",
                    "action": "补种子 / 核对时序窗口", "owner": "待分配",
                    "status": "进行中"})
    paths = tp_ev.get("groups", {}).get("path") or []
    if any(b.get("status") == "PENDING_BACKEND"
           for g in paths for b in g.get("bins") or []):
        out.append({"type": "未执行", "item": "PATH 组",
                    "root": "PATH 组已建模，执行后端（序列/path_seq）未接",
                    "action": "接 P1b 后端（序列 → UVM + 采样）",
                    "owner": "验证后端", "status": "进行中"})
    # 去重（同类型同项只留第一条）
    seen, uniq = set(), []
    for g in out:
        key = (g["type"], g["item"])
        if key not in seen:
            seen.add(key)
            uniq.append(g)
    return uniq[:200]


def build_case_view(run_dir: str | Path) -> Dict[str, Any]:
    """一次运行 → `case_associate_view_v1`（四张人读视图的数据）。"""
    od = Path(run_dir)
    tp_ev = build_tp_evidence(od)
    records = _case_records(od)
    import json as _json
    case_tp = {}
    try:
        case_tp = _json.loads((od / "coverage" / "case_tp.json").read_text(
            encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        case_tp = {}
    cases = _case_rows(tp_ev, records)
    features = _feature_rows(tp_ev)
    gaps = _gaps(tp_ev, case_tp)
    return {
        "schema": SCHEMA,
        "run": od.name,
        "counts": {"cases": len(cases), "features": len(features),
                   "gaps": len(gaps)},
        "cases": cases,
        "features": features,
        "matrix": _matrix(tp_ev),
        "gaps": gaps,
    }
