"""coverage 归因校准库单测：动作成效 / 归因准确率 / unreachable 黑名单。"""
from pathlib import Path

import pytest

from src.knowledge.coverage_experience import CoverageExperienceStore


@pytest.fixture
def store(tmp_path):
    s = CoverageExperienceStore(db_path=tmp_path / "coverage_experience.db")
    yield s
    s.close()


def test_record_round_computes_delta_and_improved(store):
    store.record_round(1, "RELAX_CONSTRAINT", "constraint gap", ["constraint"], 70.0, 78.0)
    rounds = store.list_rounds()
    assert len(rounds) == 1
    assert rounds[0]["delta"] == 8.0
    assert rounds[0]["improved"] is True


def test_reason_accuracy_aggregates_confidence(store):
    # constraint 归因 2 次，1 次改善 → 置信度 0.5
    store.record_round(1, "RELAX_CONSTRAINT", "", ["constraint"], 70.0, 78.0)
    store.record_round(2, "RELAX_CONSTRAINT", "", ["constraint"], 78.0, 78.0)
    acc = store.reason_accuracy()
    assert acc["constraint"]["trials"] == 2
    assert acc["constraint"]["improved"] == 1
    assert acc["constraint"]["confidence"] == 0.5


def test_action_effectiveness_avg_delta(store):
    store.record_round(1, "EXPAND_SEEDS", "", [], 70.0, 80.0)
    store.record_round(2, "EXPAND_SEEDS", "", [], 80.0, 85.0)
    eff = store.action_effectiveness()
    assert eff["EXPAND_SEEDS"]["trials"] == 2
    assert eff["EXPAND_SEEDS"]["improve_rate"] == 1.0
    assert eff["EXPAND_SEEDS"]["avg_delta"] == 7.5


def test_unreachable_strike_and_blacklist(store):
    # REFACTOR_RTL 3 次未改善 → 维度进黑名单
    for i in range(3):
        store.record_round(i + 1, "REFACTOR_RTL", "unreachable", ["unreachable"],
                           50.0, 50.0, unreachable_dims=["toggle"])
    assert store.is_unreachable_blacklisted("toggle")
    assert "toggle" in store.get_blacklist()


def test_unreachable_success_resets_strike(store):
    # 前两次失败，第三次改善 → strike 清零，不进黑名单
    for i in range(2):
        store.record_round(i + 1, "REFACTOR_RTL", "", ["unreachable"],
                           50.0, 50.0, unreachable_dims=["branch"])
    store.record_round(3, "REFACTOR_RTL", "", ["unreachable"],
                       50.0, 60.0, unreachable_dims=["branch"])
    assert not store.is_unreachable_blacklisted("branch")
    assert "branch" not in store.get_blacklist()


def test_stats(store):
    store.record_round(1, "GENERATE_DIRECTED_TEST", "", ["unstimulated"], 60.0, 65.0)
    s = store.stats()
    assert s["rounds"] == 1
    assert s["blacklisted"] == 0


# ══════════════════════════════════════════════════════════════
# 动作来源分桶 —— 不让蒸馏学出幸存者偏差
# ══════════════════════════════════════════════════════════════

