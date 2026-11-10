"""跑 Gate 检查并落 `gate/<proposal_id>.json`；人工批准也只改这一份。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from src.core.runtime.atomic import atomic_write_json

from ..proposal.schema import Proposal
from ..zones import WorkspaceZones
from .checks import DEFAULT_CHECKS, GateHook

REPORT_SCHEMA = "gate_report_v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_gate(proposal: Proposal, zones: WorkspaceZones,
             extra_checks: Iterable[GateHook] = ()) -> Dict[str, Any]:
    """执行默认检查 + 领域钩子；任何 block 失败即 `ok=False`。"""
    checks: List[Dict[str, Any]] = []
    for check in DEFAULT_CHECKS:
        try:
            checks.extend(check(proposal, zones))
        except Exception as exc:                     # noqa: BLE001 检查自身崩了 = 失败
            checks.append({"name": getattr(check, "__name__", "check"),
                           "status": "fail", "severity": "block",
                           "detail": f"检查异常：{exc}"})
    for hook in extra_checks:
        try:
            result = hook(proposal, zones)
        except Exception as exc:                     # noqa: BLE001
            checks.append({"name": getattr(hook, "__name__", "domain_check"),
                           "status": "fail", "severity": "block",
                           "detail": f"领域检查异常：{exc}"})
            continue
        if isinstance(result, dict):
            result = [result]
        checks.extend(dict(row) for row in (result or []))

    blocked = [row for row in checks
               if row.get("status") == "fail" and row.get("severity") == "block"]
    human_required = bool(proposal.open_questions) or any(
        row.get("human") for row in checks)
    report = {
        "schema": REPORT_SCHEMA,
        "proposal_id": proposal.proposal_id,
        "task": proposal.task,
        "ok": not blocked,
        "human_required": human_required,
        "approved": False,
        "approver": "",
        "approved_at": "",
        "comment": "",
        "created_at": _now(),
        "main_fingerprint": zones.fingerprint("main"),
        "open_questions": list(proposal.open_questions),
        "checks": checks,
    }
    atomic_write_json(zones.gate_path(proposal.proposal_id), report)
    proposal.gate = {"report": f"gate/{proposal.proposal_id}.json",
                     "ok": report["ok"],
                     "human_required": human_required}
    proposal.save(zones)
    return report


def load_gate(zones: WorkspaceZones, proposal_id: str) -> Optional[Dict[str, Any]]:
    path = zones.gate_path(proposal_id)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def approve_gate(proposal: Proposal, zones: WorkspaceZones, *,
                 by: str, comment: str = "") -> Dict[str, Any]:
    """人工批准：只有检查已通过的报告才可批；批准人必填。"""
    by = str(by or "").strip()
    if not by:
        return {"error": "人工批准必须填写批准人（by）"}
    report = load_gate(zones, proposal.proposal_id)
    if report is None:
        return {"error": "还没有 Gate 报告，先跑 gate"}
    if not report.get("ok"):
        return {"error": "Gate 检查未通过，不能批准"}
    report.update({"approved": True, "approver": by,
                   "approved_at": _now(), "comment": str(comment or "")})
    atomic_write_json(zones.gate_path(proposal.proposal_id), report)
    proposal.status = "accepted"
    proposal.gate = {"report": f"gate/{proposal.proposal_id}.json",
                      "ok": True,
                      "human_required": bool(report.get("human_required")),
                      "approved": True, "approver": by}
    proposal.save(zones)
    return report
