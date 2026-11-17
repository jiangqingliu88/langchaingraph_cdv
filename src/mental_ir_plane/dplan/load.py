"""加载 DPlan JSON/YAML → `DesignPlan`。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .model import DesignPlan


def from_dict(doc: Dict[str, Any]) -> DesignPlan:
    return DesignPlan.from_dict(doc)


def load_dplan(path: str | Path) -> DesignPlan:
    source = Path(path)
    text = source.read_text(encoding="utf-8", errors="replace")
    if source.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml

            doc = yaml.safe_load(text) or {}
        except ImportError as exc:  # pragma: no cover - PyYAML 是运行依赖
            raise ValueError("读取 YAML DPlan 需要 PyYAML") from exc
    else:
        try:
            doc = json.loads(text)
        except ValueError as exc:
            raise ValueError(f"DPlan JSON 解析失败：{source}: {exc}") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"DPlan 顶层必须是 object：{source}")
    return DesignPlan.from_dict(doc)


__all__ = ["from_dict", "load_dplan"]
