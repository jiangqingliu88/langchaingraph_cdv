"""AXI4-Stream 协议规则声明。协议知识不等于当前设计的确认。"""

from __future__ import annotations

from typing import Any

PROTOCOL = "axi4_stream"
HANDSHAKE = "valid_ready_stable"
REQUIRED_ROLES = ("VALID", "READY", "DATA")


def handshake_requirements(ir: Any) -> tuple[str, ...]:
    """返回仍需满足的事实，不在此处修改或批准 IR。"""
    missing = [f"缺少角色 {role}" for role in REQUIRED_ROLES if role not in {signal.role for signal in ir.signals}]
    if not ir.rules:
        missing.append("接口未声明握手规则")
    return tuple(missing)


def protocol_reference() -> dict[str, str]:
    return {
        "reference_id": "axi4-stream-valid-ready-stability",
        "requirement": "VALID 高而 READY 低时，VALID 与声明的 payload 必须保持稳定，直到握手完成",
        "semantic_family": "valid_ready",
    }


__all__ = ["HANDSHAKE", "PROTOCOL", "REQUIRED_ROLES", "handshake_requirements", "protocol_reference"]
