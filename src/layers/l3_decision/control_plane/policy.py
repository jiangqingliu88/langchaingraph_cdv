"""控制平面策略 —— `config/control_plane.yaml`，模块可覆盖。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .actions import AUTO, DEFAULT_ACTIONS, FORBIDDEN, TOOL_ACTION_DECISION

_ROOT = Path(__file__).resolve().parents[4]
_LEVELS = {AUTO, "APPROVAL", FORBIDDEN}


def _default_doc() -> Dict[str, Any]:
    return {
        "schema": "control_plane_policy_v1",
        "defaults": {"unknown_action": FORBIDDEN,
                     "tool_action": TOOL_ACTION_DECISION[0],
                     "tool_risk": TOOL_ACTION_DECISION[1]},
        "rules": {a: {"decision": d, "risk": r}
                  for a, (d, r) in DEFAULT_ACTIONS.items()},
    }


def _merge(doc: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    out = {**base, "defaults": dict(base["defaults"]),
           "rules": {k: dict(v) for k, v in base["rules"].items()}}
    for key, value in (doc.get("defaults") or {}).items():
        out["defaults"][str(key)] = value
    for item in (doc.get("rules") or []):
        if not isinstance(item, dict) or not item.get("action"):
            continue
        action = str(item["action"])
        entry = out["rules"].setdefault(action, {"decision": AUTO, "risk": "LOW"})
        decision = str(item.get("decision") or "").upper()
        if decision in _LEVELS:
            entry["decision"] = decision
        if item.get("risk"):
            entry["risk"] = str(item["risk"]).upper()
        if item.get("enabled") is False:
            entry["enabled"] = False
    return out


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, ImportError):
        return {}
    return doc if isinstance(doc, dict) else {}


def load_policy(module: str = "", path: str | Path = None) -> Dict[str, Any]:
    """默认表 → 项目策略 → 模块策略（后者覆盖前者）。"""
    policy = _default_doc()
    policy = _merge(_load_yaml(Path(path or _ROOT / "config" /
                                    "control_plane.yaml")), policy)
    if module:
        policy = _merge(_load_yaml(_ROOT / "specs" / module /
                                   "control_plane.yaml"), policy)
    policy["schema"] = "control_plane_policy_v1"
    return policy


__all__ = ["load_policy"]
