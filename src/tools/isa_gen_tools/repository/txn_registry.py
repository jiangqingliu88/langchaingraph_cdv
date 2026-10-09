"""事务注册表的装载 —— `schema/txn.registry.json` → `TransactionRegistry`。

装载时会**对着 op 注册表校验**（`TransactionRegistry.validate_against`）——
那是两个数据源之间唯一的连接点，漏过去的话生成器要到造事务时才发现
"没有这条指令"，而那时已经在一个深层调用里了。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..domain import (Effect, HardConstraint, OpRegistry, RegistryError,
                      TxnSpec, TransactionRegistry)

TXN_REGISTRY_FILE = Path(__file__).resolve().parents[1] / "schema" / "txn.registry.json"


def load_txn_registry(path: Optional[Path] = None,
                      ops: Optional[OpRegistry] = None) -> TransactionRegistry:
    """读事务注册表。给了 `ops` 就同时校验两边对得上。"""
    target = Path(path) if path else TXN_REGISTRY_FILE
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RegistryError(f"事务注册表不存在：{target}", target=str(target)) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"事务注册表读不出来：{exc}", target=str(target)) from exc

    entries = raw.get("transactions") if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or not entries:
        raise RegistryError(f"事务注册表里没有 transactions 列表：{target}",
                            target=str(target))

    registry = TransactionRegistry([_spec_from_dict(e, target) for e in entries])
    if ops is not None:
        registry.validate_against(ops)
    return registry


def _spec_from_dict(entry: Dict[str, Any], source: Any) -> TxnSpec:
    txn_id = str(entry.get("id") or "").strip()
    if not txn_id:
        raise RegistryError("事务缺 id", target=str(source))
    ops = entry.get("ops")
    if not isinstance(ops, list) or not ops:
        raise RegistryError(f"事务 {txn_id} 的 ops 必须是非空列表", target=txn_id,
                            fix="顺序即发射顺序：pre 在前、drv 在后")
    return TxnSpec(
        id=txn_id,
        ops=tuple(str(op) for op in ops),
        group=str(entry.get("group") or ""),
        requires=tuple(str(r) for r in (entry.get("requires") or [])),
        hard=tuple(_hard(h) for h in (entry.get("hard") or [])),
        effects=tuple(_effect(e) for e in (entry.get("effects") or [])),
        cfg=str(entry.get("cfg") or ""),
        roles={str(k): [str(x) for x in v]
               for k, v in (entry.get("roles") or {}).items()},
        note=str(entry.get("note") or ""),
        deferred=bool(entry.get("deferred", False)),
    )


def _hard(raw: Dict[str, Any]) -> HardConstraint:
    if not isinstance(raw, dict) or not raw.get("kind"):
        raise RegistryError(f"hard 条目缺 kind：{raw!r}", target="txn.registry.json")
    return HardConstraint(kind=str(raw["kind"]), target=str(raw.get("target") or ""),
                          param=raw.get("param"), note=str(raw.get("note") or ""))


def _effect(raw: Dict[str, Any]) -> Effect:
    if not isinstance(raw, dict) or not raw.get("kind"):
        raise RegistryError(f"effect 条目缺 kind：{raw!r}", target="txn.registry.json")
    return Effect(kind=str(raw["kind"]), target=str(raw.get("target") or ""),
                  span=str(raw.get("span") or ""), note=str(raw.get("note") or ""))
