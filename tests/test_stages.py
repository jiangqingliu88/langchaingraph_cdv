"""阶段表与图节点的一致性 —— 「加了节点忘了加元数据」必须是一条红测试。

`stages.py` 刻意不 import `graph.py`（否则为了读一张元数据表，要把 langgraph
和决策引擎全拖进来）。代价是两张表可能漂移，所以由本文件钉住。
"""
from __future__ import annotations

import pytest

from src.layers.l2_orchestration import stages
from src.layers.l2_orchestration.graph import NODE_NAMES
from src.layers.l2_orchestration.state import PHASE_OWNERS


class TestCoverage:
    def test_every_graph_node_has_a_spec(self):
        missing = sorted(set(NODE_NAMES) - set(stages.all_ids()))
        assert not missing, (
            f"这些图节点没有显示元数据：{missing}；"
            "在 src/layers/l2_orchestration/stages.py 的 STAGES 里补上")

    def test_no_spec_for_a_node_that_does_not_exist(self):
        """反向也要查：STAGES 里的 id 必须是真节点，否则界面会画出一个永远不亮的格子。"""
        extra = sorted(set(stages.all_ids()) - set(NODE_NAMES))
        assert not extra, f"这些阶段在 graph.py 里没有对应节点：{extra}"

    def test_ids_are_unique(self):
        ids = [s.id for s in stages.STAGES]
        assert len(ids) == len(set(ids))


class TestShape:
    def test_every_spec_declares_a_known_group(self):
        for spec in stages.STAGES:
            assert spec.group in stages.STAGE_GROUPS, spec.id

    def test_every_spec_has_a_title(self):
        for spec in stages.STAGES:
            assert spec.title and spec.title != spec.id, spec.id

    def test_grouped_covers_every_stage_exactly_once(self):
        seen = [s.id for _, _, members in stages.grouped() for s in members]
        assert sorted(seen) == sorted(stages.all_ids())


class TestOwnerNormalisation:
    """`PHASE_OWNERS` 里属主名带轮次后缀（`ops_r`），节点名不带（`ops`）。"""

    @pytest.mark.parametrize("owner,stage", [("ops_r", "ops"),
                                             ("coverage_r", "coverage"),
                                             ("design", "design")])
    def test_normalisation(self, owner, stage):
        assert stages._owner_matches(owner, stage)

    def test_phase_owners_all_resolve_to_a_stage(self):
        """每个状态字段的属主都得能落到某个阶段上。

        落不上意味着有个节点在写状态，但阶段表里没有它 —— 界面会丢掉这段进度。
        """
        unknown = {owner for owner in PHASE_OWNERS.values()
                   if owner and not stages.get(owner.rstrip("_r"))}
        assert not unknown, f"这些属主在阶段表里找不到对应阶段：{sorted(unknown)}"


class TestLookups:
    def test_title_of_unknown_id_returns_the_id(self):
        """未知节点原样返回 id：界面上看到一个 id 好过看到空白（后者才查不出问题）。"""
        assert stages.title_of("no_such_node") == "no_such_node"

    def test_title_of_known_id_is_chinese(self):
        assert stages.title_of("ops") == "编译与仿真回归"

    def test_outputs_come_from_phase_owners(self):
        """归属只有一份：outputs 由 PHASE_OWNERS 反查，不是另写一张表。"""
        assert stages.outputs_of("ops") == sorted(
            f for f, n in PHASE_OWNERS.items() if n == "ops_r")

    def test_round_scoped_reflects_the_table(self):
        assert stages.is_round_scoped("ops")
        assert not stages.is_round_scoped("design")

    def test_executor_of(self):
        assert stages.executor_of("coverage") == "coverage"
        assert stages.executor_of("init") == ""
