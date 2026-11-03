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

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.tools.checking.coverage_tools.status_vocab import (
    NA, conclusion_for, detail_of, display_color, worst)
from src.tools.checking.coverage_tools.tp_evidence import (
    LAYERS, build_tp_evidence, _case_records)

SCHEMA = "case_associate_view_v2"

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
    """多值 → 一个展示态。**映射在 `status_vocab`（唯一实现）**。"""
    return worst(statuses)


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
    # `scb_summary` 是 [SCB_DUT] 汇总；旧记录把它放在 `scb`（dict）里
    scb = rec.get("scb_summary") or (
        rec.get("scb") if isinstance(rec.get("scb"), dict) else {}) or {}
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
    """四层展示色 → 结论。**映射在 `status_vocab.conclusion_for`**。"""
    return conclusion_for(statuses)


def _canonical_layers(rec: Dict[str, Any]) -> Optional[Dict[str, Dict[str, str]]]:
    """有契约的记录 → 直接用 `case_cov` 里 **derive 判定过** 的状态。

    返回 `None` 表示这条记录没有契约身份（批次级 test / 旧目录）—— 调用方
    才走 legacy 展示路径。**视图不再从原始日志重算绿黄红**：那是第二套
    判定，改一处就会和签核结论分叉。
    """
    groups = [g for g in rec.get("groups") or [] if isinstance(g, dict)]
    if not groups:
        return None
    results = [g.get("result") for g in groups]
    coverage = {"status": worst(results), "detail": detail_of(results)}
    sva_items = [s for s in rec.get("sva") or [] if isinstance(s, dict)]
    sva_statuses = [s.get("status") for s in sva_items]
    sva = ({"status": worst(sva_statuses), "detail": detail_of(sva_statuses)}
           if sva_items else {"status": NA, "detail": "未声明 SVA"})
    scb_items = [s for s in rec.get("scb") or [] if isinstance(s, dict)]
    scb_statuses = [s.get("status") for s in scb_items]
    scb = ({"status": worst(scb_statuses), "detail": detail_of(scb_statuses)}
           if scb_items else {"status": NA, "detail": "未声明 SCB"})
    path_statuses = [(g.get("path") or {}).get("status") for g in groups]
    real_path = [s for s in path_statuses if s and s != "NOT_APPLICABLE"]
    path = ({"status": worst(real_path), "detail": detail_of(real_path)}
            if real_path else {"status": NA, "detail": "未声明 PATH 组"})
    return {"coverage": coverage, "sva": sva, "scoreboard": scb, "path": path}


def _constraints_for_record(rec: Dict[str, Any],
                            constraint_items: Dict[str, List[Dict[str, Any]]]
                            ) -> List[Dict[str, Any]]:
    """一条执行记录的约束项：记录自带 > 契约注册表 > 只有 id（backed 未登记）。"""
    own = rec.get("constraints")
    if isinstance(own, list) and own and isinstance(own[0], dict):
        return list(own)
    case_id = str(rec.get("case_id") or "")
    items = list((constraint_items or {}).get(case_id) or [])
    if items:
        return items
    ids = [str(c) for c in (rec.get("constraint_ids") or []) if str(c)]
    return [{"id": cid, "backed": None, "dimensions": [], "reason": ""}
            for cid in ids]


def _dict_items(value: Any) -> List[Dict[str, Any]]:
    return [v for v in value or [] if isinstance(v, dict)]


