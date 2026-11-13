"""证据包只读查询 —— 统一 envelope 基础段；profile 业务字段保持原样。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from src.runtime_plane.core.contracts.evidence import validate_envelope


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def read_envelope(package_dir: str | Path) -> Dict[str, Any]:
    """读 `manifest.json` 的 envelope 段；老包没有 envelope 时返回空。"""
    manifest = _read_json(Path(package_dir) / "manifest.json")
    env = manifest.get("envelope")
    return env if isinstance(env, dict) else {}


def validate_evidence(package_dir: str | Path) -> List[Dict[str, str]]:
    manifest = _read_json(Path(package_dir) / "manifest.json")
    if not manifest:
        return [{"code": "missing_manifest", "message": "没有 manifest.json"}]
    env = manifest.get("envelope")
    if not isinstance(env, dict):
        return [{"code": "missing_envelope", "message": "老包没有 envelope 段"}]
    return validate_envelope(env)
