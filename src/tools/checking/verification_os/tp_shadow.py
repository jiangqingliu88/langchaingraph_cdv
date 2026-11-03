"""M2 第一步（影子）：**TP 级**状态也由「事实 + 推导」算出来。

M0 的影子只对账到 case 级（组 / SVA / SCB）。TP 级（`tp_matrix` 的
HIT / MISS / OBSERVED / BACKDOOR_HIT / UNMAPPED）仍然是 `collect_real_coverage`
自己算的 —— 第一步先把它也推导一遍，与旧结果逐条对账，仍然不改判定。

两个事实来源：

    run 级 bin_hit   来自 `sim/coverage/reports/coverage_cvg.txt`（**合并库**，
                     所有 test 合起来的命中）—— 批次级 test 没有 case 身份，
                     但它们的命中必须算进 TP 的度量，否则 TP 状态会缺一块。
    tp_attr          来自 `coverage/testpoints.yaml`（kind / observe_only / stage /
                     coverpoint 与 proof obligation）

判定规则与 `collect_real_coverage._status_for` 同口径：
    n is None → UNMAPPED（报告里没这一格）
    n > 0     → HIT / OBSERVED / BACKDOOR_HIT
    n == 0    → MISS / UNOBSERVED / BACKDOOR_MISS
    behavior  → PENDING_BACKEND（没有执行数据，不进覆盖率分母）
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .contract_model import Fact, FactBundle

SCHEMA = "os_tp_shadow_v1"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_testpoints(run_dir: Path) -> List[Dict[str, Any]]:
    path = run_dir / "coverage" / "testpoints.yaml"
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, ValueError):
        return []
    tps = doc.get("testpoints") if isinstance(doc, dict) else None
    return [t for t in tps or [] if isinstance(t, dict)]


def _owned(tp: Dict[str, Any]) -> List[str]:
    bins = tp.get("bins")
    out = [str(b) for b in bins if str(b)] if isinstance(bins, list) else []
    if not out and tp.get("bin"):
        out = [str(tp["bin"])]
    return out


def _kind(tp: Dict[str, Any]) -> str:
    kind = str((tp.get("realization") or {}).get("kind") or "")
    if kind:
        return kind
    return "observe" if tp.get("observe_only") else "stimulus"


def _stage(tp: Dict[str, Any]) -> str:
    return str((tp.get("execution") or {}).get("stage") or "")


def _report_path(run_dir: Path,
                 coverage: Optional[Dict[str, Any]] = None) -> Optional[Path]:
    """**与 `_tp_matrix` 同源**：优先计划合并报告（`tp_report`），否则单测报告。

    两边读不同报告 = 对账时全是假差异（合并库和单测库的命中数不一样）。

    `coverage` 由调用方**当场**传入时优先用它：证据流水线跑在
    `coverage_result.json` 落盘**之前**，那里读文件会读到上一轮的旧路径
    （实测导致 20 条假差异）。
    """
    coverage = coverage or (_read_json(
        run_dir / "sim" / "coverage" / "coverage_result.json").get("coverage") or {})
    tp_report = str(coverage.get("tp_report") or "")
    if tp_report:
        path = Path(tp_report)
        if path.is_file():
            return path
    fallback = (Path(str(coverage.get("report_dir") or ""))
                / "coverage_cvg.txt") if coverage.get("report_dir") else None
    if fallback and fallback.is_file():
        return fallback
    single = run_dir / "sim" / "coverage" / "reports" / "coverage_cvg.txt"
    return single if single.is_file() else None


def run_facts(run_dir: Path,
              coverage: Optional[Dict[str, Any]] = None) -> Optional[FactBundle]:
    """合并覆盖率报告 → run 级 `bin_hit` 事实（subject 不带 case）。"""
    report = _report_path(run_dir, coverage)
    if report is None:
        return None
    try:
        from src.tools.common.lib.collect_real_coverage import _parse_cvg_bin_hits

        hits = _parse_cvg_bin_hits(report.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, ImportError):
        return None
    facts: List[Fact] = []
    for cg, coverpoints in sorted((hits or {}).items()):
        for cp, bins in sorted((coverpoints or {}).items()):
            for name, n in sorted((bins or {}).items()):
                facts.append(Fact(type="bin_hit", contract_hash="", run_id=run_dir.name,
                                  subject={"case": "", "cp": cp, "bin": name,
                                           "cg": cg},
                                  value={"hits": int(n or 0)},
                                  producer="coverage.collector@v3"))
    bundle = FactBundle(bundle_id="B-run", run_id=run_dir.name, facts=facts)
    bundle.bundle_id = f"B-run-{bundle.digest()[:16]}"
    return bundle


def attr_facts(testpoints: List[Dict[str, Any]]) -> List[Fact]:
    """TP 的静态属性（kind / stage / obligation）—— 判 TP 状态要用。"""
    facts: List[Fact] = []
    for tp in testpoints:
        facts.append(Fact(
            type="tp_attr", contract_hash="",
            subject={"tp": str(tp.get("tp_id") or ""),
                     "cp": str(tp.get("coverpoint") or ""),
                     "bins": _owned(tp)},
            value={"kind": _kind(tp), "stage": _stage(tp),
                   "observe_only": bool(tp.get("observe_only"))},
            producer="contract.compiler@v3"))
    return facts


def attr_bundle(run_dir: Path) -> Optional[FactBundle]:
    """TP 静态属性 → 一包事实（账本里用于判 TP 状态）。"""
    testpoints = _read_testpoints(run_dir)
    if not testpoints:
        return None
    bundle = FactBundle(bundle_id="B-tp-attr", run_id=run_dir.name,
                        facts=attr_facts(testpoints))
    bundle.bundle_id = f"B-tp-attr-{bundle.digest()[:16]}"
    return bundle


def _hit_index(ledger: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, int]]]:
    """`{cg: {cp: {bin: hits}}}`（run 级事实）。"""
    out: Dict[str, Dict[str, Dict[str, int]]] = {}
    for fact in ledger:
        if str(getattr(fact.get("type"), "value", fact.get("type"))) != "bin_hit":
            continue
        subject = fact.get("subject") or {}
        if subject.get("case"):
            continue                      # 只取 run 级（case 级是逐执行切片）
        cg = str(subject.get("cg") or "")
        cp = str(subject.get("cp") or "")
        b = str(subject.get("bin") or "")
        out.setdefault(cg, {}).setdefault(cp, {})[b] = int(
            (fact.get("value") or {}).get("hits") or 0)
    return out


def _lookup(hits: Dict[str, Dict[str, Dict[str, int]]],
            cp: str, bin_name: str) -> Optional[int]:
    order = sorted(hits, key=lambda g: (not g.startswith("cg_dut"), g))
    for cg in order:
        value = (hits[cg].get(cp) or {}).get(bin_name)
        if value is not None:
            return value
    return None


def _status(n: Optional[int], kind: str, observe: bool) -> str:
    if n is None:
        return "UNMAPPED"
    if kind == "backdoor":
        return "BACKDOOR_HIT" if n > 0 else "BACKDOOR_MISS"
    if n > 0:
        return "OBSERVED" if observe else "HIT"
    return "UNOBSERVED" if observe else "MISS"


def status_for_hits(n: Optional[int], kind: str, observe: bool) -> tuple:
    """**唯一的 TP 状态判据**：`(status, 归一命中数, 是否后门)`。

    `collect_real_coverage._status_for` 现在直接委托到这里 —— M2 的"状态只推导"
    从 TP 级开始落地（先换实现，字段与产物形状不变）。
    """
    return _status(n, kind, observe), (0 if n is None else int(n)), kind == "backdoor"


def derive_tp_status(testpoints: List[Dict[str, Any]],
                     ledger: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """TP → `{status, hits, bins}`（与 `_tp_matrix` 同口径）。"""
    hits = _hit_index(ledger)
    out: Dict[str, Dict[str, Any]] = {}
    for tp in testpoints:
        tid = str(tp.get("tp_id") or "")
        if not tid:
            continue
        if _stage(tp) == "behavior":
            out[tid] = {"status": "PENDING_BACKEND", "hits": 0, "bins": _owned(tp)}
            continue
        cp = str(tp.get("coverpoint") or "")
        owned = _owned(tp)
        counts = {b: _lookup(hits, cp, b) for b in owned}
        values = [v for v in counts.values() if v is not None]
        n = max(values) if values else (0 if not owned else None)
        out[tid] = {"status": _status(n, _kind(tp), bool(tp.get("observe_only"))),
                    "hits": 0 if n is None else int(n), "bins": owned}
    return out


def run_tp_shadow(run_dir: str | Path, *, write: bool = True,
                  coverage: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """TP 级影子对账：推导 vs `tp_matrix.rows[]`。

    `coverage` 由当场调用方传入（证据流水线里 `coverage_result.json` 还没落盘）。
    """
    root = Path(run_dir)
    matrix = _read_json(root / "coverage" / "tp_matrix.json")
    rows = {str(r.get("tp_id") or ""): r for r in matrix.get("rows") or []
            if isinstance(r, dict)}
    testpoints = _read_testpoints(root)
    if not testpoints or not rows:
        return {"schema": SCHEMA, "available": False,
                "note": "没有 TP IR 或 tp_matrix（先跑一轮覆盖率）"}

    bundle = run_facts(root, coverage)
    ledger = [f.model_dump(by_alias=True) for f in (bundle.facts if bundle else [])]
    derived = derive_tp_status(testpoints, ledger)

    diffs: List[Dict[str, Any]] = []
    for tid, row in rows.items():
        want = str(row.get("status") or "")
        got = (derived.get(tid) or {}).get("status", "")
        if want != got:
            diffs.append({"tp_id": tid, "expected": want, "derived": got,
                          "cp": row.get("coverpoint"), "bin": row.get("bin")})
    report = {
        "schema": SCHEMA,
        "available": True,
        "tps": len(rows),
        "facts": len(ledger),
        "mismatched": len(diffs),
        "diffs": diffs[:50],
        "ok": not diffs,
        "scope": "TP 级（HIT/MISS/OBSERVED/BACKDOOR/UNMAPPED/PENDING_BACKEND）",
    }
    if write:
        path = root / "status" / "tp_shadow.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    return report


__all__ = ["SCHEMA", "attr_bundle", "attr_facts", "derive_tp_status",
           "run_facts", "run_tp_shadow"]
