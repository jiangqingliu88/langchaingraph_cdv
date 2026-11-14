"""Mental IR 的机器可读模型（`mental_ir_v1`）。

设计原则：
  · **只记录理解，不记录执行事实** —— 执行事实归 Execution/Evidence IR；
  · **不确定的显式写出来** —— 拿不准的需求进 `ambiguities`，不要编成目标；
  · **可复查** —— 每条都带 id 与来源锚点，哈希只覆盖稳定内容（不含时间戳）。
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

SCHEMA = "mental_ir_v1"

Priority = Literal["P0", "P1", "P2", "P3"]
Severity = Literal["low", "medium", "high"]


def _str_list(value: Any) -> list[str]:
    """LLM 常把列表写成一句话（"SCB；SVA"）——宽容成列表，不因此整份作废。"""
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


def _item_list(value: Any) -> list[Any]:
    """单个对象 → 单元素列表；None → 空列表。"""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _priority(value: Any) -> Any:
    """P0..P3 也认 high/medium/low、高/中/低。"""
    text = str(value or "").strip()
    if text.upper() in ("P0", "P1", "P2", "P3"):
        return text.upper()
    return {"高": "P0", "中": "P1", "低": "P2", "high": "P0", "medium": "P1", "low": "P2"}.get(text.lower(), "P1")


def _severity(value: Any) -> Any:
    text = str(value or "").strip()
    if text.lower() in ("low", "medium", "high", "critical"):
        return "high" if text.lower() == "critical" else text.lower()
    return {"低": "low", "中": "medium", "高": "high"}.get(text, "medium")


def _bool(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("是", "true", "yes", "y", "1"):
            return True
        if text in ("否", "false", "no", "n", "0"):
            return False
    return value


StrList = Annotated[list[str], BeforeValidator(_str_list)]
BoolLike = Annotated[bool, BeforeValidator(_bool)]


class SourceAnchor(BaseModel):
    """这条理解从哪来：spec / case_ir / testpoints …（内容哈希可追溯）。"""

    kind: str = "unknown"
    path: str = ""
    sha256: str = ""
    note: str = ""


class Goal(BaseModel):
    """验证目标：设计必须被证明成立的核心主张。"""

    model_config = ConfigDict(populate_by_name=True)
    id: str
    statement: str = Field(validation_alias=AliasChoices("statement", "goal", "description", "title", "name"))
    priority: Annotated[Priority, BeforeValidator(_priority)] = "P1"
    source_refs: StrList = Field(default_factory=list, validation_alias=AliasChoices("source_refs", "refs", "sources"))


class Assumption(BaseModel):
    """继续验证所依赖、但 spec 没有显式保证的前提。"""

    model_config = ConfigDict(populate_by_name=True)
    id: str
    statement: str = Field(validation_alias=AliasChoices("statement", "assumption", "description", "title", "name"))
    rationale: str = Field(default="", validation_alias=AliasChoices("rationale", "reason", "why"))
    risk_if_wrong: str = Field(default="", validation_alias=AliasChoices("risk_if_wrong", "impact", "consequence"))


class Ambiguity(BaseModel):
    """规格没写清、会影响验证策略的问题；`blocking` 表示必须先澄清。"""

    model_config = ConfigDict(populate_by_name=True)
    id: str
    question: str = Field(
        validation_alias=AliasChoices("question", "statement", "description", "issue", "title", "name")
    )
    why_it_matters: str = Field(
        default="", validation_alias=AliasChoices("why_it_matters", "rationale", "impact", "why")
    )
    blocking: BoolLike = False
    needs_human: BoolLike = True


class VerificationIntent(BaseModel):
    """可执行的验证意图：用什么证据证明哪个目标。"""

    model_config = ConfigDict(populate_by_name=True)
    id: str
    statement: str = Field(validation_alias=AliasChoices("statement", "intent", "description", "title", "name"))
    goal_ids: StrList = Field(default_factory=list, validation_alias=AliasChoices("goal_ids", "goals", "related_goals"))
    evidence_expected: StrList = Field(
        default_factory=list, validation_alias=AliasChoices("evidence_expected", "evidence", "expected_evidence")
    )


class Risk(BaseModel):
    """设计或验证过程的风险及缓解方式。"""

    model_config = ConfigDict(populate_by_name=True)
    id: str
    description: str = Field(
        validation_alias=AliasChoices(
            "description", "statement", "risk", "risk_description", "issue", "title", "name", "concern"
        )
    )
    severity: Annotated[Severity, BeforeValidator(_severity)] = "medium"
    mitigation: str = Field(
        default="", validation_alias=AliasChoices("mitigation", "resolution", "plan", "fix", "action")
    )


class MentalIR(BaseModel):
    """一个模块的「心智模型」快照。"""

    schema_version: str = SCHEMA
    module: str
    generated_at: str = ""
    #: 谁生成的：prompt 版本、provider/model、attempt —— 不参与哈希。
    generator: dict[str, Any] = Field(default_factory=dict)
    source_anchors: Annotated[list[SourceAnchor], BeforeValidator(_item_list)] = Field(default_factory=list)
    goals: Annotated[list[Goal], BeforeValidator(_item_list)] = Field(default_factory=list)
    assumptions: Annotated[list[Assumption], BeforeValidator(_item_list)] = Field(default_factory=list)
    ambiguities: Annotated[list[Ambiguity], BeforeValidator(_item_list)] = Field(default_factory=list)
    verification_intents: Annotated[list[VerificationIntent], BeforeValidator(_item_list)] = Field(default_factory=list)
    risks: Annotated[list[Risk], BeforeValidator(_item_list)] = Field(default_factory=list)
    notes: StrList = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self):
        """id 必须在整份 Mental IR 内唯一 —— 后续引用（goal_ids）靠它定位。"""
        seen = set()
        items: list[Goal | Assumption | Ambiguity | VerificationIntent | Risk] = [
            *self.goals,
            *self.assumptions,
            *self.ambiguities,
            *self.verification_intents,
            *self.risks,
        ]
        for item in items:
            if item.id in seen:
                raise ValueError(f"Mental IR id 重复: {item.id!r}")
            seen.add(item.id)
        return self

    # ── 稳定哈希 ──────────────────────────────────────────────
    def canonical(self) -> str:
        """规范 JSON：不含时间戳/生成器信息，可用于比对两次理解的漂移。"""
        doc = self.model_dump(mode="json", exclude={"generated_at", "generator"})
        return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    def counts(self) -> dict[str, int]:
        return {
            "goals": len(self.goals),
            "assumptions": len(self.assumptions),
            "ambiguities": len(self.ambiguities),
            "blocking_ambiguities": sum(1 for a in self.ambiguities if a.blocking),
            "verification_intents": len(self.verification_intents),
            "risks": len(self.risks),
        }


def canonical_hash(doc: dict[str, Any]) -> str:
    """任意 Mental IR 文档 → 稳定哈希（读回 JSON 时用）。"""
    return MentalIR.model_validate(doc).digest()


__all__ = [
    "SCHEMA",
    "Priority",
    "Severity",
    "SourceAnchor",
    "Goal",
    "Assumption",
    "Ambiguity",
    "VerificationIntent",
    "Risk",
    "MentalIR",
    "canonical_hash",
]
