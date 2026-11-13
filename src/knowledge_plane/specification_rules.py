"""协议/领域知识提供要求清单，不替 Agent 做推理、不替 Engine 裁决。"""

from __future__ import annotations

_RULES = {
    "dma": ("burst_boundary", "alignment", "max_outstanding", "address_width"),
    "axi": ("burst_boundary", "alignment", "max_outstanding", "address_width"),
}


class ProtocolKnowledge:
    def required_for(self, domain: str) -> tuple[str, ...]:
        return _RULES.get(str(domain or "").lower(), ())

    def cite(self, domain: str) -> dict[str, str]:
        return {"kind": "protocol_knowledge", "domain": str(domain), "locator": f"signoffai://knowledge/{domain}"}


__all__ = ["ProtocolKnowledge"]
