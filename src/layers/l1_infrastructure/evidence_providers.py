"""EDA 证据源适配器 —— **工具不在就明确 unavailable，不伪造证据**。

芯华章的 Pillar 2 要求“工具为结论背书”。当前真正接通的只有
Simulation / Regression / Debug；Formal / Lint / CDC / RDC / Emulation
先落**显式占位**（dummy）：能读到产物就报 available，读不到就报
`available=False + reason`，字段与真实适配器一致，后续替换实现即可。

产物：`docs/evidence_sources.json`
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List

SCHEMA = "evidence_sources_v1"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _first(root: Path, patterns: List[str]) -> List[str]:
    hits: List[str] = []
    for pattern in patterns:
        hits.extend(str(p.relative_to(root).as_posix())
                    for p in root.glob(pattern) if p.is_file())
    return sorted(set(hits))[:20]


def _row(kind: str, *, available: bool, reason: str = "",
         artifacts: List[str] = None, metrics: Dict[str, Any] = None,
         dummy: bool = False) -> Dict[str, Any]:
    return {"evidence_kind": kind, "available": bool(available),
            "dummy": bool(dummy), "reason": reason,
            "artifacts": artifacts or [], "metrics": dict(metrics or {})}


def _simulation(root: Path) -> Dict[str, Any]:
    path = root / "sim" / "coverage" / "coverage_result.json"
    doc = _read_json(path)
    cov = doc.get("coverage") or {}
    if not path.is_file():
        return _row("sim_result", available=False, reason="没有 coverage_result.json")
    return _row("sim_result", available=True, artifacts=[path.name],
                metrics={"functional_pct": cov.get("functional_pct"),
                         "overall_pct": cov.get("overall_pct")})


def _regression(root: Path) -> Dict[str, Any]:
    paths = _first(root, ["regression_run/report.json",
                          "regression_run/**/report.json"])
    if not paths:
        return _row("regression_round", available=False,
                    reason="没有 regression report.json")
    tests = 0
    for rel in paths:
        doc = _read_json(root / rel)
        tests += int(doc.get("total") or doc.get("count") or 0)
    return _row("regression_round", available=True, artifacts=paths,
                metrics={"tests": tests, "reports": len(paths)})


def _debug(root: Path) -> Dict[str, Any]:
    logs = _first(root, ["regression_run/**/sim_vsim.log",
                         "regression_run/**/sim.log"])
    return (_row("waveform", available=True, artifacts=logs,
                 metrics={"logs": len(logs)}) if logs else
            _row("waveform", available=False, reason="没有逐 test 仿真日志"))


def _dummy(kind: str, reason: str,
           patterns: List[str] | None = None) -> Callable[[Path], Dict[str, Any]]:
    def _provider(root: Path) -> Dict[str, Any]:
        hits = _first(root, patterns or [])
        if hits:
            return _row(kind, available=True, artifacts=hits)
        return _row(kind, available=False, reason=reason, dummy=True)
    return _provider


PROVIDERS: List[Callable[[Path], Dict[str, Any]]] = [
    _simulation,
    _regression,
    _debug,
    _dummy("formal_proof", "形式验证引擎未接入（占位）",
           ["formal/**/*.json", "sim/formal/**/*.json"]),
    _dummy("lint_report", "Lint 未接入（占位）",
           ["docs/lint_report*", "reports/lint*"]),
    _dummy("cdc_report", "CDC 未接入（占位）",
           ["docs/cdc_report*", "reports/cdc*"]),
    _dummy("rdc_report", "RDC 未接入（占位）",
           ["docs/rdc_report*", "reports/rdc*"]),
    _dummy("emulation_run", "Emulation 未接入（占位）",
           ["emulation/**/*.json"]),
]


def collect_evidence_sources(root: str | Path) -> Dict[str, Any]:
    root = Path(root)
    rows = [provider(root) for provider in PROVIDERS]
    doc = {
        "schema": SCHEMA,
        "sources": rows,
        "available": [r["evidence_kind"] for r in rows if r["available"]],
        "unavailable": [r["evidence_kind"] for r in rows if not r["available"]],
        "dummy": [r["evidence_kind"] for r in rows if r["dummy"]],
        # Formal 目标指标：没接证明器时**显式 null**，不写 0 冒充“覆盖了”。
        "proof_core_coverage": None,
    }
    path = root / "docs" / "evidence_sources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return doc


__all__ = ["PROVIDERS", "SCHEMA", "collect_evidence_sources"]
