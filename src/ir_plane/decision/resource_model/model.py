"""Resource Model：资源、操作、访问、交互 → 可计算的交互事实。

先校验声明，再计算地址事实。非法值不会静默变成 0，并借 overlap=NONE
伪装成无冲突；解析问题保留在 ``declaration_errors`` 供 Engine 裁决。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .address import AddressRange, overlap
from .policy import evaluate
from .schema import (
    RELATIONS,
    Resource,
    ResourceAccess,
    ResourceInteraction,
    ResourceOperation,
)

MISSING = object()


def _issue(rule: str, target: Any, message: str, status: str = "INCOMPLETE") -> dict[str, str]:
    return {"rule": rule, "target": str(target), "message": message, "status": status}


def _integer(value: Any, path: str, errors: list[dict[str, str]], default: Any = MISSING) -> int | None:
    """解析整数；不接受 float/bool/空字符串，也不把解析失败吞成合法值。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        if default is not MISSING:
            return default
        errors.append(_issue("invalid_integer", path, "缺少必需的整数"))
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        errors.append(_issue("invalid_integer", path, f"不是合法整数：{value!r}"))
        return 0
    try:
        return int(value, 0) if isinstance(value, str) else value
    except ValueError:
        errors.append(_issue("invalid_integer", path, f"不是合法整数：{value!r}"))
        return 0


def _rows(doc: dict[str, Any], key: str, errors: list[dict[str, str]]) -> list[tuple]:
    value = doc.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(_issue("invalid_container", key, "必须是列表"))
        return []
    rows = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            errors.append(_issue("invalid_row", f"{key}[{index}]", "必须是对象"))
            continue
        rows.append((index, row))
    return rows


def _mapping(value: Any, path: str, errors: list[dict[str, str]]) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        errors.append(_issue("invalid_container", path, "必须是对象"))
        return {}
    return value


def _duplicate_identity(errors: list[dict[str, str]], groups: tuple) -> None:
    for kind, items, attr in groups:
        seen = set()
        for index, item in enumerate(items):
            value = str(getattr(item, attr) or "")
            target = f"{kind}[{index}]"
            if not value:
                errors.append(_issue("missing_id", target, "id 不能为空"))
            elif value in seen:
                errors.append(_issue("duplicate_id", target, f"重复 id：{value}"))
            seen.add(value)


