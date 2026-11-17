"""统一 IR 的原子读写。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .schema import UnifiedIR


def write_unified(ir: UnifiedIR, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(ir.to_dict(), ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, target)
    return target


def read_unified(path: str | Path) -> UnifiedIR:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("统一 IR 必须是 JSON object")
    return UnifiedIR.from_dict(doc)


__all__ = ["write_unified", "read_unified"]
