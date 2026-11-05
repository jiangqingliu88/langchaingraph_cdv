"""原子落盘 —— 同目录临时文件 + `os.replace`。

为什么需要：证据链里的 JSON/YAML 一旦被读者看到，就必须是**完整的一份**。
进程在 `write_text` 中途崩溃、或两个步骤并发写同一路径，都会留下半截文件；
而下游（gate / derive / 证据包）读到半截 JSON 时通常只会"跳过坏行"或
"字段缺失"，**静默降级**比报错更危险。

这里只做一件事：写到同目录的 `.tmp`，`flush + fsync`，再 `os.replace`。
同卷 rename 是原子的（Windows 上 `os.replace` 亦如此）。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: str | Path, text: str, *,
                      encoding: str = "utf-8", newline: str = "\n") -> Path:
    """原子写文本；返回目标路径。父目录会自动创建。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp",
                               dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


def atomic_write_json(path: str | Path, doc: Any, *,
                      indent: int = 2, ensure_ascii: bool = False) -> Path:
    """原子写 JSON（默认带换行，便于 diff）。"""
    return atomic_write_text(
        path, json.dumps(doc, ensure_ascii=ensure_ascii, indent=indent) + "\n")


__all__ = ["atomic_write_json", "atomic_write_text"]
