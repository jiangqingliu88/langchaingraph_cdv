"""RTL diff —— 只比内容哈希，不看时间戳。

时间戳不可靠（checkout、touch、拷贝都会变），而证据链本来就以 SHA256 为身份。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Tuple

EXTS = (".v", ".sv", ".svh", ".vh")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _rtl_dir(root: Path) -> Path:
    return root / "rtl" if (root / "rtl").is_dir() else root


def snapshot(root: str | Path) -> Dict[str, str]:
    """`{相对路径: sha256}`，只收 RTL 后缀。"""
    base = _rtl_dir(Path(root))
    if not base.is_dir():
        return {}
    out: Dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        if path.is_file() and path.suffix.lower() in EXTS:
            out[path.relative_to(base).as_posix()] = _sha(path)
    return out


def diff_snapshots(baseline: Dict[str, str], current: Dict[str, str]) -> Dict[str, Any]:
    added = sorted(set(current) - set(baseline))
    removed = sorted(set(baseline) - set(current))
    modified = sorted(k for k in (set(baseline) & set(current))
                      if baseline[k] != current[k])
    changed = sorted(set(added) | set(removed) | set(modified))
    return {
        "added": added,
        "modified": modified,
        "removed": removed,
        "changed": changed,
        "unchanged": len(set(baseline) & set(current)) - len(modified),
        "baseline_files": len(baseline),
        "current_files": len(current),
    }


def diff_runs(baseline_run: str | Path, current_run: str | Path) -> Dict[str, Any]:
    base = snapshot(baseline_run)
    cur = snapshot(current_run)
    out = diff_snapshots(base, cur)
    out["baseline_run"] = Path(baseline_run).name
    out["current_run"] = Path(current_run).name
    return out
