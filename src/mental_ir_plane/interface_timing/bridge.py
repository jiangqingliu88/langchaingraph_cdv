"""把接口时序证据接入既有 specification_contract_v1，不并行复制规格模型。"""

from __future__ import annotations

from typing import Any

from .model import InterfaceTimingIR, TimingContractError


def to_specification_document(ir: InterfaceTimingIR, binding: Any) -> dict[str, Any]:
    """输入 Temporal Binding 的同一对象，生成原 Specification Contract 的 fragment。

    binding 必须由 check_temporal_ir 生成且属于本 ir；禁止仅凭状态文字携带
    另一个接口的绑定报告或不匹配的 IR hash。
    """
    if binding is None or binding.status != "VALIDATED" or binding.ir_hash != ir.content_hash():
        raise TimingContractError("接口绑定报告缺失、未通过或不属于当前 IR")
    sources = []
    requirements = []
    for rule in ir.rules:
        if rule.anchor is None:
            raise TimingContractError(f"{rule.rule_id} 缺少来源锚点，不能生成规格契约")
        sources.append(
            {
                "source_id": rule.anchor.source_id,
                "kind": "spec",
                "locator": rule.anchor.locator,
                "sha256": rule.anchor.document_sha256,
                "producer": ir.metadata.get("authority", "spec"),
            }
        )
        requirements.append(
            {
                "requirement_id": rule.rule_id,
                "field": f"{ir.protocol}:{rule.kind}",
                "value": {"valid": rule.valid, "ready": rule.ready, "stable_signals": list(rule.stable_signals)},
                "status": rule.status,
                "source_ids": [rule.anchor.source_id],
                "rationale": "由原文锚点、RTL 绑定与时钟/方向检查支持的时序义务",
            }
        )
    metadata = dict(ir.metadata)
    metadata["temporal_interfaces"] = [ir.to_dict()]
    metadata["interface_binding_reports"] = {binding.ir_hash: binding.to_dict()}
    return {
        "schema": "specification_contract_v1",
        "document_id": ir.interface_id,
        "domain": "interface_timing",
        "version": ir.version,
        "sources": sources,
        "requirements": requirements,
        "gaps": [],
        "conflicts": [],
        "lifecycle": [],
        "metadata": metadata,
    }


__all__ = ["to_specification_document"]
