"""Unified Verification IR v3 —— 五个语义域的稳定数据形状。

```text
D1 Attribute      静态功能空间（dimensions / values / coverpoints / bins / cross）
D2 Behavioral     动态行为（states / events / transitions / sequences）
D3 Configuration  配置空间（config dimensions / cross / instances / exclusions）
D4 Resource       资源与交互（resource / operation / access / interaction）
D5 Verification   契约与证据要求（groups / sva / scb / constraints / obligations）
```

**身份不另起一套**：`tp_id / case_id / tst_id / evd_id / cell_id` 沿用现有体系；
IR 只负责把它们组织成可编译、可校验、可哈希的视图。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA = "verification_ir_v3"
IR_VERSION = "3.0"


def canonical_hash(doc: Any) -> str:
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class IRIdentity:
    module_id: str = ""
    design_version: str = ""
    model_version: str = ""
    ir_id: str = ""
    ir_hash: str = ""


@dataclass
class IRRelation:
    relation_id: str
    source_id: str
    target_id: str
    relation_type: str
    evidence_requirement: Optional[str] = None


#: 允许的关系类型 —— Schema 校验用，禁止任意字符串进入正式 IR。
RELATION_TYPES = frozenset({
    "derived_from", "realizes", "constrained_by", "depends_on",
    "interacts_with", "observed_by", "checked_by", "covered_by",
})


@dataclass
class VerificationIR:
    identity: IRIdentity
    attributes: Dict[str, Any] = field(default_factory=dict)
    behaviors: Dict[str, Any] = field(default_factory=dict)
    configurations: Dict[str, Any] = field(default_factory=dict)
    resources: Dict[str, Any] = field(default_factory=dict)
    verification: Dict[str, Any] = field(default_factory=dict)
    relations: List[IRRelation] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema: str = SCHEMA
    ir_version: str = IR_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "ir_version": self.ir_version,
            "identity": asdict(self.identity),
            "attributes": self.attributes,
            "behaviors": self.behaviors,
            "configurations": self.configurations,
            "resources": self.resources,
            "verification": self.verification,
            "relations": [asdict(r) for r in self.relations],
            "metadata": self.metadata,
        }

    def compute_hash(self) -> str:
        body = self.to_dict()
        body.get("identity", {}).pop("ir_id", None)
        body.get("identity", {}).pop("ir_hash", None)
        return canonical_hash(body)

    def seal(self) -> "VerificationIR":
        self.identity.ir_hash = self.compute_hash()
        self.identity.ir_id = f"IR-{self.identity.ir_hash[:12]}"
        return self


__all__ = [
    "IR_VERSION", "RELATION_TYPES", "SCHEMA", "IRIdentity", "IRRelation",
    "VerificationIR", "canonical_hash",
]
