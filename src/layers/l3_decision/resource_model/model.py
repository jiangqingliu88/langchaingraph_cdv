"""Resource Model：资源、操作、访问、交互 → 可计算的交互事实。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .address import AddressRange, overlap
from .policy import evaluate
from .schema import (
    Resource, ResourceAccess, ResourceInteraction, ResourceOperation,
)


@dataclass
class ResourceModel:
    module: str = ""
    resources: List[Resource] = field(default_factory=list)
    operations: List[ResourceOperation] = field(default_factory=list)
    interactions: List[ResourceInteraction] = field(default_factory=list)
    #: checker 并发窗口（与仿真 `$time` 同单位）。0 = 只比较同一时刻的访问；
    #: 更大值表示"两次访问相隔不超过该窗口才算并发"。协议不同取值不同，
    #: 所以由声明文件给，不在这里猜。
    check_window: int = 0

    def resource(self, rid: str) -> Optional[Resource]:
        return next((r for r in self.resources if r.resource_id == rid), None)

    def operation(self, oid: str) -> Optional[ResourceOperation]:
        return next((o for o in self.operations if o.operation_id == oid), None)

    def validate(self) -> List[Dict[str, str]]:
        errors: List[Dict[str, str]] = []
        rids = {r.resource_id for r in self.resources}
        oids = {o.operation_id for o in self.operations}
        for op in self.operations:
            if op.resource_id and op.resource_id not in rids:
                errors.append({"rule": "unknown_resource", "target": op.operation_id,
                               "message": f"操作引用了不存在的资源 {op.resource_id}"})
        for it in self.interactions:
            if it.operation_a not in oids or it.operation_b not in oids:
                errors.append({"rule": "unknown_operation",
                               "target": it.interaction_id,
                               "message": "交互引用了不存在的操作"})
        return errors

    def interaction_facts(self, *, address_width: int = 64
                          ) -> List[Dict[str, Any]]:
        """每条 interaction → 逐访问对的 Overlap + 策略结论。"""
        facts: List[Dict[str, Any]] = []
        for it in self.interactions:
            op_a = self.operation(it.operation_a)
            op_b = self.operation(it.operation_b)
            if op_a is None or op_b is None:
                continue
            for acc_a in op_a.accesses:
                for acc_b in op_b.accesses:
                    if op_a.resource_id and op_b.resource_id \
                            and op_a.resource_id != op_b.resource_id:
                        continue
                    resource_id = op_a.resource_id or op_b.resource_id
                    res = self.resource(resource_id)
                    space = res.address_space if res else ""
                    ra = AddressRange(acc_a.address, acc_a.length, space)
                    rb = AddressRange(acc_b.address, acc_b.length, space)
                    kind = overlap(ra, rb)
                    decision = evaluate(it.relation, kind,
                                        same_owner=(op_a.owner_id == op_b.owner_id))
                    facts.append({
                        "interaction_id": it.interaction_id,
                        "policy_id": it.policy_id,
                        "operation_a": op_a.operation_id,
                        "operation_b": op_b.operation_id,
                        "owner_a": op_a.owner_id,
                        "owner_b": op_b.owner_id,
                        "resource_id": resource_id,
                        "access_a": {"address": ra.start, "length": ra.length},
                        "access_b": {"address": rb.start, "length": rb.length},
                        "overlap": kind,
                        "policy": it.relation,
                        "conflict": decision["conflict"],
                        "requires_checker": decision["requires_checker"],
                        "reason": decision["reason"],
                        "overflow": ra.overflowed(address_width)
                                    or rb.overflowed(address_width),
                    })
        return facts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "resource_model_v1",
            "module": self.module,
            "check_window": self.check_window,
            "resources": [r.__dict__ for r in self.resources],
            "operations": [
                {**o.__dict__,
                 "accesses": [a.__dict__ for a in o.accesses]}
                for o in self.operations
            ],
            "interactions": [i.__dict__ for i in self.interactions],
        }


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value, 0) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return None


def _accesses_of(o: Dict[str, Any]) -> List[ResourceAccess]:
    accesses = [
        ResourceAccess(
            address=_int_or_none(a.get("address")) or 0,
            length=_int_or_none(a.get("length")) or 0,
            access_type=str(a.get("access_type") or a.get("type") or ""),
            transaction_id=str(a.get("transaction_id") or ""),
            operation_id=str(o.get("id") or ""),
        )
        for a in (o.get("accesses") or []) if isinstance(a, dict)
    ]
    # 兼容 `address/length` 写在 operation 上的简写
    if not accesses and o.get("address") is not None:
        accesses = [ResourceAccess(
            address=_int_or_none(o.get("address")) or 0,
            length=_int_or_none(o.get("length")) or 0,
            access_type=str(o.get("access_type") or ""),
            operation_id=str(o.get("id") or ""),
        )]
    return accesses


def _operation_from(o: Dict[str, Any]) -> ResourceOperation:
    return ResourceOperation(
        operation_id=str(o.get("id") or o.get("operation_id") or ""),
        owner_id=str(o.get("owner") or o.get("owner_id") or ""),
        operation_type=str(o.get("type") or o.get("operation_type") or ""),
        resource_id=str(o.get("resource") or o.get("resource_id") or ""),
        accesses=_accesses_of(o),
        start_condition=str(o.get("start_condition") or ""),
        completion_event=str(o.get("completion_event") or ""),
        agent=str(o.get("agent") or ""),
        watch={str(k): str(v) for k, v in (o.get("watch") or {}).items()
               if str(v)},
    )


def from_dict(doc: Dict[str, Any]) -> ResourceModel:
    """YAML/JSON 形状 → ResourceModel。"""
    doc = doc or {}
    resources = [
        Resource(
            resource_id=str(r.get("id") or r.get("resource_id") or ""),
            resource_type=str(r.get("type") or r.get("resource_type") or ""),
            address_space=str(r.get("address_space") or ""),
            base=_int_or_none(r.get("base")),
            size=_int_or_none(r.get("size")),
            granularity=int(r.get("granularity") or 1),
            attributes=dict(r.get("attributes") or {}),
        )
        for r in (doc.get("resources") or []) if isinstance(r, dict)
    ]
    operations = [_operation_from(o) for o in (doc.get("operations") or [])
                  if isinstance(o, dict)]
    interactions = [
        ResourceInteraction(
            interaction_id=str(i.get("id") or i.get("interaction_id") or ""),
            operation_a=str(i.get("operation_a") or ""),
            operation_b=str(i.get("operation_b") or ""),
            relation=str(i.get("relation") or i.get("policy")
                         or "UNRESTRICTED").upper(),
            policy_id=str(i.get("policy_id") or ""),
        )
        for i in (doc.get("interactions") or []) if isinstance(i, dict)
    ]
    return ResourceModel(module=str(doc.get("module") or ""),
                         resources=resources, operations=operations,
                         interactions=interactions,
                         check_window=int(doc.get("check_window") or 0))


__all__ = ["ResourceModel", "from_dict"]
