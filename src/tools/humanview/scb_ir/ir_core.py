"""Scoreboard 分解 IR —— 每个检查项一张属性卡（对应 `arch.md` §9）。

必填六项：`contract / class / model / expected_source / execute_count /
bound_cells`。`execute_count == 0` 等于没写；期望来源必须独立于被测路径。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..ir_common import as_list, norm_id, norm_ids

#: 五类视角（SB1~SB5）。
SCB_CLASSES = {
    "SB1": "数据比对", "SB2": "顺序/匹配", "SB3": "资源账本",
    "SB4": "统计计数", "SB5": "状态/残留",
}
_ALIASES = {name: key for key, name in SCB_CLASSES.items()}

#: 参考模型（期望值从哪来）。
SCB_MODELS = {
    "golden": "golden model", "transaction": "事务记录匹配",
    "shadow": "影子账本/寄存器", "predictor": "预测器",
    "accumulator": "monitor 累加器",
}
_MODEL_ALIASES = {
    "golden_model": "golden", "goldenmodel": "golden", "model": "golden",
    "事务记录": "transaction", "事务记录匹配": "transaction",
    "shadow_ledger": "shadow", "影子账本": "shadow", "影子寄存器": "shadow",
    "预测器": "predictor", "monitor": "accumulator", "累加器": "accumulator",
}


def norm_class(raw: Any) -> str:
    text = norm_id(raw).upper()
    if text in SCB_CLASSES:
        return text
    if text in _ALIASES:
        return _ALIASES[text]
    for key, name in SCB_CLASSES.items():
        if text.startswith(key):
            return key
    return ""


def norm_model(raw: Any) -> str:
    text = norm_id(raw).lower().replace(" ", "_")
    if text in SCB_MODELS:
        return text
    return _MODEL_ALIASES.get(text) or _MODEL_ALIASES.get(norm_id(raw)) or ""


@dataclass
class SCBIR:
    id: str
    name: str = ""
    contract: str = ""
    klass: str = ""
    object: str = ""
    model: str = ""
    timing: str = ""
    method: str = ""
    granularity: str = ""
    check_object: str = ""
    expected_source: str = ""
    actual_source: str = ""
    execute_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    outstanding: int = 0
    residual: int = 0
    bound_cells: List[str] = field(default_factory=list)
    bound_paths: List[str] = field(default_factory=list)
    bound_feats: List[str] = field(default_factory=list)
    severity: str = "error"
    status: str = "未执行"

    @classmethod
    def from_dict(cls, raw: Any):
        if not isinstance(raw, dict):
            return None
        sid = norm_id(raw.get("scb_id") or raw.get("id"))
        if not sid:
            return None

        def _int(key: str) -> int:
            try:
                return int(raw.get(key) or 0)
            except (TypeError, ValueError):
                return 0

        return cls(
            id=sid, name=norm_id(raw.get("name") or sid),
            contract=norm_id(raw.get("contract")),
            klass=norm_class(raw.get("class")),
            object=norm_id(raw.get("object")), model=norm_model(raw.get("model")),
            timing=norm_id(raw.get("timing")), method=norm_id(raw.get("method")),
            granularity=norm_id(raw.get("granularity")),
            check_object=norm_id(raw.get("check_object")),
            expected_source=norm_id(raw.get("expected_source")),
            actual_source=norm_id(raw.get("actual_source")),
            execute_count=_int("execute_count"), pass_count=_int("pass_count"),
            fail_count=_int("fail_count"), outstanding=_int("outstanding"),
            residual=_int("residual"),
            bound_cells=norm_ids(raw.get("bound_cells") or raw.get("cells")),
            bound_paths=norm_ids(raw.get("bound_paths") or raw.get("paths")),
            bound_feats=norm_ids(raw.get("bound_feats") or raw.get("feats")),
            severity=norm_id(raw.get("severity")) or "error",
            status=norm_id(raw.get("status")) or "未执行")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scb_id": self.id, "name": self.name, "contract": self.contract,
            "class": self.klass, "object": self.object, "model": self.model,
            "timing": self.timing, "method": self.method,
            "granularity": self.granularity, "check_object": self.check_object,
            "expected_source": self.expected_source,
            "actual_source": self.actual_source,
            "execute_count": self.execute_count, "pass_count": self.pass_count,
            "fail_count": self.fail_count, "outstanding": self.outstanding,
            "residual": self.residual, "bound_cells": list(self.bound_cells),
            "bound_paths": list(self.bound_paths),
            "bound_feats": list(self.bound_feats),
            "severity": self.severity, "status": self.status,
        }


@dataclass
class SCBDoc:
    module: str = ""
    schema: str = "scb_ir_v1"
    contracts: List[str] = field(default_factory=list)
    cells: List[str] = field(default_factory=list)
    paths: List[str] = field(default_factory=list)
    feats: List[str] = field(default_factory=list)
    checks: List[SCBIR] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Any):
        if not isinstance(raw, dict):
            raise ValueError("scb_ir 顶层必须是 mapping")
        contracts = []
        for item in as_list(raw.get("contracts")):
            contracts.append(norm_id(item.get("id") if isinstance(item, dict) else item))
        return cls(
            module=norm_id(raw.get("module")),
            schema=norm_id(raw.get("schema")) or "scb_ir_v1",
            contracts=[c for c in contracts if c],
            cells=norm_ids(raw.get("cells")),
            paths=norm_ids(raw.get("paths")),
            feats=norm_ids(raw.get("feats")),
            checks=[c for c in (SCBIR.from_dict(x)
                                for x in as_list(raw.get("checks") or raw.get("scbs")))
                    if c is not None],
            notes=[str(n) for n in as_list(raw.get("notes")) if str(n)])

    def to_dict(self) -> Dict[str, Any]:
        return {"schema": self.schema, "module": self.module,
                "contracts": list(self.contracts), "cells": list(self.cells),
                "paths": list(self.paths), "feats": list(self.feats),
                "checks": [c.to_dict() for c in self.checks],
                "notes": list(self.notes)}