class TestTheActionSourceIsRecordedAndFilters:
    """每轮要记下**这个动作是谁定的**，统计要能按来源筛。

    ## 不分来源会怎样（实测过的那条）

    RL 提名 A、规则当场退成 B —— 那一轮照样以 **B** 的名字记一条。于是 A 的
    "历史改善率"里混进一堆它**根本没被采用**的轮次。L5 蒸馏据此算权重，学到的是
    "哪个动作被提名过"，不是"哪个动作真的有用"。这是典型的幸存者偏差：
    **没生效过的那些从未被证伪**，而它们恰恰是最该被剔除的样本。
    """

    def test_the_source_lands_in_the_row(self, store):
        store.record_round(1, "EXPAND_SEEDS", "", [], 0.0, 1.0, source="rl_suggested")
        assert store.list_rounds()[0]["source"] == "rl_suggested"

    def test_the_default_is_unknown_not_rule(self, store):
        """缺省是 `''`（**来源未知**），不是 `rule`。

        老调用方 / 老数据都没记来源 —— 把它们算成"规则决定"会让一个**未知**
        的东西冒充已知，而蒸馏正是要按来源筛。
        """
        store.record_round(1, "EXPAND_SEEDS", "", [], 0.0, 1.0)
        assert store.list_rounds()[0]["source"] == ""

    def test_filtering_by_source_gives_a_different_number(self, store):
        """**本组的要点**：分来源与不分来源的数字必须不同 —— 否则白改。

        三条 `EXPAND_SEEDS`：RL 采纳的 2 条（1 涨 1 没涨）、规则的 1 条（涨）。
        全量 2/3 → 0.667；只 RL → 1/2 → 0.5。**两个数不同**，蒸馏要的是后者。
        """
        store.record_round(1, "EXPAND_SEEDS", "", [], 0, 2.0, source="rl_suggested")
        store.record_round(2, "EXPAND_SEEDS", "", [], 0, 0.0, source="rl_suggested")
        store.record_round(3, "EXPAND_SEEDS", "", [], 0, 5.0, source="rule")
        assert store.action_effectiveness()["EXPAND_SEEDS"]["improve_rate"] == 0.667
        rl = store.action_effectiveness(source="rl_suggested")["EXPAND_SEEDS"]
        assert rl["improve_rate"] == 0.5 and rl["trials"] == 2

    def test_an_unknown_source_filters_to_empty(self, store):
        """没记过来源的库，按 `rl_suggested` 筛出来是空 —— **不是全量**。"""
        store.record_round(1, "EXPAND_SEEDS", "", [], 0, 1.0)
        assert store.action_effectiveness(source="rl_suggested") == {}

    def test_an_old_db_without_the_column_is_migrated(self, tmp_path):
        """老库没有 `source` 列 → 连上时补出来，老行是 `''`（来源未知）。

        `CREATE TABLE IF NOT EXISTS` 对已存在的表什么都不做，所以后加的列必须
        在建表语句之外补一次 —— 不补的话这里每一次 INSERT 都会
        `no such column: source`。
        """
        import sqlite3

        db = tmp_path / "old.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(
            # 与真 schema 同形，**只少 `source` 列** —— 那正是要验的迁移目标
            "CREATE TABLE coverage_rounds ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " round_num INTEGER NOT NULL, action_type TEXT NOT NULL DEFAULT '',"
            " reason TEXT DEFAULT '', gap_reasons TEXT DEFAULT '[]',"
            " prev_coverage REAL DEFAULT 0, new_coverage REAL DEFAULT 0,"
            " delta REAL DEFAULT 0, improved INTEGER DEFAULT 0,"
            " created_at TEXT DEFAULT '');")
        conn.execute("INSERT INTO coverage_rounds (round_num, action_type, reason,"
                     " gap_reasons, prev_coverage, new_coverage, delta, improved, created_at)"
                     " VALUES (1,'EXPAND_SEEDS','','[]',0,1,1,1,'')")
        conn.commit()
        conn.close()

        s = CoverageExperienceStore(db_path=db)
        try:
            cols = {r[1] for r in s._connect().execute(
                "PRAGMA table_info(coverage_rounds)").fetchall()}
            assert "source" in cols, "老库没补列 —— 下一次 INSERT 会失败"
            # 补出来的老行是空来源，能读、能筛
            assert s.list_rounds()[0]["source"] == ""
            assert s.action_effectiveness(source="rl_suggested") == {}
            s.record_round(2, "EXPAND_SEEDS", "", [], 0, 2.0, source="rl_suggested")
            assert s.action_effectiveness(source="rl_suggested")["EXPAND_SEEDS"]["trials"] == 1
        finally:
            s.close()


class TestTheDistillationOnlyLearnsFromAdoptedRlActions:
    """L5 蒸馏的动作清单与 RL 的动作空间**同源**，且只看 `rl_suggested`。

    原来那份清单是**手写的四个名字**，其中 `REFACTOR_RTL` 在当前动作全集里
    已经不存在 —— 那一桶永远空着（`trials < 2` 直接跳过），而没人看得出
    "这里少学了一个动作"。
    """

    def test_only_rl_sourced_rows_can_become_a_proposal(self, tmp_path, monkeypatch):
        """**只按 `rl_suggested` 的来源判**，不按手写的动作清单。

        两条同名的动作记录：一条是规则决定的（改善率高），一条是 RL 采纳的
        （样本不足）。**只有后者有资格**进蒸馏 —— 拿前者的高分去提权重，
        就是把"规则动作的效果"记到"RL 选的动作"头上。

        这也顺带说明候选清单**不必手写**：库里带 `rl_suggested` 的键，
        按构造就是 RL 选过的（没进过它动作空间的名字不可能有这种来源），
        所以既不手写、也不用去 import L3 的动作表（那会被层向测试拦下）。
        """
        from src.knowledge import coverage_experience as ce
        from src.experience.distillation import DistillationOrchestrator

        store = CoverageExperienceStore(db_path=tmp_path / "ce3.db")
        # 规则来源：5 次全涨（分数很好看，但**不是 RL 选的**）
        for i in range(5):
            store.record_round(i, "EXPAND_SEEDS", "", [], 0, 3.0, source="rule")
        # RL 来源：只有 1 次（样本不足）
        store.record_round(9, "EXPAND_SEEDS", "", [], 0, 3.0, source="rl_suggested")
        monkeypatch.setattr(ce, "get_coverage_experience_store", lambda: store)
        try:
            props = DistillationOrchestrator()._channel_decision_weight()
            assert props == [], (
                "拿规则来源的高分给 RL 提了权重 —— 那正是幸存者偏差")
        finally:
            store.close()

    def test_without_rl_samples_nothing_is_proposed(self, tmp_path, monkeypatch):
        """一条 `rl_suggested` 样本都没有时**返回空** —— 不退回"拿全量凑一个"。"""
        from src.knowledge import coverage_experience as ce
        from src.experience.distillation import DistillationOrchestrator

        store = CoverageExperienceStore(db_path=tmp_path / "ce.db")
        # 只有规则来源的样本（RL 一条都没有）
        for i in range(3):
            store.record_round(i, "EXPAND_SEEDS", "", [], 0, 2.0, source="rule")
        monkeypatch.setattr(ce, "get_coverage_experience_store", lambda: store)
        try:
            props = DistillationOrchestrator()._channel_decision_weight()
            assert props == [], "没有 RL 样本却蒸馏出了权重 —— 那是拿全量冒充 RL"
        finally:
            store.close()
