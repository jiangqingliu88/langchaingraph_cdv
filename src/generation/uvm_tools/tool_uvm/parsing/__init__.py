"""解析层 —— 读 YAML/spec，转成 `models` 的 dataclass。

第一批只提供薄封装，避免一次性搬动 2000 行解析器；后续把
`YAMLLoader` 的纯部分逐步迁进来。**不渲染、不写文件。**
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def load_yaml(path: str | Path) -> Dict[str, Any]:
    import yaml

    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8", errors="replace"))
    return doc if isinstance(doc, dict) else {}


__all__ = ["load_yaml"]
