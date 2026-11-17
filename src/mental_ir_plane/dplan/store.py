"""DPlan IR 的原子读写。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .model import DesignPlan


def write_dplan(plan: DesignPlan, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, target)
    return target


def read_dplan(path: str | Path) -> DesignPlan:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return DesignPlan.from_dict(doc)


__all__ = ["write_dplan", "read_dplan"]
