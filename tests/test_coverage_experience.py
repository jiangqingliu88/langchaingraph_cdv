"""coverage 归因校准库单测：动作成效 / 归因准确率 / unreachable 黑名单。"""
import pytest

from src.layers.l4_memory.coverage_experience import CoverageExperienceStore


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
