"""事实账本 —— append-only JSONL + 哈希链。

三条纪律（对应计划里的不变量 2）：

1. **只追加**：文件只以 `a` 打开；更正靠新事实（`supersedes`），不原地改；
2. **链式防伪**：每条事实带 `prev_hash`，篡改任何一行都会让链断掉；
3. **按包写入**：一次执行产生的全部事实打成 `FactBundle`，**只抢一次锁**，
   并行仿真下不会因为"每条事实一次锁"把采集端拖死。

锁用"建锁文件"的跨平台写法（`O_CREAT|O_EXCL` + 超时重试）：Windows 上没有
`fcntl`，而 `msvcrt.locking` 需要持有文件句柄、退出路径更容易漏。锁文件方案
唯一的代价是进程崩溃可能留下 stale 锁 —— 所以带 `stale_after` 兜底。
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .contract_model import Fact, FactBundle, canonical_hash

LEDGER_NAME = "ledger.jsonl"
INDEX_NAME = "ledger.index.json"
LOCK_NAME = "ledger.lock"


def ledger_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "evidence" / LEDGER_NAME


def _index_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / "evidence" / INDEX_NAME


@contextmanager
def _locked(path: Path, timeout: float = 10.0,
            stale_after: float = 120.0) -> Iterator[None]:
    """跨平台的"建锁文件"互斥；stale 锁超过 `stale_after` 秒自动回收。"""
    lock = path.parent / LOCK_NAME
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale_after:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.time() > deadline:
                raise TimeoutError(f"账本锁超时: {lock}")
            time.sleep(0.02)
    try:
        yield
    finally:
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass


def read_ledger(run_dir: str | Path) -> List[Dict[str, Any]]:
    """读全部事实（坏行跳过并在 `verify_chain` 里报出来）。"""
    path = ledger_path(run_dir)
    out: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if isinstance(doc, dict):
                out.append(doc)
    except OSError:
        return []
    return out


def _head_hash(facts: List[Dict[str, Any]]) -> str:
    return str((facts[-1] or {}).get("hash") or "") if facts else ""


def verify_chain(run_dir: str | Path) -> Dict[str, Any]:
    """校验哈希链 —— 篡改任何一行都会在这里断。"""
    path = ledger_path(run_dir)
    issues: List[Dict[str, Any]] = []
    prev = ""
    count = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"ok": True, "count": 0, "issues": [], "head": "", "exists": False}
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            issues.append({"line": lineno, "check": "not_json"})
            continue
        count += 1
        if doc.get("prev_hash", "") != prev:
            issues.append({"line": lineno, "check": "chain_broken",
                           "expected": prev[:12], "actual": str(doc.get("prev_hash"))[:12]})
        body = {k: v for k, v in doc.items() if k not in ("hash", "prev_hash")}
        if canonical_hash(body) != doc.get("hash"):
            issues.append({"line": lineno, "check": "hash_mismatch"})
        prev = str(doc.get("hash") or "")
    return {"ok": not issues, "count": count, "issues": issues,
            "head": prev, "exists": True}


def _read_index(run_dir: str | Path) -> Dict[str, str]:
    try:
        doc = json.loads(_index_path(run_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def append_bundle(run_dir: str | Path, bundle: FactBundle,
                  timeout: float = 10.0) -> Dict[str, Any]:
    """把一包事实追加进账本（**幂等**：同一包只写一次）。"""
    path = ledger_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = bundle.digest()
    with _locked(path, timeout=timeout):
        index = _read_index(run_dir)
        if index.get(bundle.bundle_id) == digest:
            return {"appended": False, "reason": "duplicate", "facts": 0,
                    "head": _head_hash(read_ledger(run_dir))}
        prev = _head_hash(read_ledger(run_dir))
        lines: List[str] = []
        for fact in bundle.facts:
            sealed = fact.model_copy(deep=True).seal(prev)
            prev = sealed.hash
            lines.append(json.dumps(sealed.model_dump(by_alias=True),
                                    ensure_ascii=False))
        if lines:
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write("\n".join(lines) + "\n")
        index[bundle.bundle_id] = digest
        _index_path(run_dir).write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"appended": True, "facts": len(lines), "head": prev}


def facts_of(ledger: List[Dict[str, Any]], fact_type: str) -> List[Dict[str, Any]]:
    return [f for f in ledger if f.get("type") == fact_type]


__all__ = [
    "LEDGER_NAME", "append_bundle", "facts_of", "ledger_path", "read_ledger",
    "verify_chain",
]
