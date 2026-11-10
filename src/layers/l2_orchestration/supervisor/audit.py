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

from src.layers.l2_orchestration.nodes.agent.signoff import n_audit

logger = structlog.get_logger()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


async def n_hard_audit_gate(state, config) -> Dict[str, Any]:
    """执行审计 + 纯代码核对；返回 audit 更新与 `audit_gate`。"""
    data = await n_audit(state, config)
    root = Path(getattr(state, "output_root", "") or ".")
    report_path = root / "report.json"
    evidence_path = root / "signoff_evidence" / "manifest.json"
    report = _read_json(report_path)
    evidence = _read_json(evidence_path)
    ok = bool(report) and bool(evidence)
    gate = {
        "ok": ok,
        "report": report_path.relative_to(root).as_posix()
        if report_path.is_file() else "",
        "evidence": evidence_path.relative_to(root).as_posix()
        if evidence_path.is_file() else "",
        "verdict": str(report.get("verdict") or ""),
        "signoff_status": str(report.get("signoff_status") or ""),
        "package_hash": str(evidence.get("package_hash") or ""),
    }
    if not ok:
        logger.error(
            "Supervisor 硬审计不通过：report.json / signoff_evidence/manifest.json "
            "缺失或不可读 —— 子图的结论不能直接当签核")
    merged = dict(data) if isinstance(data, dict) else {}
    merged["audit_gate"] = gate
    return merged


__all__ = ["n_hard_audit_gate"]
