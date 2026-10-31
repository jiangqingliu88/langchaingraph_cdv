from __future__ import annotations

from src.core.decision.eval import (
    EFFECTIVE, INEFFECTIVE, REGRESSED, UNCERTAIN,
    append_record, evaluate_round, read_records, summarize,
)


def _actual(**kw):
    base = {"prev_coverage": 50.0, "coverage": 52.0, "new_hits": 1,
            "lost_hits": 0, "tests_failed": 0, "tests_failed_prev": 0,
            "compile_ok": True, "compile_ok_prev": True,
            "tp_matrix_available": True}
    base.update(kw)
    return base


def _eval(**kw):
    return evaluate_round(
        run_id="r1", round_num=1,
        action={"action_type": "GENERATE_DIRECTED_TEST", "reason": "gap",
                "source": "rule"},
        expected={"needs_human": False, "plan": {"scope": "directed"}},
        actual=_actual(**kw))


def test_effective_when_coverage_or_hits_improve():
    rec = _eval()
    assert rec["status"] == EFFECTIVE
    assert rec["actual"]["delta"] == 2.0


def test_ineffective_when_nothing_moves():
    rec = _eval(coverage=50.0, new_hits=0)
    assert rec["status"] == INEFFECTIVE


def test_regressed_when_hits_are_lost():
    rec = _eval(lost_hits=2)
    assert rec["status"] == REGRESSED


def test_regressed_when_regression_failures_increase():
    rec = _eval(tests_failed=1)
    assert rec["status"] == REGRESSED


def test_regressed_when_compile_breaks():
    rec = _eval(compile_ok=False)
    assert rec["status"] == REGRESSED


def test_uncertain_when_inputs_missing():
    rec = evaluate_round(run_id="r1", round_num=1,
                         action={"action_type": "X"},
                         expected={"needs_human": False},
                         actual={"tp_matrix_available": False})
    assert rec["status"] == UNCERTAIN
    assert rec["inputs_available"]["coverage"] is False


def test_uncertain_for_human_escalation():
    rec = _eval(prev_coverage=None, coverage=None, new_hits=0,
                tp_matrix_available=False)
    rec = evaluate_round(run_id="r1", round_num=1,
                         action={"action_type": "X"},
                         expected={"needs_human": True},
                         actual=_actual())
    assert rec["status"] == UNCERTAIN


def test_append_is_idempotent_and_summarizes(tmp_path):
    rec = _eval()
    assert append_record(tmp_path, rec) is True
    assert append_record(tmp_path, rec) is False
    records = read_records(tmp_path)
    assert len(records) == 1
    summary = summarize(records)
    assert summary["by_status"][EFFECTIVE] == 1
    assert summary["by_action"]["GENERATE_DIRECTED_TEST"][EFFECTIVE] == 1
