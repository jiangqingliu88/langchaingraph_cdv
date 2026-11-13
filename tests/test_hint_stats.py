"""策略提示（hint）的**结局统计** —— prompt 库能不能淘汰，全看这张表。

prompt 库腐烂得比规则库更隐蔽：hint 是**文本**，加一条没人看得出来，于是越加越长，
最后把 prompt 撑满还说不清哪句有用。要能淘汰就得回答"**有它比没它好多少**"——
只记"用了哪些 id"不够（那是上一轮做的），得记**结局**。
"""
from __future__ import annotations

import pytest

from src.knowledge.hint_stats import HintStats, record_hint_outcome


@pytest.fixture()
def stats(tmp_path):
    return HintStats(str(tmp_path / "hint_stats.db"))


class TestRecord:

    def test_trials_and_successes_accumulate(self, stats):
        stats.record(["hp_reset"], True, run_id="r1")
        stats.record(["hp_reset"], False, run_id="r2")
        row = stats.stats()["hints"][0]
        assert (row["trials"], row["compiled_ok"]) == (2, 1)
        assert row["rate"] == 0.5
        assert row["first_run"] == "r1" and row["last_run"] == "r2"

    def test_every_injected_id_counts_as_a_trial(self, stats):
        """一次生成注入了几条就记几条 —— 如实反映当前能力边界（一次全注入，
        效果拆不到单条头上；要拆得改成"分组注入 + 对照"）。"""
        assert stats.record(["a", "b", "c"], True) == 3
        assert len(stats.stats()["hints"]) == 3

    def test_empty_ids_is_a_noop(self, stats):
        assert stats.record([], True) == 0
        assert stats.stats()["hints"] == []


class TestIneffective:

    def test_never_compiled_after_enough_trials_is_flagged(self, stats):
        for _ in range(2):
            stats.record(["hp_bad"], False)
        assert [h["hint_id"] for h in stats.stats()["ineffective"]] == ["hp_bad"]

    def test_one_failure_is_not_enough_to_condemn(self, stats):
        """试过一次就判死太急 —— 一次失败可能是运气。"""
        stats.record(["hp_new"], False)
        assert stats.stats()["ineffective"] == []

    def test_a_hint_that_ever_worked_is_kept(self, stats):
        stats.record(["hp_ok"], False)
        stats.record(["hp_ok"], True)
        assert stats.stats()["ineffective"] == []


class TestNeverRaises:

    def test_recording_failure_is_swallowed(self, tmp_path):
        """统计是**旁路**，不该拖垮生成。"""
        assert record_hint_outcome(["a"], True,
                                   db_path=str(tmp_path / "no" / "such" / "d.db")) >= 0
