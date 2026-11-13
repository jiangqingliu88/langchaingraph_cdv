"""Verification OS v3 —— 契约 / 义务 / 事实 的强类型模型。

计划见 `docs/design/contract_driven_architecture_v3.md`。这里只做三件事：

    L1 Contract   ── 可编辑源（由 case_ir / xlsx 编译而来，带规范哈希）
    L2 Obligation ── 契约展开出的"必须清偿的证明义务"，带谓词
    L3 Fact       ── 只追加的事实（原子），以及它们的**批次包** FactBundle

三条硬约束在类型层就钉住：

1. `Predicate.fact_type` 必须属于 `FACT_TYPES` —— 规则不能引用未声明的事实类型；
2. `Fact.contract_hash` 必须等于契约哈希 —— 事实只对**那一版契约**有效；
3. `FactBundle` 是**批次**写入单位（一次执行一个包），账本锁按包争用，
   不是每条事实抢一次锁（并行仿真下的锁竞争就出在这里）。

Pydantic 在这里不只是校验：它把"契约长什么样"写成代码，`compile_obligations`
和 `derive` 都只吃这些对象，不再靠 dict 的键名约定。
"""
from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

SCHEMA_CONTRACT = "contract_v2"
SCHEMA_OBLIGATION = "obligation_v1"
SCHEMA_FACT = "fact_v1"


class FactType(str, Enum):
    """账本里允许的事实类型 —— **唯一清单**（规则只能引用这里面的）。"""
    BIN_HIT = "bin_hit"          # (case, tp, cp, bin) → 命中次数
    SVA_RESULT = "sva_result"    # (case, sva id) → fail 次数 / 状态
    SCB_RESULT = "scb_result"    # (case, sb id) → exec / matched / mismatched
    TIMING = "timing"            # (case) → 时序是否检查 / 是否超窗
    PATH_RESULT = "path_result"  # (case, path) → 路径证据（后端未接时 PENDING）
    WAVE = "wave"                # (case) → 波形路径
    LOG = "log"                  # (case) → 日志路径 / UVM_ERROR
    TP_ATTR = "tp_attr"          # (tp) → kind / observe_only（契约派生属性）
    #: **契约锚点**：证据产生前冻结的契约版本（不可回改的承诺）。
    #: 不是证明义务，不参与 derive；只作为账本里的版本锚。
    CONTRACT_ANCHOR = "contract_anchor"


FACT_TYPES = frozenset(t.value for t in FactType)

#: 证据层（与 tp_evidence 同口径）。
LAYERS = ("functional", "timing", "data", "path")


class CaseStatus(str, Enum):
    PROVEN = "PROVEN"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    PENDING_BACKEND = "PENDING_BACKEND"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_EXECUTED = "NOT_EXECUTED"


#: 判定用的"好坏"排序（越大越差）；两个 NA 类等价。
STATUS_RANK = {"PROVEN": 0, "NOT_APPLICABLE": 0, "PARTIAL": 1,
               "PENDING_BACKEND": 2, "NOT_EXECUTED": 3, "MISSING": 4}


def worst(statuses) -> str:
    real = [str(s) for s in statuses if s and str(s) != "NOT_APPLICABLE"]
    if not real:
        return CaseStatus.NOT_APPLICABLE.value
    return max(real, key=lambda s: STATUS_RANK.get(s, 4))


def canonical_hash(doc: Any) -> str:
    """规范哈希：键序固定、无空白差异 —— 契约与事实链都用它。"""
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class GroupSpec(BaseModel):
    group: str
    name: str = ""
    description: str = ""
    coverage_type: str = ""
    scope: str = ""
    cell: str = ""
    stage: str = ""
    required_layers: List[str] = Field(default_factory=lambda: ["functional"])
    coverpoints: List[str] = Field(default_factory=list)
    requirements: List[str] = Field(default_factory=list)
    checks: List[str] = Field(default_factory=list)
    tp_ids: List[str] = Field(default_factory=list)

    @field_validator("required_layers")
    @classmethod
    def _layers_known(cls, value: List[str]) -> List[str]:
        unknown = [v for v in value if v not in LAYERS]
        if unknown:
            raise ValueError(f"未知证据层: {unknown}（允许: {list(LAYERS)}）")
        return value


class SvaSpec(BaseModel):
    id: str
    name: str = ""
    expr: str = ""
    message: str = ""
    cell: str = ""
    required: bool = True
    tp_ids: List[str] = Field(default_factory=list)