@dataclass
class ResourceModel:
    module: str = ""
    resources: list[Resource] = field(default_factory=list)
    operations: list[ResourceOperation] = field(default_factory=list)
    interactions: list[ResourceInteraction] = field(default_factory=list)
    #: checker 并发窗口（与仿真 `$time` 同单位）。0 = 只比较同一时刻的访问；
    #: 更大值表示"两次访问相隔不超过该窗口才算并发"。协议不同取值不同，
    #: 所以由声明文件给，不在这里猜。
    check_window: int = 0
    #: YAML/JSON 形状解析错误；不进入公开 ResourceModel JSON，避免改变 IR 形状。
    declaration_errors: list[dict[str, str]] = field(default_factory=list, repr=False)

    def resource(self, rid: str) -> Resource | None:
        return next((r for r in self.resources if r.resource_id == rid), None)

    def operation(self, oid: str) -> ResourceOperation | None:
        return next((o for o in self.operations if o.operation_id == oid), None)

    def _validate_resources(self, errors: list[dict[str, str]], address_width: int) -> None:
        for index, resource in enumerate(self.resources):
            target = f"resources[{index}]"
            if not resource.address_space:
                errors.append(_issue("invalid_address_space", target, "address_space 不能为空"))
            base, size = resource.base, resource.size
            if base is not None and base < 0:
                errors.append(_issue("invalid_resource_base", target, "base 不能为负数"))
            if size is not None and size <= 0:
                errors.append(_issue("invalid_resource_size", target, "size 必须大于 0"))
            if resource.granularity <= 0:
                errors.append(_issue("invalid_granularity", target, "granularity 必须大于 0"))
            used = any(op.resource_id == resource.resource_id for op in self.operations)
            if base is None and size is None and used:
                errors.append(_issue("incomplete_resource_bounds", target, "该资源有访问操作，必须声明 base 和 size"))
            elif (base is None) != (size is None):
                errors.append(_issue("incomplete_resource_bounds", target, "base 和 size 必须同时声明或同时省略"))
            elif base is not None and base >= 0 and size > 0 and base + size > (1 << address_width):
                errors.append(_issue("resource_bounds_overflow", target, "资源边界超出声明的地址宽度", status="FAIL"))

    def _validate_references(self, errors: list[dict[str, str]]) -> None:
        resource_ids = {r.resource_id for r in self.resources}
        operation_ids = {o.operation_id for o in self.operations}
        for op in self.operations:
            if not op.resource_id:
                errors.append(_issue("missing_resource", op.operation_id, "访问操作必须绑定资源"))
            if op.resource_id and op.resource_id not in resource_ids:
                errors.append(_issue("unknown_resource", op.operation_id, f"操作引用了不存在的资源 {op.resource_id}"))
        for it in self.interactions:
            if it.operation_a not in operation_ids or it.operation_b not in operation_ids:
                errors.append(_issue("unknown_operation", it.interaction_id, "交互引用了不存在的操作"))
            if it.relation not in RELATIONS:
                errors.append(_issue("unknown_policy", it.interaction_id, f"未知策略：{it.relation}"))
            left, right = self.operation(it.operation_a), self.operation(it.operation_b)
            if not left or not right:
                continue
            self._validate_interaction_endpoints(it, left, right, errors)

    def _validate_interaction_endpoints(
        self, it: ResourceInteraction, left: ResourceOperation, right: ResourceOperation, errors: list[dict[str, str]]
    ) -> None:
        if left.resource_id and right.resource_id and left.resource_id != right.resource_id:
            r_left = self.resource(left.resource_id)
            r_right = self.resource(right.resource_id)
            if r_left and r_right and r_left.address_space != r_right.address_space:
                errors.append(
                    _issue("cross_address_space", it.interaction_id, "不能跨 address_space 计算同一段地址重叠")
                )
        if it.relation == "EXCLUSIVE" and (not left.owner_id or not right.owner_id):
            errors.append(_issue("missing_owner", it.interaction_id, "EXCLUSIVE 需要双方都有 owner"))

    def _validate_accesses(self, errors: list[dict[str, str]], address_width: int) -> None:
        for op in self.operations:
            if not op.accesses:
                errors.append(_issue("empty_accesses", op.operation_id, "操作至少需要一个访问区间"))
                continue
            resource = self.resource(op.resource_id)
            for access in op.accesses:
                if access.address < 0:
                    errors.append(_issue("invalid_access_address", op.operation_id, "访问地址不能为负数"))
                if access.length <= 0:
                    errors.append(_issue("invalid_access_length", op.operation_id, "访问长度必须大于 0"))
                    continue
                interval = AddressRange(access.address, access.length)
                if interval.overflowed(address_width):
                    errors.append(
                        _issue("address_overflow", op.operation_id, "访问区间超出声明的地址宽度", status="FAIL")
                    )
                if resource is None or resource.base is None or resource.size is None:
                    continue
                end = resource.base + resource.size
                if interval.start < resource.base or interval.end > end:
                    errors.append(
                        _issue(
                            "access_out_of_bounds",
                            op.operation_id,
                            f"访问 [{interval.start:#x}, {interval.end:#x}) 超出资源 [{resource.base:#x}, {end:#x})",
                            status="FAIL",
                        )
                    )

    def validate(self, *, address_width: int = 64) -> list[dict[str, str]]:
        """声明错误为 INCOMPLETE；越界等确定违规为 FAIL，不改变原返回列表契约。"""
        errors: list[dict[str, str]] = [dict(row) for row in self.declaration_errors]
        for key in ("resources", "operations", "interactions"):
            if not getattr(self, key):
                errors.append(_issue(f"missing_{key}", key, f"Resource intent 必须声明 {key}"))
        _duplicate_identity(
            errors,
            (
                ("resources", self.resources, "resource_id"),
                ("operations", self.operations, "operation_id"),
                ("interactions", self.interactions, "interaction_id"),
            ),
        )
        self._validate_resources(errors, address_width)
        self._validate_references(errors)
        self._validate_accesses(errors, address_width)
        if self.check_window < 0:
            errors.append(_issue("invalid_check_window", "check_window", "不能为负数"))
        return errors

    def interaction_facts(self, *, address_width: int = 64) -> list[dict[str, Any]]:
        """每条 interaction → 逐访问对的 Overlap + 策略结论。"""
        facts: list[dict[str, Any]] = []
        for it in self.interactions:
            op_a = self.operation(it.operation_a)
            op_b = self.operation(it.operation_b)
            if op_a is None or op_b is None:
                continue
            for acc_a in op_a.accesses:
                for acc_b in op_b.accesses:
                    if op_a.resource_id and op_b.resource_id and op_a.resource_id != op_b.resource_id:
                        continue
                    resource_id = op_a.resource_id or op_b.resource_id
                    res = self.resource(resource_id)
                    space = res.address_space if res else ""
                    ra = AddressRange(acc_a.address, acc_a.length, space)
                    rb = AddressRange(acc_b.address, acc_b.length, space)
                    kind = overlap(ra, rb)
                    decision = evaluate(it.relation, kind, same_owner=(op_a.owner_id == op_b.owner_id))
                    facts.append(
                        {
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
                            "overflow": ra.overflowed(address_width) or rb.overflowed(address_width),
                        }
                    )
        return facts

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "resource_model_v1",
            "module": self.module,
            "check_window": self.check_window,
            "resources": [r.__dict__ for r in self.resources],
            "operations": [{**o.__dict__, "accesses": [a.__dict__ for a in o.accesses]} for o in self.operations],
            "interactions": [i.__dict__ for i in self.interactions],
        }


