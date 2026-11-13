"""`find_spec_yaml` 的产物所有权清单 —— 只删自己的，不清共享目录。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

OWNED_MANIFEST = ".find_spec_manifest.json"


def clean_owned_yaml(archive: Path) -> None:
    """只删**本工具上一轮生成**的 YAML（manifest 记录）；拿不到就不删。

    这是"禁止清空共享目录"的机制：目录里可能有其它步骤写的文件，删不删
    由各步骤自己的 manifest 说话，而不是由后跑的那一步一刀切。
    """
    try:
        names = json.loads((archive / OWNED_MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for name in names if isinstance(names, list) else []:
        try:
            (archive / str(name)).unlink(missing_ok=True)
        except OSError:
            pass


def record_owned_yaml(archive: Path, files: List[str]) -> None:
    """记录本工具的产物清单（原子写；崩在半路也不会留下半截 manifest）。"""
    from src.runtime_plane.core.runtime.atomic import atomic_write_json

    names = sorted({Path(str(f)).name for f in files if str(f)})
    atomic_write_json(archive / OWNED_MANIFEST, names)


__all__ = ["OWNED_MANIFEST", "clean_owned_yaml", "record_owned_yaml"]