class ScbSpec(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    model: str = ""
    checks: List[str] = Field(default_factory=list)
    cell: str = ""
    required: bool = True
    evidence: str = "auto"          # auto | aggregate | log
    tp_ids: List[str] = Field(default_factory=list)


class CaseSpec(BaseModel):
    id: str
    groups: List[GroupSpec] = Field(default_factory=list)
    sva: List[SvaSpec] = Field(default_factory=list)
    scb: List[ScbSpec] = Field(default_factory=list)
    #: **约束 id**（`p_*` 策略名）—— 用例的激励由哪些约束塑造。它进契约哈希：
    #: 约束换版后，旧证据不再对得上这一版契约。
    constraints: List[str] = Field(default_factory=list)
    not_applicable: Dict[str, str] = Field(default_factory=dict)


class Contract(BaseModel):
    """L1 —— 一份可编译、可哈希的验证契约。"""
    schema_id: str = Field(default=SCHEMA_CONTRACT, alias="schema")
    id: str = ""
    module: str = ""
    hash: str = ""
    cases: List[CaseSpec] = Field(default_factory=list)
    #: **约束内容指纹**（`p_*` id → 策略定义的规范哈希）。只把 id 放进
    #: `CaseSpec.constraints` 会漏掉"约束逻辑变了但 id 没变"—— 那样旧证据
    #: 会被错误地认为仍然有效。内容指纹一起进契约哈希。
    constraint_fingerprints: Dict[str, str] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    def compute_hash(self) -> str:
        """内容哈希：**不含 `hash` 与 `id`**（id 由 hash 派生，不能反过来参与）。

        否则"算 hash → 用 hash 生成 id → 再算 hash"会得到两个不同的值，
        读回来的契约永远对不上清单（实测踩过）。
        """
        return canonical_hash(
            self.model_dump(by_alias=True, exclude={"hash", "id"}))

    def seal(self) -> "Contract":
        """算好规范哈希再封存 —— 之后任何改动都会让 `contract.hash` 对不上。"""
        self.hash = self.compute_hash()
        self.id = self.id or f"CT-{self.module or 'MOD'}-{self.hash[:12]}"
        return self


class Predicate(BaseModel):
    """义务的判据：**引用一种已声明的事实类型 + 一个算子 + 定位条件**。"""
    fact_type: FactType
    op: str
    where: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("fact_type", mode="before")
    @classmethod
    def _known_fact_type(cls, value: Any) -> Any:
        if str(value) not in FACT_TYPES:
            raise ValueError(f"未知事实类型: {value}（允许: {sorted(FACT_TYPES)}）")
        return value


class Obligation(BaseModel):
    """L2 —— 一条必须被清偿的证明义务。"""
    schema_id: str = Field(default=SCHEMA_OBLIGATION, alias="schema")
    obligation_id: str
    contract_id: str
    kind: str                      # group_layer | sva | scb
    case: str
    subject: Dict[str, Any] = Field(default_factory=dict)
    predicate: Predicate
    required: bool = True

    model_config = {"populate_by_name": True}


class Fact(BaseModel):
    """L3 —— 一条原子事实（只追加，不修改）。"""
    schema_id: str = Field(default=SCHEMA_FACT, alias="schema")
    fact_id: str = ""
    type: FactType
    contract_hash: str
    run_id: str = ""
    tst_id: str = ""
    seed: Optional[int] = None
    subject: Dict[str, Any] = Field(default_factory=dict)
    value: Dict[str, Any] = Field(default_factory=dict)
    producer: str = ""
    # ── 证据闭环（Architecture 3.x）：事实类别与来源 ──
    # 旧账本没有这些字段 → 默认 OBSERVED / engine，保持兼容。
    fact_class: str = "OBSERVED"       # OBSERVED | DERIVED | HYPOTHESIS | HUMAN_DECISION | TOOL_RECEIPT
    producer_class: str = "engine"     # engine | human | agent
    claim_ids: List[str] = Field(default_factory=list)
    actor: str = ""
    prev_hash: str = ""
    hash: str = ""

    model_config = {"populate_by_name": True}

    def seal(self, prev_hash: str) -> "Fact":
        self.prev_hash = prev_hash
        self.hash = canonical_hash(self.model_dump(by_alias=True,
                                                   exclude={"hash", "prev_hash"}))
        return self


class FactBundle(BaseModel):
    """L3 的**写入单位**：一次执行产生的全部原子事实。

    并行仿真下按包争用一次锁，而不是每条事实抢一次 —— 这是计划里
    "账本并发"那条建议的落点。
    """
    bundle_id: str
    run_id: str = ""
    tst_id: str = ""
    seed: Optional[int] = None
    contract_hash: str = ""
    actor: str = ""
    facts: List[Fact] = Field(default_factory=list)

    def digest(self) -> str:
        # **向后兼容**：新增的证据类别字段在取默认值时从摘要里剔除 ——
        # 否则老 run 的 bundle 会因为“多了几个默认字段”被判成新包而重复入账。
        defaults = {"fact_class": "OBSERVED", "producer_class": "engine",
                    "claim_ids": [], "actor": ""}
        rows = []
        for fact in self.facts:
            row = fact.model_dump(by_alias=True, exclude={"hash", "prev_hash"})
            for key, value in defaults.items():
                if row.get(key) == value:
                    row.pop(key, None)
            rows.append(row)
        return canonical_hash({
            "tst": self.tst_id, "seed": self.seed, "contract": self.contract_hash,
            "facts": rows,
        })


def contract_from_case_ir(case_ir: Dict[str, Any]) -> Contract:
    """`case_ir_v1`（现有产物）→ `Contract v2`。

    M0 阶段不换产物形态：直接从 case_ir 适配出契约对象，影子校验用它。
    """
    cases: List[CaseSpec] = []
    for raw in case_ir.get("cases") or []:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        cases.append(CaseSpec(
            id=str(raw["id"]),
            groups=[GroupSpec(**{k: g.get(k) for k in GroupSpec.model_fields
                                 if k in g}) for g in raw.get("groups") or []],
            sva=[SvaSpec(**{k: s.get(k) for k in SvaSpec.model_fields
                            if k in s}) for s in raw.get("sva") or []],
            scb=[ScbSpec(**{k: s.get(k) for k in ScbSpec.model_fields
                            if k in s}) for s in raw.get("scb") or []],
            constraints=[str(c) for c in raw.get("constraints") or [] if c],
            not_applicable=dict(raw.get("not_applicable") or {}),
        ))
    # 约束 id 之外，把**策略内容**也冻进契约哈希（id 不变、逻辑变了要能发现）。
    fingerprints = {
        str(pid): canonical_hash(detail)
        for pid, detail in (case_ir.get("constraint_backing") or {}).items()
        if isinstance(detail, dict)
    }
    return Contract(module=str(case_ir.get("module") or ""), cases=cases,
                    constraint_fingerprints=fingerprints).seal()
