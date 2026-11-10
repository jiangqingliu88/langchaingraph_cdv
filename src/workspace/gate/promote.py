"""Promote —— **唯一**允许写 `main/` 的代码。

前置条件全部由 Gate 报告机械给出：

  · `gate/<id>.json` 存在且 `ok == true`；
  · `human_required` 为真时必须已有 `approved`；
  · proposal 的 main 基线仍然是当前 main（除非显式 `force`）。

写入是原子的；覆盖/删除前把 main 旧文件备份到 `gate/backups/<id>/`，
最后追加一条 `gate/ledger.jsonl`（签核链：谁提议、什么证据、谁批的）。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..proposal.schema import Proposal
from ..zones import WorkspaceError, WorkspaceZones
from .runner import load_gate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_ledger(zones: WorkspaceZones, row: Dict[str, Any]) -> Path:
    path = zones.ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return path


def _preflight(proposal: Proposal, zones: WorkspaceZones,
               report: Dict[str, Any] | None, force: bool) -> str:
    if report is None:
        return "还没有 Gate 报告，先跑 gate"
    if not report.get("ok") and not force:
        return "Gate 检查未通过，拒绝 promote（开发调试可 --force）"
    if report.get("human_required") and not report.get("approved") and not force:
        return "报告有 open_questions / warn，必须人工批准后才能 promote"
    expected = str((proposal.base or {}).get("main_fingerprint") or "")
    if expected and expected != zones.fingerprint("main") and not force:
        return "main 基线已变化（期间有人 promote），请 rebase 后重跑 gate"
    if not proposal.changed_files:
        return "proposal 没有 changed_files"
    return ""


def _backup(backup_root: Path, rel: str, main_file: Path) -> None:
    if not main_file.exists():
        return
    destination = backup_root / rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(main_file, destination)


def _prune_empty(path: Path, main_root: Path) -> None:
    parent = path.parent
    while parent != main_root and parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def _apply_one(zones: WorkspaceZones, row: Dict[str, Any],
               backup_root: Path) -> tuple[str, Dict[str, Any]]:
    rel = str(row.get("path") or "")
    action = str(row.get("action") or "")
    try:
        staging_file = zones.zone_path(rel, "staging",
                                       must_exist=(action != "delete"))
        main_file = zones.sibling_path(rel, "main",
                                       must_exist=(action == "delete"))
    except WorkspaceError as exc:
        return f"{rel}: {exc}", {}
    if action in ("add", "modify"):
        data = staging_file.read_bytes()
        if _sha256_bytes(data) != row.get("sha256"):
            return f"{rel}: staging 内容已变化（sha 不匹配）", {}
        _backup(backup_root, rel, main_file)
        _atomic_write_bytes(main_file, data)
    elif action == "delete":
        _backup(backup_root, rel, main_file)
        if main_file.exists():
            main_file.unlink()
            _prune_empty(main_file, zones.main)
    else:
        return f"{rel}: 未知 action {action!r}", {}
    return "", {"path": rel, "action": action,
                "sha256": row.get("sha256") if action != "delete" else ""}


def promote(proposal: Proposal, zones: WorkspaceZones, *,
            by: str = "", force: bool = False) -> Dict[str, Any]:
    """把 proposal 的变更从 staging 提升进 main。"""
    report = load_gate(zones, proposal.proposal_id)
    error = _preflight(proposal, zones, report, force)
    if error:
        return {"error": error}

    actual_base = zones.fingerprint("main")
    backup = zones.backup_dir(proposal.proposal_id)
    applied: List[Dict[str, Any]] = []
    for row in proposal.changed_files:
        error, entry = _apply_one(zones, row, backup)
        if error:
            return {"error": error}
        applied.append(entry)

    proposal.status = "promoted"
    proposal.gate = {**proposal.gate, "promoted": True,
                     "promoted_at": _now(),
                     "promoted_by": str(by or ""),
                     "promoted_force": bool(force)}
    proposal.save(zones)
    ledger = _append_ledger(zones, {
        "schema": "workspace_promote_v1",
        "proposal_id": proposal.proposal_id,
        "task": proposal.task,
        "promoted_at": _now(),
        "promoted_by": str(by or ""),
        "forced": bool(force),
        "gate": {"report": f"gate/{proposal.proposal_id}.json",
                 "approved_by": report.get("approver", ""),
                 "approved_at": report.get("approved_at", "")},
        "files": applied,
        "main_fingerprint_before": actual_base,
        "main_fingerprint_after": zones.fingerprint("main"),
    })
    return {
        "ok": True,
        "proposal_id": proposal.proposal_id,
        "files": applied,
        "backup": str(backup),
        "ledger": str(ledger),
        "main_fingerprint": zones.fingerprint("main"),
    }
