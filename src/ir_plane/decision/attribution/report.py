"""Attribution v2 落盘 —— per-test sidecar + EXACT/WEAK/UNKNOWN 读数。

    coverage/per_test_bins.json   （已有事实：test → bins）
                │
                ▼
    coverage/per_test_v2/*.json   （每条 test 的 sidecar v2）
                │
                ▼
    coverage/attribution_v2.json  （率 + 身份完整率 + 质量门读数）

**不替换** `coverage/attribution.json`：那是完整率报告，这里只补"归因等级"
这一层，让 EXACT/WEAK/UNKNOWN 有可引用的落盘事实。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .bin_identity import bin_identity, hit_fact
from .classify import LEVELS, quality_gate, rates
from .sidecar import build_sidecar, validate_sidecar

SCHEMA = "attribution_v2"
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _identity(root: Path) -> Dict[str, str]:
    manifest = _read_json(root / "docs" / "manifest.json")
    rtl_hash = str((manifest.get("rtl_version") or {}).get("content_hash") or "")
    plan = _read_json(root / "coverage" / "stimulus_plan.json")
    plan_hash = str(plan.get("sha256") or _sha(root / "coverage" / "stimulus_plan.json"))
    return {
        "rtl_hash": rtl_hash,
        "coverage_model_hash": _sha(root / "coverage" / "testpoints.json"),
        "stimulus_plan_hash": plan_hash,
    }


def _bin_of(value: Any) -> Tuple[str, str]:
    """sidecar/pins 条目 → (coverpoint, bin)。"""
    if isinstance(value, dict):
        return (str(value.get("coverpoint") or ""), str(value.get("bin") or ""))
    text = str(value or "")
    return ("", text[4:] if text.startswith("bin:") else text)


def _seeds_for(test: str, tests_info: Dict[str, Dict[str, Any]]) -> List[Any]:
    info = tests_info.get(test) or {}
    seeds = sorted(info.get("seeds") or [])
    return seeds or [None]


def _groups(doc: Dict[str, Any], tests_info: Dict[str, Dict[str, Any]]
            ) -> List[Tuple[str, Any, Any]]:
    """per_test_bins → [(test, seed, values)]；优先 `per_seed`（seed 精确）。"""
    per_seed = doc.get("per_seed")
    if isinstance(per_seed, dict) and per_seed:
        out = []
        for key, values in sorted(per_seed.items()):
            test, _, seed_text = str(key).partition("@")
            out.append((test or str(key),
                        int(seed_text) if seed_text.isdigit() else None, values))
        return out
    tests = doc.get("tests")
    if not isinstance(tests, dict):
        return []
    return [(str(test), seed, values)
            for test, values in sorted(tests.items())
            for seed in _seeds_for(str(test), tests_info)]


def _observed_bins(values: Any, identity: Dict[str, str], module: str
                   ) -> List[Dict[str, str]]:
    bins = []
    for value in values or []:
        cp, bn = _bin_of(value)
        if cp or bn:
            bins.append({"bin_id": bin_identity(identity["coverage_model_hash"],
                                                module, cp, bn),
                         "status": "HIT"})
    return bins


def _write_sidecar(root: Path, identity: Dict[str, str], test: str, seed: Any,
                   bins: List[Dict[str, str]]) -> Dict[str, Any]:
    sidecar = build_sidecar(
        run_id=root.name, test_id=str(test), seed=seed,
        rtl_hash=identity["rtl_hash"],
        coverage_model_hash=identity["coverage_model_hash"],
        stimulus_plan_hash=identity["stimulus_plan_hash"],
        observed_bins=bins)
    check = validate_sidecar(sidecar)
    path = (root / "coverage" / "per_test_v2" /
            f"{_SAFE.sub('_', f'{test}__seed_{seed}')}.json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    except OSError:
        check["errors"].append({"rule": "write_failed", "target": str(path),
                                "message": "sidecar 落盘失败"})
    return {"test_id": str(test), "seed": seed,
            "path": path.relative_to(root).as_posix(),
            "bins": len(bins), "ok": bool(check["ok"]),
            "identity_complete": bool(check["identity_complete"]),
            "errors": check["errors"]}


def _per_test_facts(root: Path, identity: Dict[str, str], module: str,
                    tests_info: Dict[str, Dict[str, Any]]
                    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """per-test bins → (hit 记录, sidecar 摘要)。无 sidecar 时返回空。"""
    doc = _read_json(root / "coverage" / "per_test_bins.json")
    records: List[Dict[str, Any]] = []
    sidecars: List[Dict[str, Any]] = []
    for test, seed, values in _groups(doc, tests_info):
        bins = _observed_bins(values, identity, module)
        if not bins:
            continue
        sidecars.append(_write_sidecar(root, identity, test, seed, bins))
        for item in bins:
            records.append(hit_fact(
                bin_id=item["bin_id"], run_id=root.name, test_id=str(test),
                seed=seed, stimulus_plan_hash=identity["stimulus_plan_hash"],
                rtl_hash=identity["rtl_hash"],
                coverage_model_hash=identity["coverage_model_hash"],
                attribution_level="EXACT"))
    return records, sidecars


def _bin_records(root: Path, covered: set) -> List[Dict[str, Any]]:
    """未出现在 per-test sidecar 的命中 bin → WEAK / UNKNOWN 记录。"""
    doc = _read_json(root / "coverage" / "attribution.json")
    bins = doc.get("bins")
    if not isinstance(bins, list):
        try:
            from src.runtime_plane.core.provenance.report import build_attribution_report
            bins = build_attribution_report(root).get("bins") or []
        except Exception:                              # noqa: BLE001 旁路
            bins = []
    records: List[Dict[str, Any]] = []
    for item in bins:
        if not isinstance(item, dict):
            continue
        bin_id = str(item.get("bin") or "")
        if not bin_id or bin_id in covered:
            continue
        confidence = str(item.get("confidence") or "").lower()
        level = {"exact": "EXACT", "weak": "WEAK"}.get(confidence, "UNKNOWN")
        records.append({"bin_id": bin_id, "tp_id": str(item.get("tp_id") or ""),
                        "attribution_level": level})
    return records


def build_attribution_v2(root: str | Path, *, module: str = "") -> Dict[str, Any]:
    root = Path(root)
    identity = _identity(root)
    doc = _read_json(root / "coverage" / "testpoints.json")
    module = module or str(doc.get("module") or "") or root.name
    try:
        from src.runtime_plane.core.provenance.attribution import collect_test_dirs
        tests_info = collect_test_dirs(root)
    except Exception:                                  # noqa: BLE001 旁路
        tests_info = {}
    exact_records, sidecars = _per_test_facts(root, identity, module, tests_info)
    covered = {str(r["bin_id"]) for r in exact_records}
    weak_records = _bin_records(root, covered)
    all_records = exact_records + weak_records
    rate = rates(all_records)
    # 身份完整率只看**带逐用例事实**的记录 —— weak 记录本来就没有身份链。
    identity_rate = rates(exact_records)["identity_completeness"] \
        if exact_records else 0.0
    quality = quality_gate({"identity_completeness": identity_rate,
                            "unknown_rate": rate["unknown_rate"]})
    return {
        "schema": SCHEMA,
        "run_id": root.name,
        "module": module,
        "identity": identity,
        "levels": list(LEVELS),
        "per_test_sidecars": sidecars,
        "rates": rate,
        "identity_completeness": identity_rate,
        "quality": quality,
        "notes": ([] if exact_records else
                  ["没有 per-test 覆盖率 sidecar：所有归因最高只到 WEAK"]),
    }


def write_attribution_v2(root: str | Path, *, module: str = ""
                         ) -> Dict[str, Any]:
    root = Path(root)
    report = build_attribution_v2(root, module=module)
    path = root / "coverage" / "attribution_v2.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    report["path"] = path.relative_to(root).as_posix()
    return report


__all__ = ["SCHEMA", "build_attribution_v2", "write_attribution_v2"]