def _case_row(task: str, rec: Dict[str, Any], by_id: Dict[str, Any],
              constraint_items: Dict[str, Any]) -> Dict[str, Any]:
    entries = _dict_items(rec.get("tp"))
    tps = [by_id[e["tp_id"]] for e in entries if e.get("tp_id") in by_id]
    feats = sorted({t.get("requirement") for t in tps if t.get("requirement")})
    # **有契约就用 derive 判过的状态**；没有才走 legacy 展示（批次/旧目录）。
    canonical = _canonical_layers(rec)
    if canonical:
        coverage, sva = canonical["coverage"], canonical["sva"]
        scoreboard, path = canonical["scoreboard"], canonical["path"]
    else:
        coverage = _case_coverage(entries, rec)
        sva = _case_sva(rec)
        scoreboard = _case_scb(rec)
        path = _path_of(tps)
    c_items = _constraints_for_record(rec, constraint_items)
    return {
        "name": str(rec.get("test") or task),
        "task": task,
        # ── 第四集合：约束（case 的激励由哪些策略塑造）──
        "constraints": [str(c["id"]) for c in _dict_items(c_items) if c.get("id")],
        "constraint_items": c_items,
        # ── 身份（v2）：CASE/TST 来自生成期注入，legacy 目录如实标注 ──
        "case_id": str(rec.get("case_id") or ""),
        "tst_id": str(rec.get("tst_id") or ""),
        "evd_id": str(rec.get("evd_id") or ""),
        "cell_ids": list(rec.get("cell_ids") or []),
        "legacy": bool(rec.get("legacy")),
        # ── 集合证据（键名与"证据层状态"的 sva 区分开，别撞）──
        "case_status": str(rec.get("case_status") or ""),
        "groups_evidence": _dict_items(rec.get("groups")),
        "sva_items": _dict_items(rec.get("sva")),
        "scb_items": _dict_items(rec.get("scb")),
        "feats": feats,
        "desc": str(rec.get("test_name") or task),
        "coverage": coverage, "sva": sva,
        "scoreboard": scoreboard, "path": path,
        "status_source": "derive" if canonical else "legacy",
        "conclusion": _conclusion({
            "coverage": coverage["status"], "sva": sva["status"],
            "scoreboard": scoreboard["status"], "path": path["status"]}),
    }


def _case_rows(tp_ev: Dict[str, Any],
               records: Dict[str, Dict[str, Any]],
               constraint_items: Dict[str, List[Dict[str, Any]]] = None,
               ) -> List[Dict[str, Any]]:
    by_id = {t["tp_id"]: t for t in tp_ev.get("tps") or []}
    constraint_items = constraint_items or {}
    return [_case_row(task, rec, by_id, constraint_items)
            for task, rec in sorted(records.items())]


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


def _cell_gaps(cells: Dict[str, Any]) -> List[Dict[str, Any]]:
    """**每个未绿 CELL 一条** —— 视图4 必须和 Case×CELL 的颜色对得上。

    TP 层的缺口只看"证据层缺哪一层"，解释不了"PARTIAL（未签核）"这类黄格；
    而人看视图先看颜色。两边各说各的，读的人只能自己脑补差异（实测被指出过）。
    """
    out: List[Dict[str, Any]] = []
    for cell in (cells or {}).get("cells") or []:
        color = str(cell.get("color") or "").lower()
        if color not in ("red", "yellow"):
            continue
        reasons = [str(r) for r in (cell.get("reasons") or []) if str(r).strip()]
        root = "；".join(reasons[:3]) + ("…" if len(reasons) > 3 else "")
        out.append({
            "type": "CELL 未签核" if color == "red" else "CELL 部分证据",
            "item": str(cell.get("cell_id") or ""),
            "root": root or ("缺证据" if color == "red" else "部分 TP 未签核"),
            "action": ("补缺失证据（同一条用例 + 同一种子）" if color == "red"
                       else "补齐未签核 TP 的执行证据 / 接后端"),
            "owner": "待分配",
            "status": "未开始" if color == "red" else "进行中",
        })
    return out


