"""debug 经验库单测：记忆命中 / 反馈校准 / 蒸馏候选 / 统计。"""
import pytest

from src.knowledge.debug_experience import DebugExperienceStore


@pytest.fixture
def store(tmp_path):
    s = DebugExperienceStore(db_path=tmp_path / "debug_experience.db")
    yield s
    s.close()


def test_record_then_unproven_not_reused(store):
    """未验证的经验（0/0）置信度为 0，默认不应被命中复用。"""
    store.record("fp_abc", category="uvm_config", fix_name="fix_missing_vif")
    assert store.lookup("fp_abc") is None                      # 0 置信度，不返回
    assert store.lookup("fp_abc", min_confidence=0.0) is not None  # 显式降阈才可见


def test_record_result_pass_raises_confidence(store):
    """一次 PASS 后置信度 1.0，下次命中直接复用。"""
    store.record("fp_x", category="rtl_width", fix_name="fix_scoreboard_width")
    store.record_result("fp_x", passed=True)
    exp = store.lookup("fp_x")
    assert exp is not None
    assert exp["confidence"] == 1.0
    assert exp["success_count"] == 1


def test_record_result_fail_drops_confidence(store):
    """失败会拉低置信度，低于复用门槛后不再复用（教训机制）。"""
    store.record("fp_y", category="compile_syntax", fix_name="fix_double_declare")
    store.record_result("fp_y", passed=True)   # 1/0
    store.record_result("fp_y", passed=False)  # 1/1 -> confidence 0.5
    assert store.lookup("fp_y", min_confidence=0.8) is None


def test_record_preserves_counts(store):
    """record 更新 fix 信息时不应清空已验证的计数。"""
    store.record("fp_z", category="uvm_phase", fix_name="fix_phase_objection")
    store.record_result("fp_z", passed=True)
    store.record("fp_z", category="uvm_phase", fix_name="fix_phase_objection_v2")
    exp = store.lookup("fp_z", min_confidence=0.0)
    assert exp["success_count"] == 1          # 计数保留
    assert exp["fix_name"] == "fix_phase_objection_v2"


def test_distill_candidates(store):
    """稳定通过 N 次的经验可蒸馏。"""
    store.record("fp_stable", category="uvm_phase", fix_name="fix_phase_objection")
    for _ in range(3):
        store.record_result("fp_stable", passed=True)
    cands = store.distill_candidates(min_success=3)
    assert any(c["fingerprint"] == "fp_stable" for c in cands)


def test_stats(store):
    store.record("fp_1", fix_name="f1")
    store.record_result("fp_1", passed=True)
    s = store.stats()
    assert s["total"] == 1
    assert s["reusable"] == 1
