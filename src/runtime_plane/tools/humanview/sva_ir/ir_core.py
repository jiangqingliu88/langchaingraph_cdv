"""SVA 分解 IR —— 每条断言一张属性卡（对应 `arch.md` §8）。

必填六项：`contract / class / antecedent / consequent / cover_property /
bound_cells`。`hit_count == 0` 即 vacuous，不能算验证过。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..ir_common import as_list, norm_id, norm_ids

#: 七类视角（S1~S7）。
SVA_CLASSES = {
    "S1": "协议/握手", "S2": "时序关系", "S3": "数据完整性",
    "S4": "资源不变量", "S5": "安全性", "S6": "活性", "S7": "配置一致性",
}
_ALIASES = {name: key for key, name in SVA_CLASSES.items()}


def norm_class(raw: Any) -> str:
    text = norm_id(raw).upper()
    if text in SVA_CLASSES:
        return text
    if text in _ALIASES:
        return _ALIASES[text]
    for key, name in SVA_CLASSES.items():
        if text.startswith(key):
            return key
    return ""


@dataclass
class SVAIR:
    id: str
    name: str = ""
    contract: str = ""
    klass: str = ""
    level: str = ""
    time: str = ""
    nature: str = ""
    object: str = ""
    condition: str = ""
    antecedent: str = ""
    consequent: str = ""
    property: str = ""
    cover_property: str = ""
    bound_cells: List[str] = field(default_factory=list)
    bound_paths: List[str] = field(default_factory=list)
    bound_feats: List[str] = field(default_factory=list)
    severity: str = "error"
    status: str = "未触发"
    hit_count: int = 0
    fail_count: int = 0

    @classmethod
    def from_dict(cls, raw: Any):
        if not isinstance(raw, dict):
            return None
        sid = norm_id(raw.get("sva_id") or raw.get("id"))
        if not sid:
            return None
        try:
            hit = int(raw.get("hit_count") or 0)
        except (TypeError, ValueError):
            hit = 0
        try:
            fail = int(raw.get("fail_count") or 0)
        except (TypeError, ValueError):
            fail = 0
        return cls(
            id=sid, name=norm_id(raw.get("name") or sid),
            contract=norm_id(raw.get("contract")),
            klass=norm_class(raw.get("class")),
            level=norm_id(raw.get("level")), time=norm_id(raw.get("time")),
            nature=norm_id(raw.get("nature")), object=norm_id(raw.get("object")),
            condition=norm_id(raw.get("condition")),
            antecedent=str(raw.get("antecedent") or ""),
            consequent=str(raw.get("consequent") or ""),
            property=str(raw.get("property") or ""),
            cover_property=str(raw.get("cover_property") or ""),
            bound_cells=norm_ids(raw.get("bound_cells") or raw.get("cells")),
            bound_paths=norm_ids(raw.get("bound_paths") or raw.get("paths")),
            bound_feats=norm_ids(raw.get("bound_feats") or raw.get("feats")),
            severity=norm_id(raw.get("severity")) or "error",
            status=norm_id(raw.get("status")) or "未触发",
            hit_count=hit, fail_count=fail)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sva_id": self.id, "name": self.name, "contract": self.contract,
            "class": self.klass, "level": self.level, "time": self.time,
            "nature": self.nature, "object": self.object,
            "condition": self.condition, "antecedent": self.antecedent,
            "consequent": self.consequent, "property": self.property,
            "cover_property": self.cover_property,
            "bound_cells": list(self.bound_cells),
            "bound_paths": list(self.bound_paths),
            "bound_feats": list(self.bound_feats),
            "severity": self.severity, "status": self.status,
            "hit_count": self.hit_count, "fail_count": self.fail_count,
        }


@dataclass
class SVADoc:
    module: str = ""
    schema: str = "sva_ir_v1"
    contracts: List[str] = field(default_factory=list)
    cells: List[str] = field(default_factory=list)
    paths: List[str] = field(default_factory=list)
    feats: List[str] = field(default_factory=list)
    svas: List[SVAIR] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Any):
        if not isinstance(raw, dict):
            raise ValueError("sva_ir 顶层必须是 mapping")
        contracts = []
        for item in as_list(raw.get("contracts")):
            contracts.append(norm_id(item.get("id") if isinstance(item, dict) else item))
        return cls(
            module=norm_id(raw.get("module")),
            schema=norm_id(raw.get("schema")) or "sva_ir_v1",
            contracts=[c for c in contracts if c],
            cells=norm_ids(raw.get("cells")),
            paths=norm_ids(raw.get("paths")),
            feats=norm_ids(raw.get("feats")),
            svas=[s for s in (SVAIR.from_dict(x) for x in as_list(raw.get("svas")))
                  if s is not None],
            notes=[str(n) for n in as_list(raw.get("notes")) if str(n)])

    def to_dict(self) -> Dict[str, Any]:
        return {"schema": self.schema, "module": self.module,
                "contracts": list(self.contracts), "cells": list(self.cells),
                "paths": list(self.paths), "feats": list(self.feats),
                "svas": [s.to_dict() for s in self.svas],
                "notes": list(self.notes)}
