"""确定性 JSONL / 规范 JSON 读写。

纪律：
  · **只追加**的事实日志用 `append_jsonl`；全量重写用 `write_jsonl`；
  · 排序 + `sort_keys` + 不写时间戳，保证同一输入重复构建得到同一字节；
  · 写入走 tmp + `os.replace`，不会留下半截文件。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def read_jsonl(path: str | Path) -> List[dict]:
    out: List[dict] = []
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except ValueError:
                    continue          # 崩溃留下的半行，跳过
                if isinstance(doc, dict):
                    out.append(doc)
    except OSError:
        return out
    return out


def write_jsonl(path: str | Path, rows: Iterable[dict], *,
                sort_key: Optional[Callable[[dict], Any]] = None) -> str:
    """全量重写。返回 sha256（空文件返回空串）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = list(rows)
    if sort_key is not None:
        data.sort(key=sort_key)
    body = "".join(canonical_json(row) + "\n" for row in data)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return hashlib.sha256(body.encode("utf-8")).hexdigest() if body else ""


def append_jsonl(path: str | Path, row: dict) -> bool:
    """追加一行；失败不抛（观测写入不该带崩主流程）。"""
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(canonical_json(row) + "\n")
            fh.flush()
        return True
    except OSError:
        return False
