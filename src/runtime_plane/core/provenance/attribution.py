"""bin → test → seed 的归因规则 —— **老实说清哪条是精确、哪条是推断**。

难点
    `coverage/tp_matrix.json` 是把**回归全量用例合并**后的覆盖率算出来的。
    合并报告只说「这个 bin 命中了」，不说「是哪条 test / 哪个 seed 命中的」。
    把合并结果直接算到某条 test 头上，正是「新测试碰巧没打中、却被记功」的
    根源。

所以这里分两种边：
    hit_by        exact  只有 per-test 覆盖率（sidecar）能证明
    attributed_by weak   只有合并报告时，按 round_manifest 的 TP→test 计划映射
                         —— 它表达的是「计划里这条 test 本该实现它」，不是
                         「它真的命中了」
MISS / UNOBSERVED / UNMAPPED 一律不建命中边：没命中说明不了任何归属。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.runtime_plane.core.provenance.schema import bin_node_id, seed_node_id, test_node_id, tp_node_id

#: tp_matrix 里算「命中」的状态。
HIT_STATUSES = {"HIT", "OBSERVED", "BACKDOOR_HIT"}
#: 这些状态不建命中边（但缺口会在 knowledge graph 里单独处理）。
MISS_STATUSES = {"MISS", "UNOBSERVED", "BACKDOOR_MISS", "UNMAPPED"}

_SEED_RE = re.compile(r"_seed_(\d+)")


def read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def sha256_file(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with Path(path).open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _strip_test_prefix(name: str) -> str:
    return name[5:] if name.startswith("test_") else name


def _base_test(name: str) -> str:
    """去掉 `_seed_<n>` 后缀 —— 回归目录按 seed 命名，test 名本身不带它。"""
    return _SEED_RE.sub("", _strip_test_prefix(name)).rstrip("_") or _strip_test_prefix(name)


def _bin_name(row: Dict[str, Any]) -> str:
    return bin_node_id(str(row.get("coverpoint") or ""), str(row.get("bin") or ""))


@dataclass
class Attribution:
    """一轮归因的确定性结果（不依赖时间）。"""

    tests: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tp_to_tests: Dict[str, Set[str]] = field(default_factory=dict)
    tp_bins: Dict[str, Set[str]] = field(default_factory=dict)
    bin_tests_exact: Dict[str, Set[str]] = field(default_factory=dict)
    bin_tests_weak: Dict[str, Set[str]] = field(default_factory=dict)
    unattributed_bins: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 读已有产物
# ═══════════════════════════════════════════════════════════════

def collect_test_dirs(root: Path) -> Dict[str, Dict[str, Any]]:
    """扫 `regression_run/**/test_*`：test 名、种子、日志哈希。

    种子只从目录名 `_seed_<n>` 取 —— 这是 ShellGenerator 已经写进盘的事实，
    不从 plusargs 猜。
    """
    out: Dict[str, Dict[str, Any]] = {}
    reg = root / "regression_run"
    if not reg.is_dir():
        return out
    for test_dir in reg.rglob("test_*"):
        if not test_dir.is_dir():
            continue
        raw = test_dir.name
        base = _base_test(raw)
        seeds = {int(n) for n in _SEED_RE.findall(raw)}
        entry = out.setdefault(base, {"seeds": set(), "dirs": [], "log_sha256": ""})
        entry["seeds"].update(seeds)
        entry["dirs"].append(test_dir.relative_to(root).as_posix())
        if not entry["log_sha256"]:
            for name in ("sim_vsim.log", "sim.log"):
                log = test_dir / name
                if log.is_file():
                    entry["log_sha256"] = sha256_file(log)
                    break
    return out


def read_per_test_bins(root: Path) -> Dict[str, Set[str]]:
    """读 per-test 覆盖率 sidecar —— 只有它能让 `hit_by` 成为 exact。

    支持 `<run>/coverage/per_test_bins.json`：
        {"schema": "per_test_bins_v1", "tests": {"alu_test": ["op.add", "op.sub"]}}
    也接受每条 bin 写成 {"coverpoint": "...", "bin": "..."}。
    """
    doc = read_json(root / "coverage" / "per_test_bins.json")
    tests = doc.get("tests")
    if not isinstance(tests, dict):
        return {}
    out: Dict[str, Set[str]] = {}
    for test, values in tests.items():
        bins: Set[str] = set()
        for value in values or []:
            if isinstance(value, dict):
                bins.add(bin_node_id(str(value.get("coverpoint") or ""),
                                     str(value.get("bin") or "")))
            elif isinstance(value, str):
                bins.add(value if value.startswith("bin:") else f"bin:{value}")
        if bins:
            out[str(test)] = bins
    return out


def collect_tp_maps(root: Path) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """从 round_manifest 与 testpoints 读 TP→test、TP→bin 两张映射。"""
    facts = read_json(root / "coverage" / "round_manifest.json")
    tp_to_tests: Dict[str, Set[str]] = {}
    for rnd in facts.get("rounds") or []:
        for fact in rnd.get("facts") or []:
            tp_id = str(fact.get("tp_id") or "")
            test = str(fact.get("test_name") or "")
            if tp_id and test:
                tp_to_tests.setdefault(tp_id, set()).add(_base_test(test))

    tps = read_json(root / "coverage" / "testpoints.json")
    tp_bins: Dict[str, Set[str]] = {}
    for tp in tps.get("testpoints") or []:
        if not isinstance(tp, dict):
            continue
        tp_id = str(tp.get("tp_id") or "")
        cp = str(tp.get("coverpoint") or "")
        bn = str(tp.get("bin") or "")
        if tp_id and (cp or bn):
            tp_bins.setdefault(tp_id, set()).add(bin_node_id(cp, bn))
    return tp_to_tests, tp_bins


def classify(root: str | Path) -> Attribution:
    """确定性归因。不跑 EDA；没有 per-test 数据就只给 weak 边。"""
    root = Path(root)
    result = Attribution()
    result.tests = collect_test_dirs(root)
    result.tp_to_tests, result.tp_bins = collect_tp_maps(root)
    exact = read_per_test_bins(root)
    exact_bins: Dict[str, Set[str]] = {}
    for test, bins in exact.items():
        for bin_id in bins:
            exact_bins.setdefault(bin_id, set()).add(test)

    # 把 round_manifest 里出现、盘上没有目录的 test 也建出来（证据可能被清理过）
    for tests in result.tp_to_tests.values():
        for test in tests:
            result.tests.setdefault(test, {"seeds": set(), "dirs": [], "log_sha256": ""})

    matrix = read_json(root / "coverage" / "tp_matrix.json")
    rows = [r for r in (matrix.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        result.notes.append("没有 coverage/tp_matrix.json 的 rows —— bin 归因不可用")
        return result

    for row in rows:
        status = str(row.get("status") or "")
        bin_id = _bin_name(row)
        if status in MISS_STATUSES or not status:
            continue
        tp_id = str(row.get("tp_id") or "")
        actual_tests = exact_bins.get(bin_id) or set()
        if actual_tests:
            result.bin_tests_exact.setdefault(bin_id, set()).update(actual_tests)
            continue
        planned = set(result.tp_to_tests.get(tp_id) or set())
        if planned:
            result.bin_tests_weak.setdefault(bin_id, set()).update(planned)
        else:
            if bin_id not in result.unattributed_bins:
                result.unattributed_bins.append(bin_id)

    if exact:
        result.notes.append(
            "存在 per-test 覆盖率 sidecar：命中的 bin 用 hit_by（exact）")
    else:
        result.notes.append(
            "没有 per-test 覆盖率（coverage/per_test_bins.json）："
            "bin→test 只能是 attributed_by（weak），不能把合并覆盖率的功劳"
            "算到某条 test 上")
    if result.unattributed_bins:
        result.notes.append(
            f"{len(result.unattributed_bins)} 个命中 bin 没有任何 TP→test 映射")
    return result
