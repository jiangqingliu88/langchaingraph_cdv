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

VPlan 契约（`C-*`）还可以通过**环境契约**取证：run 的
`contract/vplan_map.json` 把 C-* 映射到 CASEMODEL 义务（OBL-*），义务状态
由 `contract/obligations.json` + `evidence/ledger.jsonl` 用
`contract.derive` 推导。有映射时以环境契约为准 —— 映射到的义务全部
`PROVEN` / `NOT_APPLICABLE`、回归 PASS、且有 sv 资产声明该 C-*，才 eligible。
没有映射的 run 继续走上面的 TP/case 口径（向后兼容）。

缺任何一条都保持 `assume`。`--apply` 只把满足条件的行改成 `active`；
不会自动 `exempt`，也不会因为“只改 CSV”而升级。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

from src.runtime_plane.core.runtime.atomic import atomic_write_text

INDEX_SCHEMA = "vplan_evidence_index_v1"
HIT_STATES = {"HIT", "OBSERVED", "BACKDOOR_HIT"}
#: 义务清偿状态里"算过关"的两种（与 contract.derive 的词汇一致）。
CLEARED_STATES = {"PROVEN", "NOT_APPLICABLE"}


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_list(path: Path) -> List[Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return []
    return doc if isinstance(doc, list) else []


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


def _sva_assets(run_dir: Path) -> List[Dict[str, Any]]:
    """`sv/asset_registry.csv` 里的 SVA 资产（kind=sva）及其契约。"""
    path = run_dir / "sv" / "asset_registry.csv"
    out: List[Dict[str, Any]] = []
    if not path.is_file():
        return out
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("kind") or "").lower() != "sva":
                continue
            out.append({
                "artifact": str(row.get("artifact") or ""),
                "path": str(row.get("path") or ""),
                "contract_ids": [c.strip() for c in
                                 str(row.get("contract_ids") or "").split("|")
                                 if c.strip()],
            })
    return out


def _in_filelist(run_dir: Path, asset_path: str) -> bool:
    """SVA 是否真的进了编译清单（不是只躺在 sv/ 目录里）。

    `inputs/filelists/` 在 run 结束后会被清理；`sv/vc/{hdl,hvl}_files.f` 是
    package-assets 持久化的同一份清单，两个都查。
    """
    name = Path(asset_path).name
    if not name:
        return False
    candidates = list((run_dir / "inputs" / "filelists").glob("*.f"))
    candidates.extend((run_dir / "sv" / "vc").glob("*.f"))
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if name in text.replace("\\", "/"):
            return True
    return False


