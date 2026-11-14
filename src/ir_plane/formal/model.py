"""Formal IR 的机器可读模型（`formal_plan_v1`）。"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field

SCHEMA = "formal_plan_v1"

PropertyKind = Literal["assert", "assume", "cover"]
ObligationStatus = Literal["not_run", "proved", "failed", "unknown"]


def _text(value: Any) -> Any:
    return "" if value is None else str(value)


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        for sep in ("；", ";", "、", "\n", ","):
            if sep in text:
                return [x.strip() for x in text.split(sep) if x.strip()]
        return [text]
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value)]


Text = Annotated[str, BeforeValidator(_text)]
StrList = Annotated[list[str], BeforeValidator(_str_list)]
ItemList = BeforeValidator(_list)


class FormalSourceAnchor(BaseModel):
    kind: str = "unknown"
    path: str = ""
    sha256: str = ""
    note: str = ""


class FormalProperty(BaseModel):
    """一条形式化性质：assert（必须成立）/ assume（环境约束）/ cover（可达性）。"""

    model_config = ConfigDict(populate_by_name=True)
    id: str
    name: Text = Field(
        default="", validation_alias=AliasChoices("name", "id", "title"))
    expression: Text = Field(
        default="", validation_alias=AliasChoices("expression", "expr", "property", "sva"))
    kind: PropertyKind = "assert"
    description: Text = Field(
        default="", validation_alias=AliasChoices("description", "statement", "intent"))


class ProofObligation(BaseModel):
    """证明义务：哪些性质必须被证明，以及当前状态（默认未运行）。"""

    model_config = ConfigDict(populate_by_name=True)
    id: str
    property_ids: StrList = Field(
        default_factory=list,
        validation_alias=AliasChoices("property_ids", "properties", "props"))
    status: ObligationStatus = "not_run"
    engine: Text = ""


class FormalPlan(BaseModel):
    """一个模块的形式化验证计划。"""

    schema_version: str = SCHEMA
    module: str
    clock: Text = "clk"
    reset: Text = "rst_n"
    properties: Annotated[list[FormalProperty], ItemList] = Field(default_factory=list)
    proof_obligations: Annotated[list[ProofObligation], ItemList] = Field(default_factory=list)
    engine_requirements: StrList = Field(default_factory=list)
    coverage_goals: StrList = Field(default_factory=list)
    notes: StrList = Field(default_factory=list)
    source_anchors: Annotated[list[FormalSourceAnchor], ItemList] = Field(default_factory=list)
    #: **是否真的跑过形式引擎**。没有引擎时如实写 false + 原因。
    engine: dict[str, Any] = Field(
        default_factory=lambda: {"ran": False, "reason": "no formal engine configured"})
    generated_at: str = ""
    generator: dict[str, Any] = Field(default_factory=dict)

    def canonical(self) -> str:
        doc = self.model_dump(
            mode="json",
            exclude={"generated_at", "generator", "engine"},
        )
        return json.dumps(doc, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    def counts(self) -> dict[str, int]:
        kinds = {"assert": 0, "assume": 0, "cover": 0}
        for prop in self.properties:
            kinds[prop.kind] = kinds.get(prop.kind, 0) + 1
        return {
            "properties": len(self.properties),
            "assert": kinds["assert"],
            "assume": kinds["assume"],
            "cover": kinds["cover"],
            "proof_obligations": len(self.proof_obligations),
            "unproved_obligations": sum(
                1 for o in self.proof_obligations if o.status != "proved"),
        }


__all__ = ["SCHEMA", "PropertyKind", "ObligationStatus", "FormalSourceAnchor",
           "FormalProperty", "ProofObligation", "FormalPlan"]
