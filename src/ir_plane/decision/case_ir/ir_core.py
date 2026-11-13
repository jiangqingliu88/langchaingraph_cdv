"""Case IR —— **逻辑用例（CASE）** 与分类树（CCAT）的身份模型。

方法学里的三层里，本模块只承担前两层：

    CCAT（分类树） → CASE（逻辑用例） → TST（可执行实例，派生的）

**TST 不是这里的第一等实体**：一条 CASE 会被回归跑成
`(test @ seed)` 的若干次执行，实例数由种子决定，写进 YAML 只会变成
每次改种子都要改模型。所以 TST 的 id 是**派生**的
（`TST-<test>@<seed>`），由 `tst_id()` 一处生成。

## 为什么 CASE 不直接从测试名来

回归任务名（`tp_npusch_d_queue_0_seed_6001`）是**执行细节**：改名、换种子、
换分级都会变。CASE 是逻辑身份，必须由模型声明（或由模型结构稳定合成），
否则“同一批用例换了个测试名”就变成另一批用例，跨 run 聚合直接断掉。

## 两种来源（见 `loader.py`）

  · `declared`    —— 模型里写了 `cases:` 段，按声明走（优先级最高）
  · `synthesized` —— 没写时按“每个维度一个 CASE”合成，**如实标注来源**，
                    不假装那是人设计出来的用例划分
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 身份字符串的唯一实现在 core.runtime.ids；这里 re-export，旧 import 不变。
from src.runtime_plane.core.runtime.ids import (  # noqa: F401
    case_id_of, ccat_id_of, evd_id_of, group_id_of, group_short,
    scb_id_of, slug, sva_id_of, tst_id_of,
)

SCHEMA = "case_ir_v1"

#: 合成来源的标记 —— 视图与门禁据此区分“人设计的用例”和“结构兜底”。
SOURCE_DECLARED = "declared"
SOURCE_SYNTHESIZED = "synthesized"
#: 从业务测试点表（xlsx）投影 —— 人写的"该测什么"是真源。
SOURCE_XLSX = "xlsx"

@dataclass
class CCatIR:
    """分类树节点（Case 分类树）。`parent` 为空表示根。"""
    id: str
    name: str = ""
    parent: str = ""
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name or self.id,
                "parent": self.parent, "description": self.description}


@dataclass
class CaseIR:
    """一条**逻辑用例** —— 四集合契约的容器。

    `groups` / `sva` / `scb` / `constraints` 是**必填结构**（见 `arch.md`）：
      · `groups` 非空，每项带 `cell` 与 `required_layers`；
      · `sva` / `scb` 可以是空列表，但字段必须存在，空要写 `not_applicable` 原因；
      · `constraints` 是约束 id（`p_*` 策略名），空列表 = 该维度没有绑定约束
        （不编 id）；
      · 每项都带 `cell` —— 证据最后要落回 Cell 枢纽。

    `tests` 是它落到 UVM 上的测试类名；`dimensions` 是它归属的功能维度。
    """
    id: str
    name: str = ""
    categories: List[str] = field(default_factory=list)
    feats: List[str] = field(default_factory=list)
    tests: List[str] = field(default_factory=list)
    cells: List[str] = field(default_factory=list)
    dimensions: List[str] = field(default_factory=list)
    owner: str = ""
    priority: str = ""
    tags: List[str] = field(default_factory=list)
    description: str = ""
    # ── 业务测试点表（xlsx）的原文字段 —— 不在投影时丢掉 ──
    #: `TestName`：人写的测试意图（常是 `func_cov监测` / 场景名，不一定是 UVM 类）。
    test_intent: str = ""
    #: `TestNum`：业务表声明的测试数量/权重（可为 0、整数或原始文本）。
    test_count: Any = None
    doc_section: str = ""
    chapter: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    source: str = SOURCE_DECLARED
    #: `[{group, cell, required_layers}]` —— 一条 case 可同时占多个组/多个阶段。
    groups: List[Dict[str, Any]] = field(default_factory=list)
    #: `[{id, cell, required, tp_ids}]`
    sva: List[Dict[str, Any]] = field(default_factory=list)
    #: `[{id, cell, required, checks}]`
    scb: List[Dict[str, Any]] = field(default_factory=list)
    #: **约束 id**（`p_*` 策略名）—— 这条用例的激励受哪些约束塑造。
    #: 归属来自 `coverage_plan.constraint_backing.policies[].dimensions` 与
    #: 本 case 的维度交集；**没有声明就不编**（空列表是事实）。
    constraints: List[str] = field(default_factory=list)
    #: `{sva: 原因, scb: 原因}` —— 空集合必须解释（"没声明"≠"不需要"）。
    not_applicable: Dict[str, str] = field(default_factory=dict)
    #: **人工豁免**：`[{id, scope[], owner, approver, reason, expires}]`。
    #: 只有显式豁免才允许把某项标成 NOT_APPLICABLE —— 没有审批人就是没豁免。
    waivers: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name or self.id,
            "categories": list(self.categories),
            "feats": list(self.feats),
            "tests": list(self.tests),
            "cells": list(self.cells),
            "dimensions": list(self.dimensions),
            "owner": self.owner,
            "priority": self.priority,
            "tags": list(self.tags),
            "test_intent": self.test_intent,
            "test_count": self.test_count,
            "doc_section": self.doc_section,
            "chapter": self.chapter,
            "provenance": dict(self.provenance),
            "groups": [dict(g) for g in self.groups],
            "sva": [dict(s) for s in self.sva],
            "scb": [dict(s) for s in self.scb],
            "constraints": list(self.constraints),
            "not_applicable": dict(self.not_applicable),
            "waivers": [dict(w) for w in self.waivers],
            "description": self.description,
            "source": self.source,
        }


@dataclass
class CaseDoc:
    """一份 Case IR：分类树 + 用例表 + 两张反查索引。"""
    module: str = ""
    schema: str = SCHEMA
    source: str = SOURCE_DECLARED
    categories: List[CCatIR] = field(default_factory=list)
    cases: List[CaseIR] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    #: `{policy_id: {backed, dimensions, reason}}` —— 约束注册表（来自
    #: `coverage_plan.constraint_backing`）。视图/审计据此回答"这条约束是真
    #: 编译进模型了，还是空骨架"。
    constraint_backing: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # ── 反查索引（懒建，读端只管用）─────────────────────────────
    _by_test: Dict[str, List[str]] = field(default_factory=dict, repr=False)
    _by_dimension: Dict[str, List[str]] = field(default_factory=dict, repr=False)
    _by_id: Dict[str, CaseIR] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.reindex()

    def reindex(self) -> None:
        by_test: Dict[str, List[str]] = {}
        by_dim: Dict[str, List[str]] = {}
        by_id: Dict[str, CaseIR] = {}
        for case in self.cases:
            by_id[case.id] = case
            for test in case.tests:
                by_test.setdefault(test, []).append(case.id)
            for dim in case.dimensions:
                by_dim.setdefault(dim, []).append(case.id)
        self._by_test, self._by_dimension, self._by_id = by_test, by_dim, by_id

    # ── 查询 ──────────────────────────────────────────────────
    @property
    def empty(self) -> bool:
        return not self.cases

    def get(self, case_id: str) -> Optional[CaseIR]:
        return self._by_id.get(case_id)

    def cases_for_test(self, test: str) -> List[str]:
        return list(self._by_test.get(test, []))

    def cases_for_dimension(self, dimension: str) -> List[str]:
        return list(self._by_dimension.get(dimension, []))

    def resolve_all(self, *, test: str = "", dimension: str = "") -> List[str]:
        """test 优先、维度兜底 → **全部**匹配的 case_id（去重保序）。

        一条 TP（`维度 × 取值`）可以被多条业务 CASE 共享：CASE A 绑
        `D_type`，CASE B 同时绑 `D_type + D_dep`，则 `D_type` 下的 TP
        同属 A、B —— 不能只取第一个，否则 B 永远没有证据。

        都没有就返回空列表 —— **不编一个默认 CASE**：没有身份就是没有身份，
        让门禁（`CASE_MISSING`）去报，而不是造一个看起来对的。
        """
        for ids in (self._by_test.get(test) if test else None,
                    self._by_dimension.get(dimension) if dimension else None):
            if ids:
                return list(dict.fromkeys(ids))
        return []

    def resolve(self, *, test: str = "", dimension: str = "") -> str:
        """兼容旧读端：返回 `resolve_all` 的**主身份**（首项）。"""
        ids = self.resolve_all(test=test, dimension=dimension)
        return ids[0] if ids else ""

    def category_path(self, case_id: str) -> List[str]:
        """从根到该 CASE 的分类链（ID 列表）—— 分类树视图用。"""
        case = self._by_id.get(case_id)
        if case is None or not case.categories:
            return []
        parent_of = {c.id: c.parent for c in self.categories}
        chain: List[str] = []
        for start in case.categories[:1]:
            node = start
            seen = set()
            while node and node not in seen:
                seen.add(node)
                chain.append(node)
                node = parent_of.get(node, "")
            chain.reverse()
        return chain

    # ── 序列化 ────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "module": self.module,
            "source": self.source,
            "counts": {
                "categories": len(self.categories),
                "cases": len(self.cases),
                "declared": sum(1 for c in self.cases
                                if c.source == SOURCE_DECLARED),
                "synthesized": sum(1 for c in self.cases
                                   if c.source == SOURCE_SYNTHESIZED),
                "xlsx": sum(1 for c in self.cases if c.source == SOURCE_XLSX),
                # 三集合契约的规模 —— 门禁与视图都读这一份
                "cases_without_groups": sum(1 for c in self.cases if not c.groups),
                "groups": len({g.get("group") for c in self.cases
                               for g in c.groups if g.get("group")}),
                "sva": len({s.get("id") for c in self.cases
                            for s in c.sva if s.get("id")}),
                "scb": len({s.get("id") for c in self.cases
                            for s in c.scb if s.get("id")}),
                "constraints": len({cid for c in self.cases
                                    for cid in c.constraints if cid}),
            },
            "categories": [c.to_dict() for c in self.categories],
            "cases": [c.to_dict() for c in self.cases],
            "constraint_backing": dict(self.constraint_backing),
            "notes": list(self.notes),
        }
