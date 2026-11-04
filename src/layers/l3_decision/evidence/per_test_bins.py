"""Per-test 覆盖率生产端 —— 回归目录里的逐 test ucdb → `coverage/per_test_bins.json`。

    regression_run/<stage>/.../test_<name>_seed_<n>/cov/<test>/_ucdb/*.ucdb
                              │
                              ▼   vcover report -cvg -details
                 _parse_cvg_bin_hits()（唯一解析实现）
                              │
                              ▼
            coverage/per_test_bins.json  ← 现有 attribution 的 exact 证据源

**没有 vcover / 没有 ucdb 时明确返回 unavailable**，不编造"精确命中"。
包含以下事实：
- `tests`：test（去掉 `test_` 前缀与 `_seed_<n>` 后缀）→ 命中 bin 列表；
- `per_seed`：`<test>@<seed>` → 命中 bin 列表（验收边界用）；
- `sources`：每个 ucdb 的路径、bins 数与错误；`errors` 汇总。

同一 test 多 seed 的 bin 取**并集**（`tests` 是既有多数消费者吃的形状）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA = "per_test_bins_v1"
FLAG = "SIGNOFFAI_PER_TEST_COVERAGE"
_SEED_RE = re.compile(r"_seed_(\d+)")
_PREFIX = "test_"


def enabled() -> bool:
    """默认开启；显式 off/0/false 才跳过（不静默改行为，只给出口）。"""
    return os.environ.get(FLAG, "").strip().lower() not in (
        "0", "off", "false", "no")


def _base_test(name: str) -> str:
    base = name[len(_PREFIX):] if name.startswith(_PREFIX) else name
    return _SEED_RE.sub("", base).rstrip("_") or base


def _seed_of(name: str) -> Optional[int]:
    found = _SEED_RE.findall(name)
    return int(found[-1]) if found else None


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def find_per_test_ucdbs(root: str | Path) -> List[Dict[str, Any]]:
    """回归目录 → 逐 test 的 ucdb 清单（确定性排序，不跑 EDA）。"""
    reg = Path(root) / "regression_run"
    if not reg.is_dir():
        return []
    out: List[Dict[str, Any]] = []
    for test_dir in sorted(reg.rglob("test_*")):
        if not test_dir.is_dir():
            continue
        ucdbs = sorted(test_dir.rglob("*.ucdb"))
        if not ucdbs:
            continue
        out.append({
            "test": _base_test(test_dir.name),
            "task": test_dir.name,
            "seed": _seed_of(test_dir.name),
            "stage": test_dir.relative_to(reg).parts[0],
            "ucdb": ucdbs[0],
        })
    return out


def _vcover_exe() -> str:
    try:
        from config.settings import questa_exe
        exe = questa_exe("vcover.exe") or ""
    except Exception:                                  # noqa: BLE001 旁路
        return ""
    # `questa_exe` 可能返回"配置的路径"而非"存在的可执行文件"——不检查就会
    # 变成对每个 ucdb 各失败一次（实测 274 条错误、3.7 秒白跑）。
    return exe if exe and Path(exe).is_file() else ""


def _run_vcover(exe: str, ucdb: Path) -> str:
    proc = subprocess.run(
        [exe, "report", "-cvg", "-details", str(ucdb)],
        capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"vcover 退出码 {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout or '')[:200]}")
    return proc.stdout or ""


def _bins_from_report(text: str) -> List[Dict[str, Any]]:
    """`{cg: {cp: {bin: hits}}}` → 命中 bin 列表（hits>0 才算命中）。"""
    from src.layers.l3_decision.evidence.cvg_parse import _parse_cvg_bin_hits

    out: List[Dict[str, Any]] = []
    for cg, coverpoints in sorted((_parse_cvg_bin_hits(text) or {}).items()):
        for cp, bins in sorted((coverpoints or {}).items()):
            for name, hits in sorted((bins or {}).items()):
                if int(hits or 0) > 0:
                    out.append({"covergroup": cg, "coverpoint": cp,
                                "bin": name, "hits": int(hits)})
    return out


def collect_per_test_bins(root: str | Path, *, runner=None, write: bool = True,
                          limit: int = 0) -> Dict[str, Any]:
    """逐 test ucdb → `coverage/per_test_bins.json`。

    `runner(exe, ucdb)` 可注入（冒烟用）；默认跑 vcover。
    `limit>0` 时只处理前 N 个 ucdb，并在结果里**显式记录截断**。
    """
    root = Path(root)
    if not enabled():
        return {"available": False, "reason": f"{FLAG} 已关闭"}
    sources = find_per_test_ucdbs(root)
    if not sources:
        return {"available": False, "reason": "没有逐 test ucdb"}
    exe = _vcover_exe()
    if not exe:
        return {"available": False, "reason": "vcover 不可用",
                "ucdbs": len(sources)}
    runner = runner or _run_vcover
    truncated = max(0, len(sources) - limit) if limit > 0 else 0
    picked = sources[:limit] if limit > 0 else sources

    tests: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]] = {}
    per_seed: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]] = {}
    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for item in picked:
        ucdb = Path(item["ucdb"])
        try:
            bins = _bins_from_report(runner(exe, ucdb))
        except Exception as exc:                       # noqa: BLE001 单文件失败不拖垮
            errors.append({"test": item["test"],
                           "ucdb": ucdb.relative_to(root).as_posix(),
                           "error": f"{type(exc).__name__}: {exc}"})
            continue
        bucket = tests.setdefault(item["test"], {})
        seed_key = f"{item['test']}@{item['seed']}" if item["seed"] is not None \
            else item["test"]
        seed_bucket = per_seed.setdefault(seed_key, {})
        for row in bins:
            key = (row["coverpoint"], row["bin"])
            bucket[key] = {**row, "hits": max(bucket.get(key, {}).get("hits", 0),
                                             row["hits"])}
            seed_bucket[key] = row
        rows.append({"test": item["test"], "seed": item["seed"],
                     "ucdb": ucdb.relative_to(root).as_posix(),
                     "sha256": _sha(ucdb), "bins": len(bins)})

    def _flatten(group):
        return {name: [values[k] for k in sorted(values)]
                for name, values in sorted(group.items()) if values}

    doc = {
        "schema": SCHEMA,
        "tests": _flatten(tests),
        "per_seed": _flatten(per_seed),
        "sources": rows,
        "errors": errors,
        "truncated": truncated,
        "notes": ([] if not truncated else
                  [f"只处理了 {len(picked)}/{len(sources)} 个 ucdb（limit={limit}）"]),
    }
    if write and (doc["tests"] or errors):
        path = root / "coverage" / "per_test_bins.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    return {"available": bool(doc["tests"]), "tests": len(doc["tests"]),
            "bins": sum(len(v) for v in doc["tests"].values()),
            "ucdbs": len(picked), "errors": len(errors),
            "truncated": truncated, "path": "coverage/per_test_bins.json"}


__all__ = ["FLAG", "SCHEMA", "collect_per_test_bins", "enabled",
           "find_per_test_ucdbs"]
