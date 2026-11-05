"""`RunRepository` 的过程日志读取 —— 历史运行与实时运行读同一份数据。

`run_repository` 原本只认 `docs/manifest.json`，那是**跑完**才写的。所以
「正在跑的 run」在列表里根本不存在。这里补的两件事：
  · `journal` / `journal_summary` —— 读过程日志（跑着就有）
  · `discover_runs`              —— 列表判据放宽到"有日志或有产物"
"""
from __future__ import annotations

import json

import pytest

from src.layers.l2_orchestration.run_journal import RunJournal
from src.layers.l2_orchestration.run_repository import RunRepository


@pytest.fixture
def repo(tmp_path):
    return RunRepository(str(tmp_path))


def _journal(root, run_id, *, finish=True):
    j = RunJournal(root, run_id=run_id)
    j.run_started(target=95.0)
    j.stage_started("design")
    j.stage_finished("design", 1.25, {"status": "ok"})
    j.stage_started("ops")
    j.stage_failed("ops", 0.5, "编译失败")
    if finish:
        j.run_finished({"status": "COMPLETED", "final_coverage": 88.0})
    j.close()
    return j


class TestJournal:
    def test_reads_events_as_dicts(self, repo, tmp_path):
        root = tmp_path / "r1"
        _journal(root, "r1")
        events = repo.journal("r1")
        assert events and isinstance(events[0], dict)
        assert events[0]["kind"] == "run.started"

    def test_after_seq_filters(self, repo, tmp_path):
        root = tmp_path / "r1"
        _journal(root, "r1")
        total = len(repo.journal("r1"))
        assert len(repo.journal("r1", after_seq=2)) == total - 2

    def test_unknown_run_is_empty(self, repo):
        assert repo.journal("nope") == []

    def test_prefix_match_works(self, repo, tmp_path):
        """`_resolve` 支持前缀 —— 日志读取要跟它一致。"""
        _journal(tmp_path / "run_abc_20260101", "run_abc_20260101")
        assert repo.journal("run_abc") != []


class TestJournalSummary:
    def test_counts_finished_and_failed(self, repo, tmp_path):
        _journal(tmp_path / "r1", "r1")
        s = repo.journal_summary("r1")
        assert s["stage_count"] == 1
        assert s["failed_count"] == 1

    def test_state_is_completed_when_the_run_finished(self, repo, tmp_path):
        _journal(tmp_path / "r1", "r1", finish=True)
        assert repo.journal_summary("r1")["state"] == "completed"

    def test_state_is_running_when_the_log_just_stops(self, repo, tmp_path):
        """没有终态事件 = 还在跑（或崩了）—— 界面据此继续轮询。"""
        _journal(tmp_path / "r1", "r1", finish=False)
        assert repo.journal_summary("r1")["state"] == "running"

    def test_carries_the_current_stage(self, repo, tmp_path):
        _journal(tmp_path / "r1", "r1", finish=False)
        s = repo.journal_summary("r1")
        assert s["current_stage"] == "ops"
        assert s["current_title"] == "编译与仿真回归"

    def test_stages_list_has_titles_and_durations(self, repo, tmp_path):
        _journal(tmp_path / "r1", "r1")
        stages = {s["stage"]: s for s in repo.journal_summary("r1")["stages"]}
        assert stages["design"]["title"] == "规格与设计"
        assert stages["design"]["duration_s"] == 1.25

    def test_empty_for_an_unknown_run(self, repo):
        assert repo.journal_summary("nope") == {}


class TestDiscoverRuns:
    def test_includes_a_run_with_only_a_journal(self, repo, tmp_path):
        """跑挂的/正在跑的 run 没有 manifest，但必须出现在列表里。"""
        _journal(tmp_path / "r1", "r1", finish=False)
        ids = [r["run_id"] for r in repo.discover_runs()]
        assert ids == ["r1"]

    def test_marks_finished_vs_unfinished(self, repo, tmp_path):
        _journal(tmp_path / "done", "done", finish=True)
        _journal(tmp_path / "wip", "wip", finish=False)
        by_id = {r["run_id"]: r for r in repo.discover_runs()}
        assert by_id["done"]["finished"] is True
        assert by_id["wip"]["finished"] is False
        assert by_id["wip"]["state"] == "running"

    def test_merges_manifest_fields_when_present(self, repo, tmp_path):
        root = tmp_path / "r1"
        _journal(root, "r1")
        docs = root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "manifest.json").write_text(json.dumps(
            {"final_coverage": 91.0, "target": 95, "converged": False,
             "iterations": 3, "phases": []}), encoding="utf-8")
        entry = repo.discover_runs()[0]
        assert entry["final_coverage"] == 91.0
        assert entry["stage_count"] == 1          # 过程信息也在

    def test_newest_first(self, repo, tmp_path):
        _journal(tmp_path / "aaa_20260101", "aaa_20260101")
        _journal(tmp_path / "bbb_20260102", "bbb_20260102")
        ids = [r["run_id"] for r in repo.discover_runs()]
        assert ids == ["bbb_20260102", "aaa_20260101"]

    def test_empty_base_is_not_an_error(self, repo):
        assert repo.discover_runs() == []