def _gaps(tp_ev: Dict[str, Any], case_tp: Dict[str, Any],
          cells: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    # CELL 层的缺口排前面：它与视图“颜色”一一对应，先回答"哪些格子不绿、为什么"
    out: List[Dict[str, Any]] = _cell_gaps(cells or {})
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


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _ssot_hash(od: Path) -> str:
    """SSOT 指纹 = TP IR + Case IR 的 sha（模型变了，指纹就变）。"""
    digest = hashlib.sha256()
    for rel in ("coverage/testpoints.yaml", "coverage/case_ir.json"):
        try:
            digest.update((od / rel).read_bytes())
        except OSError:
            digest.update(rel.encode("utf-8"))
    return digest.hexdigest()


def _case_tree(case_ir: Dict[str, Any]) -> Dict[str, Any]:
    """视图5：Case 分类树（CCAT → CASE 数 / TST 数）。"""
    cats = [c for c in case_ir.get("categories") or [] if isinstance(c, dict)]
    cases = [c for c in case_ir.get("cases") or [] if isinstance(c, dict)]
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for case in cases:
        for cid in case.get("categories") or []:
            by_cat.setdefault(str(cid), []).append(case)
    rows = []
    for cat in cats:
        cid = str(cat.get("id") or "")
        bound = by_cat.get(cid) or []
        rows.append({
            "id": cid,
            "name": str(cat.get("name") or cid),
            "parent": str(cat.get("parent") or ""),
            "cases": len(bound),
            "tests": sum(len(c.get("tests") or []) for c in bound),
            "source": str(case_ir.get("source") or ""),
        })
    return {"source": str(case_ir.get("source") or ""),
            "rows": rows, "counts": {"categories": len(rows), "cases": len(cases)}}


def _case_cell(case_ir: Dict[str, Any], cells: Dict[str, Any],
               cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """视图6：Case × CELL —— 哪些格子有用例、哪些只有 checker、哪些红。"""
    cell_rows = {str(c.get("cell_id")): c for c in cells.get("cells") or []
                 if isinstance(c, dict)}
    claimed: Dict[str, set] = {}
    for case in case_ir.get("cases") or []:
        cid = str(case.get("id") or "")
        for cell_id in case.get("cells") or []:
            claimed.setdefault(str(cell_id), set()).add(cid)
    seen: Dict[str, set] = {}
    for row in cases:
        for cell_id in row.get("cell_ids") or []:
            seen.setdefault(str(cell_id), set()).add(str(row.get("case_id") or ""))
    rows = []
    for cell_id, cell in sorted(cell_rows.items()):
        rows.append({
            "cell_id": cell_id,
            "cg": cell.get("cg", ""), "p": cell.get("p", ""),
            "color": cell.get("color", ""),
            "tp_count": cell.get("tp_count", 0),
            "declared_cases": sorted(claimed.get(cell_id) or []),
            "observed_cases": sorted(c for c in (seen.get(cell_id) or set()) if c),
        })
    orphans = sorted(set(claimed) - set(cell_rows))
    return {"rows": rows,
            "counts": {"cells": len(rows),
                       "without_case": sum(1 for r in rows
                                           if not r["declared_cases"]),
                       "red": sum(1 for r in rows if r["color"] == "red")},
            "declared_but_missing": orphans}


def _contract_groups(case_ir: Dict[str, Any]) -> List[Dict[str, Any]]:
    """契约里**必须覆盖的全部组**（不只是已经跑出证据的那些）。

    签核先要回答"该覆盖哪些组"；只列"跑过的组"会把漏测的组藏起来。
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for case in case_ir.get("cases") or []:
        if not isinstance(case, dict):
            continue
        for g in case.get("groups") or []:
            key = str((g or {}).get("group") or "")
            if not key:
                continue
            slot = merged.setdefault(key, {
                "group": key, "name": g.get("name", ""),
                "description": g.get("description", ""),
                "coverage_type": g.get("coverage_type", ""),
                "scope": g.get("scope", ""),
                "coverpoints": [], "requirements": [], "checks": [],
                "required_layers": [], "cells": [], "cases": [],
            })
            for field in ("coverpoints", "requirements", "checks",
                          "required_layers"):
                for v in g.get(field) or []:
                    if v and v not in slot[field]:
                        slot[field].append(v)
            if g.get("cell") and g["cell"] not in slot["cells"]:
                slot["cells"].append(g["cell"])
            if case.get("id") and case["id"] not in slot["cases"]:
                slot["cases"].append(case["id"])
    return [merged[k] for k in sorted(merged)]


def _case_constraint_items(case_ir: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """`case_id → [{id, backed, dimensions, reason}]`（来自 case_ir + 注册表）。"""
    backing = case_ir.get("constraint_backing") or {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    for case in case_ir.get("cases") or []:
        if not isinstance(case, dict) or not case.get("id"):
            continue
        items = []
        for cid in case.get("constraints") or []:
            meta = backing.get(str(cid)) or {}
            items.append({
                "id": str(cid),
                "backed": bool(meta.get("backed")),
                "dimensions": list(meta.get("dimensions") or []),
                "reason": str(meta.get("reason") or ""),
            })
        out[str(case["id"])] = items
    return out


def _case_runs(evd: Dict[str, Any]) -> List[Dict[str, Any]]:
    """视图7：执行证据（case × run × seed × cfg × 结论）。"""
    rows = []
    for item in evd.get("evd") or []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "evd_id": item.get("evd_id", ""),
            "case_id": item.get("case_id", ""),
            "tst_id": item.get("tst_id", ""),
            "test": item.get("test", ""),
            "seed": item.get("seed"),
            "stage": item.get("stage", ""),
            "cells": item.get("cells") or [],
            "wave": item.get("wave", ""),
            "legacy": bool(item.get("legacy")),
        })
    return rows


def build_case_view(run_dir: str | Path) -> Dict[str, Any]:
    """一次运行 → `case_associate_view_v2`（七张人读视图的数据）。

    v1 的四张表**字段不变**；v2 增三张（分类树 / Case×CELL / 执行证据）与
    一份元数据（SSOT 指纹、生成时间、只读标记）。
    """
    od = Path(run_dir)
    tp_ev = build_tp_evidence(od)
    records = _case_records(od)
    case_tp = _read_json(od / "coverage" / "case_tp.json")
    case_ir = _read_json(od / "coverage" / "case_ir.json")
    cells = _read_json(od / "coverage" / "cell_matrix.json")
    evd = _read_json(od / "coverage" / "evd.json")

    constraint_items = _case_constraint_items(case_ir)
    cases = _case_rows(tp_ev, records, constraint_items)
    features = _feature_rows(tp_ev)
    gaps = _gaps(tp_ev, case_tp, cells)
    ssot = _ssot_hash(od)
    return {
        "schema": SCHEMA,
        "run": od.name,
        # ── 元数据：每份生成物都要能回答"这是哪个模型版本出的" ──
        "meta": {
            "ver_id": f"VER-{ssot[:12]}",
            "source_ssot": "coverage/testpoints.yaml + coverage/case_ir.json",
            "ssot_sha256": ssot,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "generator": "src.tools.humanview.case_associate_view",
            "confidence": "measured",
            "readonly": True,
        },
        "counts": {"cases": len(cases), "features": len(features),
                   "gaps": len(gaps),
                   "cells": len(cells.get("cells") or []),
                   "evd": len(evd.get("evd") or [])},
        "cases": cases,
        "features": features,
        "matrix": _matrix(tp_ev),
        "gaps": gaps,
        # 约束注册表（来自 case_ir.constraint_backing）：视图回答"这条约束
        # 真编译进模型了吗"。缺省为空 —— 老 run 不编。
        "constraint_backing": dict(case_ir.get("constraint_backing") or {}),
        # ── v2 新增 ──
        # 契约要求的全部覆盖率组（含尚未跑出证据的）—— "必须覆盖什么"的答案
        "contract_groups": _contract_groups(case_ir),
        "case_tree": _case_tree(case_ir),
        "case_cell": _case_cell(case_ir, cells, cases),
        "case_runs": _case_runs(evd),
    }
