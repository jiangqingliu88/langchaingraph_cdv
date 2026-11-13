"""纯代码审计门 —— Supervisor 不相信子图的“我干完了”。

它先调用既有的确定性 `n_audit`（不经过 LLM），再独立核对：
  · `<run>/report.json` 是否存在且可读；
  · `<run>/signoff_evidence/manifest.json` 是否存在且可读；
  · 两者是否都带可解析的 JSON。
失败只写 `audit_gate` 读数，不删除已有证据；三态判定仍由 `n_audit` 负责。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import structlog

from src.layers.l2_orchestration.evidence.signoff_package import verify_package

logger = structlog.get_logger()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


async def n_hard_audit_gate(state, config) -> Dict[str, Any]:
    """执行审计 + 纯代码核对；返回 audit 更新与 `audit_gate`。"""
    from src.agent.runtime.pipeline_nodes.signoff import n_audit

    data = await n_audit(state, config)
    root = Path(getattr(state, "output_root", "") or ".")
    report_path = root / "report.json"
    evidence_path = root / "signoff_evidence" / "manifest.json"
    report = _read_json(report_path)
    evidence = _read_json(evidence_path)
    verification = verify_package(evidence_path.parent) if evidence_path.is_file() else {}
    ok = bool(report) and bool(evidence) and bool(verification.get("ok"))
    gate = {
        "ok": ok,
        "report": report_path.relative_to(root).as_posix()
        if report_path.is_file() else "",
        "evidence": evidence_path.relative_to(root).as_posix()
        if evidence_path.is_file() else "",
        "verdict": str(report.get("verdict") or ""),
        "signoff_status": str(report.get("signoff_status") or ""),
        "package_hash": str(evidence.get("package_hash") or ""),
        "verification": {
            "ok": bool(verification.get("ok")),
            "issues": list(verification.get("issues") or [])[:10],
        },
    }
    if not ok:
        logger.error(
            "Supervisor 硬审计不通过：report.json / signoff_evidence/manifest.json "
            "缺失、不可读或 package_hash 校验失败 —— 子图的结论不能直接当签核")
    merged = dict(data) if isinstance(data, dict) else {}
    merged["audit_gate"] = gate
    if not ok:
        merged.update({
            "interrupted": True,
            "terminal_reason": "audit_gate_failed",
        })
    return merged


__all__ = ["n_hard_audit_gate"]