def _accesses_of(operation: dict[str, Any], index: int, errors: list[dict[str, str]]) -> list[ResourceAccess]:
    oid = str(operation.get("id") or operation.get("operation_id") or "")
    accesses: list[ResourceAccess] = []
    raw = operation.get("accesses")
    if raw is not None and not isinstance(raw, list):
        errors.append(_issue("invalid_container", f"operations[{index}].accesses", "必须是列表"))
    for row_index, access in _rows(operation, "accesses", errors):
        accesses.append(
            ResourceAccess(
                address=_integer(access.get("address"), f"operations[{index}].accesses[{row_index}].address", errors),
                length=_integer(access.get("length"), f"operations[{index}].accesses[{row_index}].length", errors),
                access_type=str(access.get("access_type") or access.get("type") or ""),
                transaction_id=str(access.get("transaction_id") or ""),
                operation_id=oid,
            )
        )
    # 兼容 `address/length` 写在 operation 上的简写。
    if not accesses and operation.get("address") is not None:
        accesses = [
            ResourceAccess(
                address=_integer(operation.get("address"), f"operations[{index}].address", errors),
                length=_integer(operation.get("length"), f"operations[{index}].length", errors),
                access_type=str(operation.get("access_type") or ""),
                operation_id=oid,
            )
        ]
    return accesses


def _operation_from(operation: dict[str, Any], index: int, errors: list[dict[str, str]]) -> ResourceOperation:
    watch = _mapping(operation.get("watch"), f"operations[{index}].watch", errors)
    return ResourceOperation(
        operation_id=str(operation.get("id") or operation.get("operation_id") or ""),
        owner_id=str(operation.get("owner") or operation.get("owner_id") or ""),
        operation_type=str(operation.get("type") or operation.get("operation_type") or ""),
        resource_id=str(operation.get("resource") or operation.get("resource_id") or ""),
        accesses=_accesses_of(operation, index, errors),
        start_condition=str(operation.get("start_condition") or ""),
        completion_event=str(operation.get("completion_event") or ""),
        agent=str(operation.get("agent") or ""),
        watch={str(k): str(v) for k, v in watch.items() if str(v)},
    )


def _resource_from(resource: dict[str, Any], index: int, errors: list[dict[str, str]]) -> Resource:
    for numeric_name in ("base", "size"):
        if numeric_name in resource:
            _integer(resource[numeric_name], f"resources[{index}].{numeric_name}", errors, default=None)
    address_space = resource.get("address_space")
    if address_space is not None and not isinstance(address_space, str):
        errors.append(_issue("invalid_address_space", f"resources[{index}].address_space", "必须是字符串"))
    return Resource(
        resource_id=str(resource.get("id") or resource.get("resource_id") or ""),
        resource_type=str(resource.get("type") or resource.get("resource_type") or ""),
        address_space=address_space.strip() if isinstance(address_space, str) else "",
        base=_integer(resource.get("base"), f"resources[{index}].base", errors, default=None),
        size=_integer(resource.get("size"), f"resources[{index}].size", errors, default=None),
        granularity=_integer(resource.get("granularity", 1), f"resources[{index}].granularity", errors),
        attributes=_mapping(resource.get("attributes"), f"resources[{index}].attributes", errors),
    )


def from_dict(doc: dict[str, Any]) -> ResourceModel:
    """YAML/JSON 形状 → ResourceModel；形状错误由 ``validate()`` 统一暴露。"""
    errors: list[dict[str, str]] = []
    if not isinstance(doc, dict):
        return ResourceModel(declaration_errors=[_issue("invalid_document_type", "document", "根节点必须是对象")])
    resources = [_resource_from(row, index, errors) for index, row in _rows(doc, "resources", errors)]
    operations = [_operation_from(row, index, errors) for index, row in _rows(doc, "operations", errors)]
    interactions = [
        ResourceInteraction(
            interaction_id=str(row.get("id") or row.get("interaction_id") or ""),
            operation_a=str(row.get("operation_a") or ""),
            operation_b=str(row.get("operation_b") or ""),
            relation=str(row.get("relation") or row.get("policy") or "UNRESTRICTED").upper(),
            policy_id=str(row.get("policy_id") or ""),
        )
        for index, row in _rows(doc, "interactions", errors)
    ]
    return ResourceModel(
        module=str(doc.get("module") or ""),
        resources=resources,
        operations=operations,
        interactions=interactions,
        check_window=_integer(doc.get("check_window", 0), "check_window", errors),
        declaration_errors=errors,
    )


__all__ = ["ResourceModel", "from_dict"]