def _sva_module(run_dir: Path, asset_path: str) -> str:
    """从 SVA 资产里读出 `module <name>`。"""
    try:
        text = (run_dir / asset_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = re.search(r"\bmodule\s+([A-Za-z_]\w*)", text)
    return match.group(1) if match else ""


def _sva_elaborated(run_dir: Path, asset_path: str) -> bool:
    """SVA module 是否真的进了编译出的 work 库（不是只生成了文件）。"""
    module = _sva_module(run_dir, asset_path)
    if not module:
        return False
    for info in (run_dir / "regression_run").rglob("work/_info"):
        try:
            text = info.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if module in text:
            return True
    return False


def _sva_reasons(entry: Dict[str, Any], cid: str) -> List[str]:
    """接口/SVA 契约的判据：回归 PASS + 有声明该 C-* 的 SVA 资产 + 进了清单 + 已 elaborate。"""
    reasons: List[str] = []
    run_dir = Path(entry.get("run_dir") or ".")
    if entry.get("regression_status") != "PASS":
        reasons.append(f"regression={entry.get('regression_status')}")
    assets = [a for a in (entry.get("sva_assets") or [])
              if cid in (a.get("contract_ids") or [])]
    if not assets:
        reasons.append("no SVA asset declares this contract")
        return reasons
    usable = [a for a in assets if _in_filelist(run_dir, a.get("path") or "")]
    if not usable:
        reasons.append("SVA asset not in compile filelist")
    elif not any(_sva_elaborated(run_dir, a.get("path") or "") for a in usable):
        reasons.append("SVA module not elaborated in compiled work library")
    return reasons


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


def _vplan_obligations(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    """`vplan_map.json` + 义务 + 账本 → 每个 C-* 的环境义务状态。

    映射由 `contract/build.py` 在编译契约时写盘；义务状态用
    `contract.derive`（唯一判定实现）从账本事实推导。老 run 没有映射
    → 返回空，调用方回退到 TP/case 口径。
    """
    doc = _read_json(run_dir / "contract" / "vplan_map.json")
    contracts = doc.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        return {}
    # 局部导入：没有映射时不必背 pydantic 契约模型。
    from src.ir_plane.contract import Obligation, derive, read_ledger

    obligations = []
    for row in _read_list(run_dir / "contract" / "obligations.json"):
        try:
            obligations.append(Obligation(**row))
        except Exception:                  # noqa: BLE001 坏行不能让 gate 挂掉
            continue
    statuses = derive(obligations, read_ledger(run_dir)) if obligations else {}

    out: Dict[str, Dict[str, Any]] = {}
    for cid, slot in contracts.items():
        if not isinstance(slot, dict):
            continue
        oids = [str(o) for o in slot.get("obligations") or [] if o]
        per = {oid: str(statuses.get(oid, "MISSING")) for oid in oids}
        out[str(cid)] = {
            "cases": [str(c) for c in slot.get("cases") or [] if c],
            "artifacts": [str(a) for a in slot.get("artifacts") or [] if a],
            "obligations": per,
            "blocking": sorted({st for st in per.values()
                                if st not in CLEARED_STATES}),
        }
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
        "sva_assets": _sva_assets(root),
        "vplan_contracts": _vplan_obligations(root),
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
    """把一个 run 记进项目证据索引（同 run_id 覆盖旧条目）。

    顺手为老 run 补写 `contract/vplan_map.json`（确定性投影）：这样在
    mapping 上线之前跑出来的 run 也能按环境契约义务评估，不必重跑 EDA。
    """
    project = Path(project_root)
    try:
        from src.ir_plane.contract.build import ensure_vplan_map

        ensure_vplan_map(run_dir)
    except Exception:                      # noqa: BLE001 补映射失败不阻断 link
        pass
    entry = build_entry(run_dir)
    # 显式记录链接时间：gate 选 run 时不能依赖“目录里 append 的顺序”，
    # 否则“补 link 一个旧 run”会把旧证据顶到最新。
    entry["linked_at"] = datetime.now(timezone.utc).isoformat(
        timespec="microseconds")
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


def _vplan_reasons(entry: Dict[str, Any], cid: str) -> Optional[List[str]]:
    """有 VPlan→环境契约映射 → 用义务状态判；没有映射返回 `None`。"""
    vplan = (entry.get("vplan_contracts") or {}).get(cid)
    if not vplan:
        return None
    reasons: List[str] = []
    per = vplan.get("obligations") or {}
    if not per:
        reasons.append("vplan map has no environment obligations")
    blocking = [f"{oid}={st}" for oid, st in per.items()
                if st not in CLEARED_STATES]
    if blocking:
        reasons.append("obligation not proven: " + ", ".join(blocking[:5]))
    if entry.get("regression_status") != "PASS":
        reasons.append(f"regression={entry.get('regression_status')}")
    if cid not in set(entry.get("sv_contracts") or []):
        reasons.append("no sv/ asset declares this contract")
    return reasons


def _latest(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """按 `linked_at` 取最新；老索引没有时间戳时退回 append 顺序。"""
    if not candidates:
        return {}
    return max(
        candidates,
        key=lambda e: (str(e.get("linked_at") or ""), str(e.get("run_id") or "")),
    )


def _evaluate_contract(cid: str, status: str,
                       candidates: List[Dict[str, Any]],
                       row: Dict[str, Any] | None = None) -> Dict[str, Any]:
    entry = _latest(candidates)
    row = row or {}
    reasons: List[str]
    via = "none"
    if not candidates:
        reasons = ["no linked run maps this contract"]
    elif str(row.get("class") or "").lower() == "if":
        # 接口契约由 SVA/checker 取证，不是 case 覆盖点义务：
        # 回归 PASS + 声明该 C-* 的 SVA 资产 + 进了编译清单。
        reasons, via = _sva_reasons(entry, cid), "sva"
    else:
        mapping = next((c for c in entry.get("contracts") or []
                        if c.get("contract_id") == cid), {})
        mapped = _vplan_reasons(entry, cid)
        if mapped is not None:
            reasons, via = mapped, "vplan_obligations"
        else:
            tp_ids, tp_status = _resolve_tp_status(entry, mapping)
            reasons, via = _contract_reasons(entry, cid, tp_ids, tp_status), "tp"
    return {
        "contract_id": cid,
        "status": status,
        "eligible_active": not reasons,
        # active 是“曾经证明过”，不是“永远有效”。最新 run 对不上时单独标出，
        # 供 gate 漂移报告/CI 使用；不自动降级（降级是人的决定）。
        "active_drift": status == "active" and bool(reasons),
        "reasons": reasons,
        "run_id": entry.get("run_id", "") if candidates else "",
        "via": via,
    }


def evaluate(project_root: str | Path) -> List[Dict[str, Any]]:
    """每个契约 → {contract_id, status, eligible, reasons}。"""
    project = Path(project_root)
    entries = list(load_index(project).get("entries") or [])
    by_contract: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        # plan_link 与 vplan_map 都是"C-* 属于哪个 run"的来源；取并集，
        # 同一个 run 不重复登记。
        cids = {str(row.get("contract_id") or "")
                for row in entry.get("contracts") or []}
        cids |= set(entry.get("vplan_contracts") or {})
        for cid in cids:
            if cid:
                by_contract.setdefault(cid, []).append(entry)

    return [
        _evaluate_contract(row["contract_id"],
                           str(row.get("status") or "assume"),
                           by_contract.get(row["contract_id"]) or [],
                           row)
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
            # 先留一份原矩阵副本：gate --apply 是唯一改权威 CSV 的入口，
            # 出错时至少能人工回滚；备份不参与 gate 读取。
            backup = path.parent / ".backup" / path.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file():
                shutil.copy2(path, backup)
            buf = io.StringIO(newline="")
            writer = csv.DictWriter(buf, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            atomic_write_text(path, buf.getvalue(), newline="")
    return changed
