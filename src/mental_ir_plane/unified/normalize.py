"""统一 IR 的纯函数工具：id / token / 列表归一化。"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

_STOP = {
    "and", "or", "the", "for", "with", "basic", "test", "block", "mode",
    "of", "to", "in", "on", "is", "a", "an", "be", "by", "as", "at",
}


def safe_id(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "_", text).strip("_")
    return text or fallback


def items(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return [row for row in value if isinstance(row, dict)]
    return []


def text_of(row: Dict[str, Any], keys: Iterable[str]) -> str:
    return " ".join(str(row.get(k) or "") for k in keys if row.get(k))


def tokens(value: Any) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", str(value or ""))
    return {w.lower() for w in words if w.lower() not in _STOP and len(w) > 1}


def score(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return round(len(a & b) / max(1, min(len(a), len(b))), 3)


def split_ids(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value or "")
    for sep in ("|", ",", ";", "、"):
        if sep in text:
            return [x.strip() for x in text.split(sep) if x.strip()]
    return [text.strip()] if text.strip() else []


def find_garble(value: Any) -> int:
    """U+FFFD 的数量 —— 乱码只记录，不猜修。"""
    return str(value or "").count("�")


__all__ = ["safe_id", "items", "text_of", "tokens", "score", "split_ids", "find_garble"]
