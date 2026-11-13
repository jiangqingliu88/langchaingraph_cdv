"""人机审阅 —— 意图 / 结论 / 解释 / 下一轮上下文 / 证据门禁。

审阅动作**只改人工状态**，不改 derive 判定、不伪造证据：
  · Intent：CANDIDATE → CONFIRMED / REJECTED（确认需签核人或证据）
  · Claim ：CANDIDATE → CONFIRMED / REJECTED（人工确认会记 confirmed_by）
  · Interpretation：DRAFT → REVIEWED / REJECTED（解释仍是 HYPOTHESIS）
动作全部进 `docs/action_audit.jsonl`，带 `appr_id`。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from src.core.runtime.atomic import atomic_write_json
from src.layers.l2_orchestration.flow_shared import _read_json, _resolve_run_dir

SCHEMA = "review_board_v1"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    for line in text.splitlines():
        try:
            rec = json.loads(line) if line.strip() else {}
        except ValueError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def _audit(root: Path, action: str, *, reviewer: str, input_sha: str,
           output_sha: str) -> None:
    try:
        from src.layers.l3_decision.control_plane import approval_token, record

        record(root, {"action": action, "role": "engineer",
                      "decision": "APPROVAL", "risk": "HIGH",
                      "policy_id": "CP-REVIEW", "reason": "",
                      "input_sha": input_sha},
               actor=reviewer, output_sha=output_sha,
               appr_id=approval_token(action, actor=reviewer,
                                      input_sha=input_sha))
    except Exception:                                  # noqa: BLE001 旁路
        pass


# ═══════════════════════════════════════════════════════════
# 读取
# ═══════════════════════════════════════════════════════════

def _intents(root: Path) -> List[Dict[str, Any]]:
    doc = _read_json(root / "coverage" / "intents.json") or {}
    rows = [i for i in (doc.get("intents") or []) if isinstance(i, dict)]
    if rows:
        return rows
    # 老 run 没有 intents.json：从 case_ir 现编译一份**只读视图**（不写盘）
    case_ir = _read_json(root / "coverage" / "case_ir.json") or {}
    if not case_ir.get("cases"):
        return []
    from src.layers.l3_decision.intent import intents_from_case_ir
    return [i.to_dict() for i in intents_from_case_ir(
        case_ir, module=str(case_ir.get("module") or ""))]


def _claims(root: Path, intents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    doc = _read_json(root / "coverage" / "claims.json") or {}
    rows = [c for c in (doc.get("claims") or []) if isinstance(c, dict)]
    if rows:
        return rows
    from src.layers.l3_decision.claims import claims_from_intents
    from src.layers.l3_decision.intent import from_dict
    return [c.to_dict() for c in claims_from_intents(
        [from_dict(i) for i in intents])]


def _interpretations(root: Path) -> Dict[str, Any]:
    return _read_json(root / "status" / "interpretations.json") or {}


def _context_rows(root: Path) -> List[Dict[str, Any]]:
    ctx = _read_json(root / "status" / "next_iteration_context.json") or {}
    rows: List[Dict[str, Any]] = []
    for item in ctx.get("open_obligations") or []:
        rows.append({"section": "未决义务", "item": item.get("obligation_id"),
                     "status": item.get("status"),
                     "detail": f"case={item.get('case_id') or '?'} "
                               f"tp={item.get('tp_id') or '?'}"})
    for item in ctx.get("coverage_holes") or []:
        rows.append({"section": "覆盖缺口", "item": item.get("tp_id") or item.get("bin"),
                     "status": item.get("action") or "",
                     "detail": f"{item.get('dimension') or ''} {item.get('owner_test') or ''}".strip()})
    for cid in ((ctx.get("evidence") or {}).get("claims_without_evidence") or []):
        rows.append({"section": "无证据 Claim", "item": cid, "status": "CANDIDATE",
                     "detail": "还没有引擎/人工证据"})
    return rows


def _claim_source_rows(index: Dict[str, Any],
                       sources: Dict[str, Any]) -> List[Dict[str, Any]]:
    counts = index.get("claim_counts") or {}
    return [
        {"check": "Claim 总数", "value": counts.get("total", 0),
         "status": "OK", "detail": "coverage/claims.json"},
        {"check": "有证据 Claim", "value": counts.get("with_evidence", 0),
         "status": "OK", "detail": "OBSERVED / HUMAN_DECISION / DERIVED"},
        {"check": "无证据 Claim", "value": counts.get("without_evidence", 0),
         "status": "WARN", "detail": "仍是 CANDIDATE（正常，但签核前要收敛）"},
        {"check": "可用证据源", "value": len(sources.get("available") or []),
         "status": "OK", "detail": ", ".join(sources.get("available") or [])},
        {"check": "占位证据源", "value": len(sources.get("dummy") or []),
         "status": "WARN", "detail": ", ".join(sources.get("dummy") or [])},
    ]


def _obligation_rows(obligations: Dict[str, Any],
                     closure: Dict[str, Any]) -> List[Dict[str, Any]]:
    failed = [o for o in (obligations.get("obligations") or [])
              if isinstance(o, dict) and o.get("status") == "FAILED"]
    return [
        {"check": "失败义务", "value": len(failed),
         "status": "BLOCK" if failed else "OK",
         "detail": "obligations_v3 FAILED"},
        {"check": "闭环未收敛", "value": bool(closure.get("continue")),
         "status": "WARN" if closure.get("continue") else "OK",
         "detail": "status/closure_plan.json"},
    ]


def _unapproved_row(root: Path) -> Dict[str, Any]:
    approved, high = set(), set()
    for rec in _read_jsonl(root / "docs" / "action_audit.jsonl"):
        if rec.get("decision") == "APPROVAL" and rec.get("appr_id"):
            approved.add(str(rec.get("action")))
        if str(rec.get("risk") or "") == "HIGH":
            high.add(str(rec.get("action")))
    unapproved = sorted(high - approved)
    return {"check": "高风险未审批", "value": len(unapproved),
            "status": "BLOCK" if unapproved else "OK",
            "detail": ", ".join(unapproved)}


def _gate_rows(root: Path) -> List[Dict[str, Any]]:
    index = _read_json(root / "docs" / "evidence_index.json") or {}
    sources = _read_json(root / "docs" / "evidence_sources.json") or {}
    obligations = _read_json(root / "docs" / "obligations_v3.json") or {}
    closure = _read_json(root / "status" / "closure_plan.json") or {}
    return (_claim_source_rows(index, sources)
            + _obligation_rows(obligations, closure)
            + [_unapproved_row(root)])


def review_board(run_dir: str = "") -> Dict[str, Any]:
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error
    intents = _intents(root)
    claims = _claims(root, intents)
    interps = _interpretations(root)
    return {
        "available": True,
        "run_dir": str(root),
        "schema": SCHEMA,
        "intents": [{
            "kind": "intent", "item_id": i.get("intent_id"),
            "case_id": i.get("case_id"), "statement": i.get("statement"),
            "goals": len(i.get("goals") or []),
            "status": i.get("status") or "CANDIDATE",
            "confirmed_by": i.get("confirmed_by") or "",
            "source": i.get("source") or "",
        } for i in intents],
        "claims": [{
            "kind": "claim", "item_id": c.get("claim_id"),
            "case_id": c.get("case_id"), "statement": c.get("statement"),
            "evidence_required": ", ".join(c.get("evidence_required") or []),
            "status": c.get("status") or "CANDIDATE",
            "confirmed_by": c.get("confirmed_by") or "",
        } for c in claims],
        "interpretations": [{
            "kind": "interpretation", "item_id": i.get("interp_id"),
            "actor": i.get("actor"), "status": i.get("status") or "DRAFT",
            "insights": len(i.get("insights") or []),
            "plan_updates": len(i.get("plan_updates") or []),
            "reviewed_by": i.get("reviewed_by") or "",
            "reviewed_at": i.get("reviewed_at") or "",
            "preview": "；".join(
                str(x.get("statement") or "") for x in
                (i.get("insights") or [])[:2]),
        } for i in (interps.get("items") or []) if isinstance(i, dict)],
        "context": _context_rows(root),
        "gate": _gate_rows(root),
        "gate_mode": os.environ.get("SIGNOFFAI_EVIDENCE_GATE", "report"),
    }


# ═══════════════════════════════════════════════════════════
# 审阅动作
# ═══════════════════════════════════════════════════════════

def _materialize_intents(root: Path):
    """老 run 没有 intents.json 时，从 case_ir 生成一份可审阅的构建物。"""
    from src.layers.l3_decision.intent import (
        intents_from_case_ir, load_intents, save_intents,
    )
    intents = load_intents(root)
    if intents:
        return intents
    case_ir = _read_json(root / "coverage" / "case_ir.json") or {}
    intents = intents_from_case_ir(case_ir,
                                   module=str(case_ir.get("module") or ""))
    if intents:
        save_intents(root, intents)
    return intents


def _materialize_claims(root: Path):
    from src.layers.l3_decision.claims import (
        claims_from_intents, load_claims, save_claims,
    )
    claims = load_claims(root)
    if claims:
        return claims
    claims = claims_from_intents(_materialize_intents(root))
    if claims:
        save_claims(root, claims)
    return claims


def _decide_intent(root: Path, item_id: str, decision: str,
                   reviewer: str, comment: str) -> Dict[str, Any]:
    from src.layers.l3_decision.intent import promote, save_intents
    intents = _materialize_intents(root)
    target = next((i for i in intents if i.intent_id == item_id), None)
    if target is None:
        return {"error": f"Intent 不存在：{item_id}"}
    if decision == "CANDIDATE":
        target.status = "CANDIDATE"
        target.confirmed_by = ""
    else:
        promote(target, decision, by=reviewer)
    target.metadata["review_note"] = comment
    target.metadata["reviewed_at"] = _now()
    save_intents(root, intents)
    return {"ok": True, "kind": "intent", "item_id": item_id,
            "decision": decision}


def _decide_claim(root: Path, item_id: str, decision: str,
                  reviewer: str, comment: str) -> Dict[str, Any]:
    from src.layers.l3_decision.claims import save_claims
    if decision not in ("CONFIRMED", "REJECTED", "CANDIDATE"):
        return {"error": f"未知 Claim 结论：{decision}"}
    claims = _materialize_claims(root)
    target = next((c for c in claims if c.claim_id == item_id), None)
    if target is None:
        return {"error": f"Claim 不存在：{item_id}"}
    if decision == "CONFIRMED" and not reviewer:
        return {"error": "确认 Claim 需要签核人（或先补引擎证据）"}
    target.status = decision
    target.confirmed_by = reviewer if decision != "CANDIDATE" else ""
    target.confirmed_at = _now() if decision != "CANDIDATE" else ""
    if decision == "CONFIRMED":
        # 人工确认：producer_class 记为 human（agent 结论不能自称事实）。
        target.producer_class = "human"
    target.evidence_ids = list(target.evidence_ids)
    save_claims(root, claims)
    return {"ok": True, "kind": "claim", "item_id": item_id,
            "decision": decision}


def _decide_interp(root: Path, item_id: str, decision: str,
                   reviewer: str, comment: str) -> Dict[str, Any]:
    path = root / "status" / "interpretations.json"
    doc = _read_json(path) or {}
    targets = [i for i in (doc.get("items") or [])
               if isinstance(i, dict) and i.get("interp_id") == item_id]
    if not targets:
        return {"error": f"解释不存在：{item_id}"}
    for item in targets:
        item["status"] = decision
        item["reviewed_by"] = reviewer
        item["reviewed_at"] = _now()
        item["review_note"] = comment
    atomic_write_json(path, doc)
    return {"ok": True, "kind": "interpretation", "item_id": item_id,
            "decision": decision}


def review_decide(run_dir: str = "", kind: str = "", item_id: str = "",
                  decision: str = "", reviewer: str = "",
                  comment: str = "") -> Dict[str, Any]:
    """人工审阅结论。kind = intent | claim | interpretation。"""
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error
    kind = str(kind or "").lower()
    decision = str(decision or "").upper()
    if kind == "interpretation" and decision not in ("REVIEWED", "REJECTED",
                                                     "DRAFT"):
        return {"error": f"未知解释结论：{decision}（REVIEWED/REJECTED/DRAFT）"}
    if kind == "intent" and decision not in ("CONFIRMED", "REJECTED",
                                             "CANDIDATE"):
        return {"error": f"未知意图结论：{decision}"}
    reviewer = str(reviewer or "").strip()
    if kind in ("intent", "claim") and decision != "CANDIDATE" and not reviewer:
        return {"error": "确认/驳回必须填写审阅人"}
    handlers = {"intent": _decide_intent, "claim": _decide_claim,
                "interpretation": _decide_interp}
    handler = handlers.get(kind)
    if handler is None:
        return {"error": f"未知审阅类型：{kind}"}
    result = handler(root, str(item_id or ""), decision, reviewer,
                     str(comment or ""))
    if result.get("error"):
        return result
    _audit(root, f"review_{kind}", reviewer=reviewer,
           input_sha=str(item_id), output_sha=_now())
    board = review_board(str(root))
    board["recorded"] = result
    return board


__all__ = ["SCHEMA", "review_board", "review_decide"]
