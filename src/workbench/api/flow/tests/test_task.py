"""`run_task` —— 一次运行当作一个「验证任务」看。

钉的是几件容易糊在一起的事：
  · **「跑完」和「跑成功」是两件事** —— 有 manifest 但没达标 → `completed_with_errors`；
  · 还在跑时**没有 manifest**，阶段数与覆盖率要从运行日志里取，不能是空的；
  · 规划器的 `convergence_forecast` 里 `inf` 不是合法 JSON 值 —— 换成 None + 说明；
  · 覆盖率曲线口径与 evidence / run_common 一致（事件里的 round 本身就是 1-based）。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.workbench.api.flow import run_task


def _run(tmp_path: Path, events=(), manifest=None) -> Path:
    root = tmp_path / "apb_uart"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    if events:
        (root / "docs" / "run_events.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
    if manifest is not None:
        (root / "docs" / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return root


FINISHED_OK = {
    "target": 95.0, "final_coverage": 96.0, "effective_coverage": 96.0,
    "converged": True, "iterations": 2,
    "phases": [{"name": "design", "status": "passed", "score": 80},
               {"name": "ops", "status": "passed", "score": 70}],
    "planning": {"convergence_forecast": {"rounds_to_target": 1, "converging": True}},
}
FINISHED_BAD = {
    "target": 95.0, "final_coverage": 62.0, "effective_coverage": 62.0,
    "converged": False,
    "phases": [{"name": "ops", "status": "failed", "score": 0}],
    "planning": {"convergence_forecast": {"rounds_to_target": float("inf"),
                                          "converging": False}},
}
COVERAGE_EVENTS = [
    {"seq": 1, "kind": "run.started", "payload": {}},
    {"seq": 2, "kind": "coverage.updated", "round": 1, "payload": {"total": 62.0}},
    {"seq": 3, "kind": "coverage.updated", "round": 2, "payload": {"total": 74.0}},
]


class TestStates:
    def test_converged_run_is_completed(self, tmp_path):
        r = run_task(str(_run(tmp_path, COVERAGE_EVENTS, FINISHED_OK)))
        assert r["state"] == "completed"
        assert r["coverage"]["converged"] is True
        assert "已达标" in r["summary"]

    def test_finished_but_not_converged_is_completed_with_errors(self, tmp_path):
        """跑完 ≠ 成功。没达标必须能一眼看出来。"""
        r = run_task(str(_run(tmp_path, COVERAGE_EVENTS, FINISHED_BAD)))
        assert r["state"] == "completed_with_errors"
        assert "还差 33 个点" in r["summary"]

    def test_terminal_event_beats_manifest(self, tmp_path):
        events = COVERAGE_EVENTS + [{"seq": 9, "kind": "run.failed",
                                     "payload": {"error": "炸了"}}]
        r = run_task(str(_run(tmp_path, events, FINISHED_OK)))
        assert r["state"] == "failed"

    def test_interrupted_means_waiting(self, tmp_path):
        events = [{"seq": 1, "kind": "run.interrupted", "payload": {}}]
        assert run_task(str(_run(tmp_path, events)))["state"] == "waiting"

    def test_in_flight_is_running(self, tmp_path):
        assert run_task(str(_run(tmp_path, COVERAGE_EVENTS)))["state"] == "running"


class TestCoverage:
    def test_history_is_one_based(self, tmp_path):
        r = run_task(str(_run(tmp_path, COVERAGE_EVENTS)))
        assert r["coverage"]["history"] == [[1, 62.0], [2, 74.0]]

    def test_in_flight_falls_back_to_last_event(self, tmp_path):
        """还在跑：没有 manifest，最终覆盖率就是最后一轮的记录。"""
        r = run_task(str(_run(tmp_path, COVERAGE_EVENTS)))
        assert r["coverage"]["final"] == 74.0

    def test_gap_uses_effective_coverage(self, tmp_path):
        manifest = {**FINISHED_BAD, "final_coverage": 90.0, "effective_coverage": 92.0}
        r = run_task(str(_run(tmp_path, COVERAGE_EVENTS, manifest)))
        assert r["coverage"]["gap"] == 3.0          # 95 - 92，不是 95 - 90


class TestForecast:
    def test_rounds_to_target(self, tmp_path):
        f = run_task(str(_run(tmp_path, COVERAGE_EVENTS, FINISHED_OK)))["forecast"]
        assert f["rounds_to_target"] == 1 and f["converging"] is True

    def test_inf_becomes_none_with_a_note(self, tmp_path):
        """`inf` 不是合法 JSON —— 如实换成 None + 说明，别让界面上出现 Infinity。"""
        f = run_task(str(_run(tmp_path, COVERAGE_EVENTS, FINISHED_BAD)))["forecast"]
        assert f["rounds_to_target"] is None
        assert f["converging"] is False
        assert "停滞" in f["note"]


class TestPhasesAndBlockers:
    def test_phases_from_manifest(self, tmp_path):
        r = run_task(str(_run(tmp_path, COVERAGE_EVENTS, FINISHED_OK)))
        assert r["phases"]["passed"] == 2 and r["phases"]["total"] == 2

    def test_phases_from_journal_when_still_running(self, tmp_path):
        """还在跑没有 manifest —— 阶段数要从日志里数，否则"运行中"那行是空的。"""
        events = COVERAGE_EVENTS + [
            {"seq": 4, "kind": "stage.finished", "stage": "verify",
             "title": "验证计划与UVM", "round": 1, "status": "ok"}]
        r = run_task(str(_run(tmp_path, events)))
        assert r["phases"]["total"] == 1 and r["phases"]["passed"] == 1

    def test_failed_stage_is_a_blocker(self, tmp_path):
        events = COVERAGE_EVENTS + [
            {"seq": 4, "kind": "stage.failed", "stage": "ops",
             "title": "编译与仿真回归", "round": 2, "payload": {"error": "vlog 报错 3 处"}}]
        r = run_task(str(_run(tmp_path, events)))
        assert r["blockers"][0]["title"] == "编译与仿真回归"
        assert "vlog 报错" in r["blockers"][0]["error"]
        assert "1 处卡点" in r["summary"]

    def test_failed_phase_is_a_blocker_when_no_journal_event(self, tmp_path):
        r = run_task(str(_run(tmp_path, COVERAGE_EVENTS, FINISHED_BAD)))
        assert r["blockers"][0]["title"] == "ops"

    def test_current_stage_from_last_event(self, tmp_path):
        events = COVERAGE_EVENTS + [
            {"seq": 4, "kind": "stage.finished", "stage": "design",
             "title": "规格与设计", "round": 1, "status": "ok"}]
        assert run_task(str(_run(tmp_path, events)))["current"]["title"] == "规格与设计"


class TestEmptyAndErrors:
    def test_no_records_says_so(self, tmp_path):
        r = run_task(str(_run(tmp_path)))
        assert r["available"] is False
        assert "还没有任何记录" in r["summary"]

    def test_missing_dir_is_loud(self, tmp_path):
        assert "error" in run_task(str(tmp_path / "nope"))

    def test_empty_path_is_loud(self):
        assert "error" in run_task("")