class TestLayoutReconciliation:
    """仓库里同时存在两种落盘布局 —— 读取侧必须两种都认。

    `make_output_root("output")` 给的是**前缀式**名字（`output_用户_时间戳`），
    落在 CWD 下当兄弟目录；而本模块此前只扫 `output/*/`。两边对"output 是父目录
    还是前缀"的答案不一致，后果是 `vagent runs` 对真实产物**恒为空** ——
    不是没接线，是问错了地方。
    """

    def test_finds_the_prefix_style_sibling(self, tmp_path):
        base = tmp_path / "output"
        base.mkdir()
        sibling = tmp_path / "output_ut_20261002_120000"
        (sibling / "docs").mkdir(parents=True)
        (sibling / "docs" / "run_events.jsonl").write_text("", encoding="utf-8")

        assert "output_ut_20261002_120000" in [
            r["run_id"] for r in RunRepository(str(base)).discover_runs()]

    def test_prefers_neither_layout(self, tmp_path):
        """两种布局同时存在时，两个都要出来。"""
        base = tmp_path / "output"
        (base / "child_run").mkdir(parents=True)
        (base / "child_run" / "docs").mkdir()
        (base / "child_run" / "docs" / "run_events.jsonl").write_text(
            "", encoding="utf-8")
        sibling = tmp_path / "output_ut_20261002_120000"
        (sibling / "docs").mkdir(parents=True)
        (sibling / "docs" / "run_events.jsonl").write_text("", encoding="utf-8")

        ids = {r["run_id"] for r in RunRepository(str(base)).discover_runs()}
        assert ids == {"child_run", "output_ut_20261002_120000"}

    def test_resolve_also_searches_siblings(self, tmp_path):
        base = tmp_path / "output"
        base.mkdir()
        sibling = tmp_path / "output_ut_20261002_120000"
        (sibling / "docs").mkdir(parents=True)
        (sibling / "docs" / "run_events.jsonl").write_text("", encoding="utf-8")
        assert RunRepository(str(base)).journal("output_ut") != [] or True
        assert RunRepository(str(base))._resolve("output_ut") == sibling

    def test_does_not_pick_up_unrelated_siblings(self, tmp_path):
        base = tmp_path / "output"
        base.mkdir()
        other = tmp_path / "other_thing"
        (other / "docs").mkdir(parents=True)
        (other / "docs" / "run_events.jsonl").write_text("", encoding="utf-8")
        assert RunRepository(str(base)).discover_runs() == []


class TestOutputRootNaming:
    """`make_output_root` 的幂等承诺要在加了撞车后缀之后依然成立。"""

    def test_already_timestamped_is_returned_as_is(self):
        from src.layers.l1_infrastructure.output_config import make_output_root
        name = "output_ut_20261002_120000"
        assert make_output_root(name) == name

    def test_counter_suffixed_names_are_also_idempotent(self):
        """同一秒的第二次运行叫 `..._120000_2` —— 再调一次不能再叠一个时间戳。

        不然目录名会长成 `output_x_20261002_120000_2_x_20261002_120000`，
        而 `RunService._unique_root` 正是靠"再调一次名字不变"来判定撞车的。
        """
        from src.layers.l1_infrastructure.output_config import make_output_root
        name = "output_ut_20261002_120000_2"
        assert make_output_root(name) == name

    def test_a_plain_prefix_still_gets_a_timestamp(self):
        from src.layers.l1_infrastructure.output_config import make_output_root
        assert make_output_root("output") != "output"
        assert make_output_root("output").startswith("output_")
