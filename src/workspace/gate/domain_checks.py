"""Gate 领域检查 —— 消费 EDA 证据包，而不是模型自述。"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List

from ..proposal.schema import Proposal
from ..zones import WorkspaceZones


def _row(name: str, status: str, detail: str = "", severity: str = "block",
         **extra: Any) -> Dict[str, Any]:
    return {"name": name, "status": status, "severity": severity,
            "detail": detail, **extra}


def _hashes_ok(latest: Dict[str, Any]) -> List[str]:
    run_dir = Path(str(latest.get("run_dir") or ""))
    hashes = latest.get("hashes") or {}
    errors = []
    for rel, sha in hashes.items():
        path = run_dir / rel
        if not path.is_file():
            errors.append(f"{rel}: 文件不存在")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != sha:
            errors.append(f"{rel}: sha256 变了")
    if not hashes:
        errors.append("没有证据文件哈希")
    return errors


def _regression_rows(latest: Dict[str, Any]) -> List[Dict[str, Any]]:
    regression = latest.get("regression") or {}
    failed = int(regression.get("failed") or 0)
    passed = (str(regression.get("status") or "").upper() == "PASS"
              and failed == 0 and bool(regression.get("stages")))
    return [_row("eda_regression", "pass" if passed else "fail",
                 f"status={regression.get('status')} failed={failed}")]


def _coverage_rows(latest: Dict[str, Any], eda: Dict[str, Any]) -> List[Dict[str, Any]]:
    coverage = latest.get("coverage") or {}
    actual = float(coverage.get("functional_pct") or 0.0)
    target = float(eda.get("target") or latest.get("target") or 0.0)
    if target <= 0:
        return [_row("eda_coverage", "warn",
                     f"functional={actual:.2f}% 但未声明 target",
                     severity="warn", human=True)]
    met = actual >= target
    return [_row("eda_coverage", "pass" if met else "fail",
                 f"functional={actual:.2f}% target={target:.2f}%",
                 actual=actual, target=target)]


def _file_rows(latest: Dict[str, Any], zones: WorkspaceZones) -> List[Dict[str, Any]]:
    errors = _hashes_ok(latest)
    rows = [_row("eda_evidence_files", "fail" if errors else "pass",
                 "; ".join(errors) if errors else
                 f"{len(latest.get('hashes') or {})} 份证据哈希匹配")]
    run_dir = Path(str(latest.get("run_dir") or ""))
    try:
        run_dir.resolve().relative_to(zones.staging.resolve())
    except (ValueError, OSError):
        rows.append(_row("eda_evidence_location", "warn",
                         "证据不在 staging/ 下（仍是只读证据，建议 sandbox 内产出）",
                         severity="warn", human=True))
    return rows


def _contract_rows(latest: Dict[str, Any]) -> List[Dict[str, Any]]:
    contracts = latest.get("contracts") or {}
    if int(contracts.get("obligations") or 0) == 0:
        return [_row("eda_contracts", "warn",
                     "证据包里没有契约义务计数（只看回归/覆盖率）",
                     severity="warn", human=True)]
    return [_row("eda_contracts", "pass",
                 f"obligations={contracts.get('obligations')}")]


def eda_evidence(proposal: Proposal, zones: WorkspaceZones) -> List[Dict[str, Any]]:
    """`workspace gate --profile eda` 的默认领域检查。"""
    eda = (proposal.evidence or {}).get("eda") or {}
    latest = eda.get("after") or eda.get("latest") or {}
    if not latest:
        return [_row("eda_evidence", "fail",
                     "没有 EDA 证据（先 run_verify/collect_evidence，或 propose --eda-run）")]
    rows: List[Dict[str, Any]] = []
    rows.extend(_regression_rows(latest))
    rows.extend(_coverage_rows(latest, eda))
    rows.extend(_file_rows(latest, zones))
    rows.extend(_contract_rows(latest))
    return rows
