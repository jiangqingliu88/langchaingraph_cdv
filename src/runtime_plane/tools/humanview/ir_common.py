"""humanview 三个 IR 的公共小工具 —— 只做**归一化 / 取引用 / 比率**，不含语义。

`covg_ir` / `sva_ir` / `scb_ir` 共用同一套约定：

- 顶层 YAML：`schema` + `module` + 各自的实体列表；
- 每条实体都能回指 `contract`（契约编号）并绑定 `cells / paths / feats`；
- 完整性度量统一输出 `{name, covered, total, pct, ok}`。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def as_list(value: Any) -> List[Any]:
    """None → []；标量 → [标量]；列表原样。"""
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def norm_id(value: Any) -> str:
    return str(value or "").strip()


def norm_ids(values: Any) -> List[str]:
    """多值引用 → 去重后的非空字符串列表（保持输入顺序）。"""
    out: List[str] = []
    for item in as_list(values):
        text = norm_id(item)
        if text and text not in out:
            out.append(text)
    return out


def load_doc(text_or_path: str | Path) -> Dict[str, Any]:
    """YAML 文本或文件路径 → dict。解析失败抛 ValueError（调用方转成 error）。"""
    import yaml as _yaml

    raw = str(text_or_path)
    path = Path(raw)
    try:
        if path.is_file():
            raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    doc = _yaml.safe_load(raw) or {}
    if not isinstance(doc, dict):
        raise ValueError("顶层必须是 mapping")
    return doc


def ratio(covered: int, total: int) -> float:
    return round(100.0 * covered / total, 2) if total else 0.0


def metric(name: str, covered: int, total: int,
           target: float = 100.0) -> Dict[str, Any]:
    pct = ratio(covered, total)
    return {"name": name, "covered": covered, "total": total, "pct": pct,
            "target": target, "ok": total > 0 and pct >= target}


def refs(entry: Any, *keys: str) -> List[str]:
    """从 dict/dataclass 上取多个引用字段（cells/paths/feats）并归一。"""
    out: List[str] = []
    for key in keys:
        value = entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)
        for item in norm_ids(value):
            if item not in out:
                out.append(item)
    return out


def duplicates(items: Iterable[Any], key_fn) -> Dict[str, List[Any]]:
    """按 key 分组，返回出现 >1 次的组（保持首次出现顺序）。"""
    groups: Dict[str, List[Any]] = {}
    for item in items:
        key = key_fn(item)
        if key:
            groups.setdefault(key, []).append(item)
    return {k: v for k, v in groups.items() if len(v) > 1}


def result(errors: List[str] = None, warnings: List[str] = None,
           metrics: List[Dict[str, Any]] = None,
           details: Dict[str, Any] = None) -> Dict[str, Any]:
    """统一的校验结果形状：`{ok, errors, warnings, metrics, details}`。"""
    errs, warns = list(errors or []), list(warnings or [])
    mets = list(metrics or [])
    return {"ok": not errs, "errors": errs, "warnings": warns,
            "metrics": mets, "details": details or {}}


def dedupe_lines(items: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(str(x) for x in items if str(x).strip()))
