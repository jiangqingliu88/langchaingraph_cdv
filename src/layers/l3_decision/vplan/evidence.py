"""VPlan 证据索引与契约 gate。

只读 run 产物，不跑 EDA：

    <run>/contract/plan_link.yaml      C-* ↔ TP ↔ case
    <run>/coverage/tp_matrix.json      TP → HIT/OBSERVED/UNMAPPED...
    <run>/regression_stages.json       分级回归 PASS/FAIL
    <run>/sv/asset_registry.csv        生成资产（package-assets 产物）

契约从 `assume` 到 `active` 的条件（全部满足）：

1. run 已链接，且 `regression_stages.json` 为 PASS；
2. 契约映射到的 TP 全部 HIT / OBSERVED / BACKDOOR_HIT；
3. `sv/asset_registry.csv` 里至少有一个资产声明了该 C-*。

缺任何一条都保持 `assume`。`--apply` 只把满足条件的行改成 `active`；
不会自动 `exempt`，也不会因为“只改 CSV”而升级。
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

INDEX_SCHEMA = "vplan_evidence_index_v1"
HIT_STATES = {"HIT", "OBSERVED", "BACKDOOR_HIT"}


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_link(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / "contract" / "plan_link.yaml"
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_tp_status(run_dir: Path) -> Dict[str, str]:
    doc = _read_json(run_dir / "coverage" / "tp_matrix.json")
    out: Dict[str, str] = {}
    for row in doc.get("rows") or []:
        if isinstance(row, dict) and row.get("tp_id"):
            out[str(row["tp_id"])] = str(row.get("status") or "UNKNOWN")
    return out


def _read_case_tp_status(run_dir: Path) -> Dict[str, Dict[str, str]]:
    """`case_id → {tp_id: status}` —— VPlan TP 与生成 TP 不同名时的桥。"""
    doc = _read_json(run_dir / "coverage" / "tp_matrix.json")
    out: Dict[str, Dict[str, str]] = {}
    for row in doc.get("rows") or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("case_id") or "")
        tp_id = str(row.get("tp_id") or "")
        if cid and tp_id:
            out.setdefault(cid, {})[tp_id] = str(row.get("status") or "UNKNOWN")
    return out


def _regression_status(run_dir: Path) -> str:
    doc = _read_json(run_dir / "regression_stages.json")
    return str(doc.get("status") or "UNKNOWN")


def _sv_contracts(run_dir: Path) -> set[str]:
    path = run_dir / "sv" / "asset_registry.csv"
    out: set[str] = set()
    if not path.is_file():
        return out
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            for cid in (row.get("contract_ids") or "").split("|"):
                if cid.strip():
                    out.add(cid.strip())
    return out


def _case_contracts(run_dir: Path) -> set[str]:
    """Case IR 里声明了 sva/scb 的契约 —— 内核生成的环境覆盖了这些检查。"""
    out: set[str] = set()
    doc = _read_json(run_dir / "coverage" / "case_ir.json")
    for case in doc.get("cases") or []:
        if not isinstance(case, dict):
            continue
        if case.get("sva") or case.get("scb"):
            out.update(str(c) for c in (case.get("feats") or []) if c)
    return out


def build_entry(run_dir: str | Path) -> Dict[str, Any]:
    """run 目录 → 证据索引条目（缺什么如实留空）。"""
    root = Path(run_dir).resolve()
    link = _read_link(root)
    contracts = []
    for row in link.get("contracts") or []:
        if not isinstance(row, dict):
            continue
        contracts.append({
            "contract_id": str(row.get("contract_id") or ""),
            "tp_ids": [str(t) for t in (row.get("tp_ids") or []) if t],
            "case_ids": [str(c) for c in (row.get("case_ids") or []) if c],
            "matrix_status": str(row.get("status") or ""),
        })
    return {
        "run_id": root.name,
        "run_dir": str(root),
        "spec_hash": str(link.get("spec_hash") or ""),
        "module": str(link.get("module") or ""),
        "contracts": contracts,
        "regression_status": _regression_status(root),
        "tp_status": _read_tp_status(root),
        "case_tp_status": _read_case_tp_status(root),
        "sv_contracts": sorted(
            _sv_contracts(root)
            | (_case_contracts(root) if (root / "sv").is_dir() else set())),
        "sha256": {
            name: _sha256(root / rel)
            for name, rel in (
                ("contract_manifest", "contract/contract_manifest.json"),
                ("regression_stages", "regression_stages.json"),
                ("tp_matrix", "coverage/tp_matrix.json"),
                ("sv_registry", "sv/asset_registry.csv"),
            )
        },
    }


def index_path(project_root: str | Path) -> Path:
    return Path(project_root) / "evidence" / "index.json"


def load_index(project_root: str | Path) -> Dict[str, Any]:
    doc = _read_json(index_path(project_root))
    if doc.get("schema") != INDEX_SCHEMA:
        return {"schema": INDEX_SCHEMA, "module": "", "entries": []}
    return doc


def link_run(project_root: str | Path, run_dir: str | Path) -> Dict[str, Any]:
    """把一个 run 记进项目证据索引（同 run_id 覆盖旧条目）。"""
    project = Path(project_root)
    entry = build_entry(run_dir)
    try:
        entry["run_dir"] = str(Path(entry["run_dir"]).relative_to(project.parent))
    except ValueError:
        pass
    index = load_index(project)
    entries = [e for e in index.get("entries") or []
               if e.get("run_id") != entry["run_id"]]
    entries.append(entry)
    index = {
        "schema": INDEX_SCHEMA,
        "module": project.name,
        "entries": entries,
    }
    target = index_path(project)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    run_copy = target.parent / "runs" / f"{entry['run_id']}.json"
    run_copy.parent.mkdir(parents=True, exist_ok=True)
    run_copy.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return entry


def _matrix_rows(project_root: Path) -> List[Tuple[Path, Dict[str, str]]]:
    rows: List[Tuple[Path, Dict[str, str]]] = []
    for path in sorted((project_root / "data" / "contract_matrix").glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("contract_id"):
                    rows.append((path, dict(row)))
    return rows


def _resolve_tp_status(entry: Dict[str, Any],
                       mapping: Dict[str, Any]) -> Tuple[List[str], Dict[str, str]]:
    """VPlan TP ID 与 kernel 生成的 TP ID 不是同一套：找不到就按 case 聚合。"""
    tp_ids = [str(t) for t in (mapping.get("tp_ids") or []) if t]
    case_ids = [str(c) for c in (mapping.get("case_ids") or []) if c]
    tp_status = entry.get("tp_status") or {}
    if any(t in tp_status for t in tp_ids):
        return tp_ids, tp_status
    aggregated: Dict[str, str] = {}
    for case_id in case_ids:
        aggregated.update((entry.get("case_tp_status") or {}).get(case_id) or {})
    return (list(aggregated), aggregated) if aggregated else (tp_ids, tp_status)


def _contract_reasons(entry: Dict[str, Any], cid: str,
                      tp_ids: List[str], tp_status: Dict[str, str]
                      ) -> List[str]:
    reasons: List[str] = []
    if not tp_ids:
        reasons.append("plan_link has no tp_ids and case has no run TPs")
    if entry.get("regression_status") != "PASS":
        reasons.append(f"regression={entry.get('regression_status')}")
    missing = [t for t in tp_ids if tp_status.get(t) not in HIT_STATES]
    if missing:
        reasons.append("TP not hit: " + ", ".join(missing[:5]))
    if cid not in set(entry.get("sv_contracts") or []):
        reasons.append("no sv/ asset declares this contract")
    return reasons


def _evaluate_contract(cid: str, status: str,
                       candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candidates:
        reasons = ["no linked run maps this contract"]
    else:
        entry = candidates[-1]
        mapping = next((c for c in entry.get("contracts") or []
                        if c.get("contract_id") == cid), {})
        tp_ids, tp_status = _resolve_tp_status(entry, mapping)
        reasons = _contract_reasons(entry, cid, tp_ids, tp_status)
    return {
        "contract_id": cid,
        "status": status,
        "eligible_active": not reasons,
        "reasons": reasons,
        "run_id": (candidates[-1].get("run_id") if candidates else ""),
    }


def evaluate(project_root: str | Path) -> List[Dict[str, Any]]:
    """每个契约 → {contract_id, status, eligible, reasons}。"""
    project = Path(project_root)
    entries = list(load_index(project).get("entries") or [])
    by_contract: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        for row in entry.get("contracts") or []:
            cid = str(row.get("contract_id") or "")
            if cid:
                by_contract.setdefault(cid, []).append(entry)

    return [
        _evaluate_contract(row["contract_id"],
                           str(row.get("status") or "assume"),
                           by_contract.get(row["contract_id"]) or [])
        for _path, row in _matrix_rows(project)
    ]


def apply_active(project_root: str | Path,
                 results: Iterable[Dict[str, Any]]) -> int:
    """只把 eligible 且尚未 active 的行改成 active；返回改动条数。"""
    project = Path(project_root)
    eligible = {r["contract_id"] for r in results
                if r["eligible_active"] and r["status"] != "active"}
    if not eligible:
        return 0
    run_of = {r["contract_id"]: r.get("run_id", "") for r in results}
    changed = 0
    for path in sorted((project / "data" / "contract_matrix").glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            rows = [dict(r) for r in reader]
        touched = False
        for row in rows:
            cid = row.get("contract_id")
            if cid in eligible and row.get("status") != "active":
                row["status"] = "active"
                run_id = run_of.get(cid or "", "")
                note = f"gate: active from {run_id}" if run_id else "gate: active from evidence"
                row["remark"] = (row.get("remark") or "").strip()
                row["remark"] = (row["remark"] + " | " + note).strip(" |")
                touched = True
                changed += 1
        if touched:
            with path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
    return changed
