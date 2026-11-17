"""M1 —— 契约成为**构建物**：`contract/contract.yaml` + 义务 + 清单。

    <run>/contract/
        contract.yaml            ← L1（由 case_ir 编译，带规范哈希）
        obligations.json         ← L2（展开结果，ops 按它规划执行）
        contract_manifest.json   ← hash + 生成器版本 + 输入 sha（漂移检测锚点）

为什么是"构建物"而不是流程中间件：契约一旦生成就不再随流程漂 ——
`ops` 先校验它存在且哈希自洽才开跑；`task_meta` 记下 `contract_hash`，
证据只对**这一版**契约有效。改了契约，旧事实会被标 `stale`，不静默复用。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.runtime_plane.core.runtime.atomic import atomic_write_json, atomic_write_text

from .compiler import compile_obligations
from .contract_model import (
    Contract, Obligation, canonical_hash, contract_from_case_ir,
)
from .ledger import anchor_contract, contract_anchor

SCHEMA_MANIFEST = "contract_manifest_v1"
GENERATOR = "verification_os.compiler@v3"

CONTRACT_DIR = "contract"
CONTRACT_YAML = "contract.yaml"
OBLIGATIONS_JSON = "obligations.json"
MANIFEST_JSON = "contract_manifest.json"
#: VPlan C-* → 本环境契约义务的映射（sidecar；不参与契约哈希）。
VPLAN_MAP_JSON = "vplan_map.json"


def contract_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / CONTRACT_DIR


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _obligations_by_case(obligations: List[Any]) -> Dict[str, List[str]]:
    by_case: Dict[str, List[str]] = {}
    for obligation in obligations:
        by_case.setdefault(str(obligation.case), []).append(
            str(obligation.obligation_id))
    return by_case


def _case_refs(case: Dict[str, Any]) -> List[str]:
    return [str(c) for c in (case.get("feats") or case.get("requirements")
                             or []) if c]


def _case_artifacts(case: Dict[str, Any]) -> List[str]:
    """case 覆盖到的环境资产：组 / SVA / SCB（VPlan 的 C-* 靠它们取证）。"""
    artifacts = [str(g.get("group")) for g in case.get("groups") or []
                 if isinstance(g, dict) and g.get("group")]
    for key in ("sva", "scb"):
        artifacts += [str(s.get("id")) for s in case.get(key) or []
                      if isinstance(s, dict) and s.get("id")]
    return artifacts


def _merge_case(contracts: Dict[str, Dict[str, Any]], cid: str,
                refs: List[str], artifacts: List[str],
                by_case: Dict[str, List[str]]) -> None:
    """一个 case 的引用合并进每个 C-* 槽位（去重，引用不复制字段）。"""
    for ref in refs:
        slot = contracts.setdefault(ref, {
            "cases": [], "obligations": [], "artifacts": []})
        for key, values in (("cases", [cid]),
                            ("obligations", by_case.get(cid) or []),
                            ("artifacts", artifacts)):
            for value in values:
                if value not in slot[key]:
                    slot[key].append(value)


def build_vplan_contract_map(case_ir: Dict[str, Any],
                             obligations: List[Any]) -> Dict[str, Any]:
    """VPlan `C-*` → 本 run 环境契约（CASE / OBL / 资产）的映射。

    映射粒度是 **case**：环境契约按 case 展开义务，case IR 的 `feats`
    是唯一把 C-* 指回 case 的字段。因此一个 C-* 的"已清偿"意味着
    引用它的 case 的**全部**义务都已 PROVEN/NOT_APPLICABLE —— 宁可严，
    不拿一个组的命中替整条契约背书。
    """
    by_case = _obligations_by_case(obligations)
    contracts: Dict[str, Dict[str, Any]] = {}
    for case in case_ir.get("cases") or []:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("id") or "")
        refs = _case_refs(case)
        if cid and refs:
            _merge_case(contracts, cid, refs, _case_artifacts(case), by_case)
    if not contracts:
        return {}
    return {"schema": "vplan_contract_map_v1",
            "module": str(case_ir.get("module") or ""),
            "contracts": contracts}


def write_contract(run_dir: str | Path, case_ir: Dict[str, Any],
                   *, module: str = "") -> Dict[str, Any]:
    """`case_ir` → 契约三件套；返回 manifest（含 `contract_hash`）。"""
    contract = contract_from_case_ir(case_ir)
    if module and not contract.module:
        contract.module = module
        contract.seal()
    obligations = compile_obligations(contract)

    out = contract_dir(run_dir)
    out.mkdir(parents=True, exist_ok=True)
    body = contract.model_dump(by_alias=True, exclude={"hash"})
    atomic_write_text(
        out / CONTRACT_YAML,
        yaml.safe_dump({**body, "hash": contract.hash}, allow_unicode=True,
                       sort_keys=False))
    atomic_write_json(out / OBLIGATIONS_JSON,
                      [o.model_dump(by_alias=True) for o in obligations])
    vplan_map = build_vplan_contract_map(case_ir, obligations)
    if vplan_map:
        atomic_write_json(out / VPLAN_MAP_JSON, vplan_map)
    manifest = {
        "schema": SCHEMA_MANIFEST,
        "contract_id": contract.id,
        "contract_hash": contract.hash,
        "obligations": len(obligations),
        "cases": len(contract.cases),
        "generator": GENERATOR,
        "inputs": {"case_ir_sha256": _sha_text(canonical_hash(case_ir))},
    }
    atomic_write_json(out / MANIFEST_JSON, manifest)
    # L2 → L3 交接：**证据产生之前**把契约版本冻结进账本（只追加的承诺）。
    # 之后 AI 再改 case_ir / 重建契约，旧事实不会静默对上新版。
    anchor_contract(run_dir, contract.hash,
                    manifest["inputs"]["case_ir_sha256"], generator=GENERATOR)
    return manifest


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_list(path: Path) -> list:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return []
    return doc if isinstance(doc, list) else []


def _load_obligations(run_dir: str | Path) -> List[Obligation]:
    out: List[Obligation] = []
    for row in _read_list(contract_dir(run_dir) / OBLIGATIONS_JSON):
        try:
            out.append(Obligation(**row))
        except Exception:                  # noqa: BLE001 坏行跳过，不阻断 link
            continue
    return out


def ensure_vplan_map(run_dir: str | Path) -> bool:
    """老 run 补写 `contract/vplan_map.json`；已存在或没有 case_ir → 不动。

    `link` 对历史 run 调它：映射是**确定性投影**（case_ir + obligations），
    补写不会改变契约哈希，也不改任何证据。
    """
    out = contract_dir(run_dir)
    if (out / VPLAN_MAP_JSON).is_file():
        return False
    case_ir = _read_json(Path(run_dir) / "coverage" / "case_ir.json")
    doc = build_vplan_contract_map(case_ir, _load_obligations(run_dir))
    if not doc:
        return False
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out / VPLAN_MAP_JSON, doc)
    return True


def read_manifest(run_dir: str | Path) -> Dict[str, Any]:
    doc = _read_json(contract_dir(run_dir) / MANIFEST_JSON)
    return doc if doc.get("schema") == SCHEMA_MANIFEST else {}


def contract_hash(run_dir: str | Path) -> str:
    """当前契约的规范哈希（没有契约 → 空串，调用方据此拒绝开跑）。"""
    return str(read_manifest(run_dir).get("contract_hash") or "")


def load_contract(run_dir: str | Path) -> Optional[Contract]:
    """读回契约（M2 的 derive 用它，而不是再拿 case_ir 现推一遍）。"""
    doc = _read_json(contract_dir(run_dir) / MANIFEST_JSON)
    if not doc:
        return None
    try:
        raw = yaml.safe_load((contract_dir(run_dir) / CONTRACT_YAML)
                             .read_text(encoding="utf-8", errors="replace")) or {}
    except OSError:
        return None
    raw.pop("schema", None)
    try:
        return Contract(**raw)
    except Exception:                      # noqa: BLE001 读回失败不假装成功
        return None


def check_contract(run_dir: str | Path) -> Dict[str, Any]:
    """校验契约自洽：文件在、哈希对得上、义务数与清单一致。"""
    root = Path(run_dir)
    manifest = read_manifest(root)
    if not manifest:
        return {"ok": False, "reason": "contract_missing",
                "path": str(contract_dir(root))}
    contract = load_contract(root)
    if contract is None:
        return {"ok": False, "reason": "contract_unreadable"}
    recomputed = contract.compute_hash()
    if recomputed != manifest.get("contract_hash"):
        return {"ok": False, "reason": "contract_hash_mismatch",
                "expected": manifest.get("contract_hash"), "actual": recomputed}
    # 账本锚点（老 run 没有锚点 → 不要求；有就必须与当前契约一致）
    anchor = contract_anchor(root)
    if anchor and anchor != manifest.get("contract_hash"):
        return {"ok": False, "reason": "contract_anchor_mismatch",
                "anchor": anchor, "contract_hash": manifest.get("contract_hash")}
    obligations = _read_list(contract_dir(root) / OBLIGATIONS_JSON)
    return {
        "ok": True,
        "contract_id": manifest.get("contract_id"),
        "contract_hash": manifest.get("contract_hash"),
        "obligations": len(obligations),
        "cases": manifest.get("cases", 0),
    }


__all__ = [
    "CONTRACT_DIR", "VPLAN_MAP_JSON", "build_vplan_contract_map",
    "check_contract", "contract_hash", "ensure_vplan_map", "load_contract",
    "read_manifest", "write_contract",
]
