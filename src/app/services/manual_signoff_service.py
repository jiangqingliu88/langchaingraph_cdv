"""人工签核 —— 逐用例签核 + TB/RTL 封存（桌面工作台用）。

    coverage/case_ir.json          用例清单（契约身份）
    coverage/case_cov/**/*.json    逐用例证据状态（只读）
    status/manual_signoff.json     人工结论（本模块写）
    status/seal_manifest.json      TB / RTL 封存清单（本模块写）

原则：
  · 人工签核**只记录人的决定**，不改 derive 判定、不伪造证据；
  · 封存必须先有结论（每个用例 APPROVED/REJECTED），否则拒绝；
  · 封存后签核表锁定；解封需要签核人 + 原因，并留 action audit。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.runtime.atomic import atomic_write_json
from src.layers.l2_orchestration.flow_shared import _read_json, _resolve_run_dir

SCHEMA = "manual_signoff_v1"
SEAL_SCHEMA = "seal_manifest_v1"
DECISIONS = ("APPROVED", "REJECTED", "PENDING")


# ═══════════════════════════════════════════════════════════
# 读取
# ═══════════════════════════════════════════════════════════

def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _canonical(doc: Any) -> str:
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, default=str,
                      separators=(",", ":"))


def _file_sha(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _cases(root: Path) -> List[Dict[str, Any]]:
    doc = _read_json(root / "coverage" / "case_ir.json") or {}
    return [c for c in (doc.get("cases") or []) if isinstance(c, dict)
            and c.get("id")]


def _module(root: Path) -> str:
    doc = _read_json(root / "coverage" / "case_ir.json") or {}
    return str(doc.get("module") or "")


def _case_evidence(root: Path) -> Dict[str, Dict[str, Any]]:
    """case_cov 记录按 case_id 聚合（只读）。"""
    out: Dict[str, Dict[str, Any]] = {}
    cov = root / "coverage" / "case_cov"
    if not cov.is_dir():
        return out
    for path in sorted(cov.rglob("*.json")):
        rec = _read_json(path) or {}
        cid = str(rec.get("case_id") or "")
        if not cid:
            continue
        entry = out.setdefault(cid, {"records": 0, "statuses": {}})
        entry["records"] += 1
        status = str(rec.get("case_status") or "UNKNOWN")
        entry["statuses"][status] = entry["statuses"].get(status, 0) + 1
    for entry in out.values():
        statuses = entry.get("statuses") or {}
        if statuses.get("VERIFIED"):
            entry["status"] = "VERIFIED"
        elif statuses.get("PARTIAL"):
            entry["status"] = "PARTIAL"
        elif statuses:
            entry["status"] = sorted(statuses)[0]
        else:
            entry["status"] = "NO_EVIDENCE"
    return out


def _manual_doc(root: Path) -> Dict[str, Any]:
    doc = _read_json(root / "status" / "manual_signoff.json") or {}
    if doc.get("schema") != SCHEMA:
        doc = {"schema": SCHEMA, "run_id": root.name, "cases": {}}
    doc.setdefault("cases", {})
    return doc


def _seal_doc(root: Path) -> Dict[str, Any]:
    return _read_json(root / "status" / "seal_manifest.json") or {}


def _contract_hash(root: Path) -> str:
    for name in ("contract/contract_manifest.json", "contract/contract.yaml"):
        path = root / name
        if path.suffix == ".json":
            doc = _read_json(path) or {}
            if doc.get("contract_hash"):
                return str(doc["contract_hash"])
    return ""


def _gate_snapshot(root: Path) -> Dict[str, Any]:
    gates = _read_json(root / "coverage" / "gates.json") or {}
    return {"verdict": gates.get("verdict", ""),
            "counts": gates.get("counts") or {}}


def manual_signoff(run_dir: str = "") -> Dict[str, Any]:
    """逐用例签核表 + 封存状态。"""
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error
    cases = _cases(root)
    evidence = _case_evidence(root)
    manual = _manual_doc(root)
    seal = _seal_doc(root)
    contract_hash = _contract_hash(root)
    rows: List[Dict[str, Any]] = []
    counts = {"APPROVED": 0, "REJECTED": 0, "PENDING": 0}
    for case in cases:
        cid = str(case.get("id"))
        decision = (manual.get("cases") or {}).get(cid) or {}
        ev = evidence.get(cid) or {}
        status = str(decision.get("decision") or "PENDING").upper()
        if status not in DECISIONS:
            status = "PENDING"
        counts[status] = counts.get(status, 0) + 1
        rows.append({
            "case_id": cid,
            "name": case.get("name") or "",
            "source": case.get("source") or "",
            "evidence": ev.get("status") or "NO_EVIDENCE",
            "evidence_records": ev.get("records", 0),
            "decision": status,
            "signer": decision.get("signer") or "",
            "at": decision.get("at") or "",
            "comment": decision.get("comment") or "",
            "_case_hash": _sha(_canonical(case)),
        })
    sealed = bool(seal.get("sealed"))
    return {
        "available": True,
        "run_dir": str(root),
        "module": _module(root),
        "contract_hash": contract_hash,
        "gate": _gate_snapshot(root),
        "cases": rows,
        "summary": {
            "total": len(rows),
            "approved": counts.get("APPROVED", 0),
            "rejected": counts.get("REJECTED", 0),
            "pending": counts.get("PENDING", 0),
            "decided": counts.get("APPROVED", 0) + counts.get("REJECTED", 0),
        },
        "seal": {
            "present": bool(seal),
            "sealed": sealed,
            "sealed_at": seal.get("sealed_at", ""),
            "sealed_by": seal.get("sealed_by", ""),
            "tb_hash": (seal.get("tb") or {}).get("aggregate_hash", ""),
            "rtl_hash": (seal.get("rtl") or {}).get("aggregate_hash", ""),
            "note": seal.get("note", ""),
        },
        "can_edit": not sealed,
        "note": "" if cases else "这一轮没有 case_ir.json（老 run，或没跑到 verify）",
    }


# ═══════════════════════════════════════════════════════════
# 人工签核
# ═══════════════════════════════════════════════════════════

def _audit(root: Path, action: str, *, actor: str, input_sha: str,
           output_sha: str, decision: str = "APPROVAL") -> None:
    """动作审计：高风险动作必须有 appr_id（绑定输入哈希）。"""
    try:
        from src.layers.l3_decision.control_plane import approval_token, record

        record(root, {
            "action": action, "role": "engineer", "decision": decision,
            "risk": "HIGH", "policy_id": "CP-MANUAL", "reason": "",
            "input_sha": input_sha,
        }, actor=actor, output_sha=output_sha,
            appr_id=approval_token(action, actor=actor, input_sha=input_sha))
    except Exception:                                  # noqa: BLE001 旁路
        pass


def record_case_decision(run_dir: str = "", case_id: str = "",
                         decision: str = "", signer: str = "",
                         comment: str = "", force: bool = False
                         ) -> Dict[str, Any]:
    """记录一个用例的人工结论（APPROVED / REJECTED / PENDING）。"""
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error
    case_id = str(case_id or "").strip()
    decision = str(decision or "").upper()
    if decision not in DECISIONS:
        return {"error": f"未知结论 {decision!r}（允许 {DECISIONS}）"}
    if decision != "PENDING" and not str(signer or "").strip():
        return {"error": "签核/驳回必须填写签核人"}
    if _seal_doc(root).get("sealed") and not force:
        return {"error": "这一轮已封存 TB/RTL —— 先解封再修改签核结论"}
    case = next((c for c in _cases(root) if str(c.get("id")) == case_id), None)
    if case is None:
        return {"error": f"用例不存在：{case_id}"}
    manual = _manual_doc(root)
    entry = {
        "decision": decision,
        "signer": str(signer or "").strip(),
        "at": _now(),
        "comment": str(comment or "").strip(),
        "case_hash": _sha(_canonical(case)),
        "contract_hash": _contract_hash(root),
    }
    manual["cases"][case_id] = entry
    manual["updated_at"] = entry["at"]
    path = root / "status" / "manual_signoff.json"
    atomic_write_json(path, manual)
    _audit(root, "manual_case_signoff", actor=entry["signer"] or "unknown",
           input_sha=entry["case_hash"], output_sha=_sha(_canonical(entry)))
    payload = manual_signoff(str(root))
    payload["recorded"] = {"case_id": case_id, **entry}
    return payload


# ═══════════════════════════════════════════════════════════
# TB / RTL 封存
# ═══════════════════════════════════════════════════════════

_TB_ROOTS = ("agents", "env", "bench", "tb", "harness")
_TB_EXT = (".sv", ".svh", ".v", ".vh")
_RTL_EXT = (".sv", ".svh", ".v", ".vh")


def _files(root: Path, paths: List[Path], exts: tuple) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for base in paths:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix.lower() in exts:
                rows.append({
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _file_sha(path),
                    "size": path.stat().st_size,
                })
    return rows


def _aggregate(rows: List[Dict[str, Any]]) -> str:
    return _sha("\n".join(f"{r['path']}:{r['sha256']}" for r in rows))


def _tb_files(root: Path) -> List[Dict[str, Any]]:
    rows = _files(root, [root / name for name in _TB_ROOTS], _TB_EXT)
    rows += _files(root, [root / "inputs" / "yaml" / "uvm"], (".yaml", ".yml"))
    return rows


def _rtl_files(root: Path) -> List[Dict[str, Any]]:
    rows = _files(root, [root / "rtl"], _RTL_EXT)
    if rows:
        return rows
    module = _module(root)
    if module:
        rows = _files(root, [root.parent / "specs" / module], _RTL_EXT)
    return rows


def seal_tb_rtl(run_dir: str = "", signer: str = "", note: str = "",
                force: bool = False) -> Dict[str, Any]:
    """封存 TB + RTL：逐文件哈希 + 聚合哈希 + 签核快照。"""
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error
    signer = str(signer or "").strip()
    if not signer:
        return {"error": "封存必须填写签核人"}
    payload = manual_signoff(str(root))
    summary = payload.get("summary") or {}
    pending = int(summary.get("pending") or 0)
    if pending and not force:
        return {"error": f"还有 {pending} 个用例没有人工结论 —— 全部签核/驳回后才能封存"}
    tb = _tb_files(root)
    rtl = _rtl_files(root)
    if not tb:
        return {"error": "没有找到 TB 源文件（agents/env/bench/tb）"}
    if not rtl:
        return {"error": "没有找到 RTL 源文件（rtl/ 或 specs/<module>/）"}
    case_ir = _read_json(root / "coverage" / "case_ir.json") or {}
    seal = {
        "schema": SEAL_SCHEMA,
        "sealed": True,
        "run_id": root.name,
        "module": _module(root),
        "sealed_at": _now(),
        "sealed_by": signer,
        "note": str(note or "").strip(),
        "contract_hash": _contract_hash(root),
        "case_ir_sha": _sha(_canonical(case_ir)),
        "signoff_digest": _sha(_canonical(_manual_doc(root))),
        "signoff_summary": summary,
        "gate_snapshot": _gate_snapshot(root),
        "tb": {"root": "agents/env/bench/tb", "count": len(tb),
               "aggregate_hash": _aggregate(tb), "files": tb},
        "rtl": {"root": "rtl", "count": len(rtl),
                "aggregate_hash": _aggregate(rtl), "files": rtl},
    }
    atomic_write_json(root / "status" / "seal_manifest.json", seal)
    # 证据包也收一份：封存清单是签核材料，不是过程文件。
    atomic_write_json(root / "signoff_evidence" / "seal_manifest.json", seal)
    _audit(root, "seal_tb_rtl", actor=signer,
           input_sha=seal["signoff_digest"],
           output_sha=_sha(_canonical(seal)))
    return manual_signoff(str(root))


def unseal(run_dir: str = "", signer: str = "", reason: str = ""
           ) -> Dict[str, Any]:
    """解封：需要签核人 + 原因；封存清单保留，只把状态翻成未封存。"""
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error
    signer = str(signer or "").strip()
    reason = str(reason or "").strip()
    if not signer or not reason:
        return {"error": "解封必须填写签核人与原因"}
    seal = _seal_doc(root)
    if not seal.get("sealed"):
        return {"error": "这一轮没有处于封存状态"}
    seal["sealed"] = False
    seal["unsealed_at"] = _now()
    seal["unsealed_by"] = signer
    seal["unseal_reason"] = reason
    atomic_write_json(root / "status" / "seal_manifest.json", seal)
    _audit(root, "unseal_tb_rtl", actor=signer,
           input_sha=str(seal.get("signoff_digest") or ""),
           output_sha=_sha(_canonical(seal)))
    return manual_signoff(str(root))


__all__ = [
    "DECISIONS", "SCHEMA", "SEAL_SCHEMA", "manual_signoff",
    "record_case_decision", "seal_tb_rtl", "unseal",
]
