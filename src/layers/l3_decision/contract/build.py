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
from typing import Any, Dict, Optional

import yaml

from src.core.runtime.atomic import atomic_write_json, atomic_write_text

from .compiler import compile_obligations
from .contract_model import Contract, canonical_hash, contract_from_case_ir
from .ledger import anchor_contract, contract_anchor

SCHEMA_MANIFEST = "contract_manifest_v1"
GENERATOR = "verification_os.compiler@v3"

CONTRACT_DIR = "contract"
CONTRACT_YAML = "contract.yaml"
OBLIGATIONS_JSON = "obligations.json"
MANIFEST_JSON = "contract_manifest.json"


def contract_dir(run_dir: str | Path) -> Path:
    return Path(run_dir) / CONTRACT_DIR


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    "CONTRACT_DIR", "check_contract", "contract_hash", "load_contract",
    "read_manifest", "write_contract",
]
