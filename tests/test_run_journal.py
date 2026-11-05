"""运行日志 —— 写入、读取、增量 tail，以及「图流 → 日志」的翻译。

这套测试盯的是**崩溃安全**与**增量读**两件事：界面靠轮询 tail 显示实时进度，
所以「半截行怎么办」「文件被截断怎么办」不是边缘情况，是常态。
"""
from __future__ import annotations

import json

import pytest

from src.layers.l2_orchestration.execution import (
    _coverage_of, _result_of, _round_of, _translate_custom, _translate_debug,
)
from src.layers.l2_orchestration.run_journal import (
    KIND_APPROVAL_DECIDED, KIND_RUN_CANCELLED, KIND_RUN_FINISHED,
    KIND_STAGE_FAILED, KIND_STAGE_FINISHED, KIND_STAGE_STARTED, JournalTail,
    RunEvent, RunJournal, iter_events, journal_path, read_journal,
)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "output_ut_20261002_120000"


# ═══════════════════════════════════════════════════════════════
# 写
# ═══════════════════════════════════════════════════════════════

class TestWrite:
    def test_lands_under_docs(self, root):
        assert journal_path(root) == root / "docs" / "run_events.jsonl"

    def test_creates_parent_directory(self, root):
        with RunJournal(root, run_id="r1") as j:
            j.note("hi")
        assert journal_path(root).exists()

    def test_seq_continues_across_reopens(self, root):
        """一次运行可以分几次写同一个日志（检查点重入、换进程继续）。

        每次开头把 seq 归零的话，增量读的一方会认为"这些我都看过了"而把后半段
        整段丢掉 —— 静默丢掉，界面上表现为"重入了但时间线不动"。
        """
        with RunJournal(root, run_id="r1") as j:
            j.note("前半段")
        with RunJournal(root, run_id="r1") as j:
            j.note("后半段")
        assert [e.seq for e in read_journal(root)] == [1, 2]

    def test_incremental_read_sees_the_second_half(self, root):
        """上面的直接后果：按 after_seq 轮询必须看得到重入之后的事件。"""
        with RunJournal(root, run_id="r1") as j:
            j.note("a")
        watermark = read_journal(root)[-1].seq
        with RunJournal(root, run_id="r1") as j:
            j.note("b")
        fresh = read_journal(root, after_seq=watermark)
        assert [e.payload["message"] for e in fresh] == ["b"]

    def test_seq_is_monotonic_from_one(self, root):
        with RunJournal(root, run_id="r1") as j:
            j.run_started(target=95.0)
            j.stage_started("design")
            j.note("x")
        events = read_journal(root)
        assert [e.seq for e in events] == [1, 2, 3]

    def test_stage_events_carry_title_and_agent(self, root):
        """标题与归属在**写入时**就查好 —— 读的一方不必再 import 阶段表。"""
        with RunJournal(root, run_id="r1") as j:
            j.stage_started("ops")
        (event,) = read_journal(root)
        assert event.stage == "ops"
        assert event.title == "编译与仿真回归"
        assert event.agent == "ops"

    def test_round_defaults_to_the_journal_counter(self, root):
        with RunJournal(root, run_id="r1") as j:
            j.round_num = 3
            j.stage_started("coverage")
        (event,) = read_journal(root)
        assert event.round == 3

    def test_run_id_defaults_to_the_directory_name(self, root):
        with RunJournal(root) as j:
            j.note("x")
        assert read_journal(root)[0].run_id == root.name

    def test_payload_is_json_serialisable(self, root, tmp_path):
        """增量里可能有 Path / dataclass —— 日志不能因此写不出来。"""
        with RunJournal(root, run_id="r1") as j:
            j.record("note", payload={"p": tmp_path / "a.sv", "n": [1, 2]})
        (event,) = read_journal(root)
        assert event.payload["p"] == str(tmp_path / "a.sv")

    def test_write_failure_does_not_raise(self, tmp_path):
        """日志是观测手段，不能因为它坏了就把验证跑挂掉。"""
        blocked = tmp_path / "blocked"
        blocked.write_text("我是个文件，不是目录", encoding="utf-8")
        with RunJournal(blocked, run_id="r1") as j:
            j.note("x")                       # 不抛
        assert j.write_errors >= 1

    def test_returns_the_event_even_when_the_write_failed(self, tmp_path):
        blocked = tmp_path / "blocked2"
        blocked.write_text("x", encoding="utf-8")
        with RunJournal(blocked, run_id="r1") as j:
            event = j.note("hello")
        assert event.seq == 1 and event.payload["message"] == "hello"


# ═══════════════════════════════════════════════════════════════
# 读
# ═══════════════════════════════════════════════════════════════

class TestRead:
    def test_round_trip(self, root):
        with RunJournal(root, run_id="r1") as j:
            j.run_started(target=90.0)
            j.stage_finished("design", 1.5, {"status": "ok"})
        events = read_journal(root)
        assert events[0].kind.startswith("run.")
        assert events[1].duration_s == 1.5
        assert events[1].payload["status"] == "ok"

    def test_after_seq_filters(self, root):
        with RunJournal(root, run_id="r1") as j:
            for i in range(5):
                j.note(f"n{i}")
        assert len(read_journal(root, after_seq=3)) == 2

    def test_missing_file_is_empty_not_an_error(self, tmp_path):
        assert read_journal(tmp_path / "nope") == []

    def test_malformed_line_is_skipped(self, root):
        with RunJournal(root, run_id="r1") as j:
            j.note("good1")
        with journal_path(root).open("a", encoding="utf-8") as fh:
            fh.write("这不是 JSON\n")
        with RunJournal(root, run_id="r1") as j:
            j.note("good2")
        messages = [e.payload.get("message") for e in read_journal(root)]
        assert messages == ["good1", "good2"]

    def test_truncated_tail_is_skipped(self, root):
        """进程被杀时最后一行可能只写了一半 —— 跳过它，别丢掉前面的。"""
        with RunJournal(root, run_id="r1") as j:
            j.note("complete")
        with journal_path(root).open("a", encoding="utf-8") as fh:
            fh.write('{"seq": 2, "kind": "note"')      # 半截
        assert len(read_journal(root)) == 1

    def test_accepts_a_file_path_too(self, root):
        """调用方从界面拿到的是路径、从仓库拿到的是目录 —— 两边都得能用。"""
        with RunJournal(root, run_id="r1") as j:
            j.note("x")
        assert len(read_journal(journal_path(root))) == 1

    def test_event_is_terminal_and_failure_flags(self, root):
        with RunJournal(root, run_id="r1") as j:
            j.note("x")
            j.stage_failed("ops", 0.1, "boom")
            j.run_finished({"status": "PASS"})
        note, failed, done = read_journal(root)
        assert not note.is_terminal and not note.is_failure
        assert failed.is_failure
        assert done.is_terminal and not done.is_failure


# ═══════════════════════════════════════════════════════════════
# 增量读（界面轮询）
# ═══════════════════════════════════════════════════════════════

class TestJournalTail:
    def test_first_poll_gives_everything(self, root):
        with RunJournal(root, run_id="r1") as j:
            j.note("a")
            j.note("b")
        tail = JournalTail(root)
        assert len(tail.poll()) == 2

    def test_second_poll_gives_only_the_new(self, root):
        journal = RunJournal(root, run_id="r1")
        journal.note("a")
        tail = JournalTail(root)
        assert len(tail.poll()) == 1

        journal.note("b")
        journal.note("c")
        fresh = tail.poll()
        assert [e.payload["message"] for e in fresh] == ["b", "c"]

        journal.close()

    def test_no_new_data_is_empty(self, root):
        with RunJournal(root, run_id="r1") as j:
            j.note("a")
        tail = JournalTail(root)
        tail.poll()
        assert tail.poll() == []

    def test_partial_line_waits_for_its_newline(self, root):
        """半截行不能吐给界面 —— 等下一轮补全了再给。"""
        path = journal_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(RunEvent(seq=1, ts="t", kind="note").to_dict(),
                          ensure_ascii=False)
        path.write_text(line[:20], encoding="utf-8")     # 写一半
        tail = JournalTail(root)
        assert tail.poll() == []

        with path.open("a", encoding="utf-8") as fh:
            fh.write(line[20:] + "\n")
        events = tail.poll()
        assert len(events) == 1 and events[0].seq == 1

    def test_truncated_file_resets_the_offset(self, root):
        """同一个 run 目录被重跑 → 文件变小 → 从头读，不能越读越乱。"""
        with RunJournal(root, run_id="r1") as j:
            for i in range(10):
                j.note(f"old{i}")
        tail = JournalTail(root)
        assert len(tail.poll()) == 10

        journal_path(root).write_text("", encoding="utf-8")
        with RunJournal(root, run_id="r1") as j:
            j.note("fresh")
        events = tail.poll()
        assert [e.payload["message"] for e in events] == ["fresh"]

    def test_missing_file_then_appearing(self, root):
        tail = JournalTail(root)
        assert tail.poll() == []
        with RunJournal(root, run_id="r1") as j:
            j.note("late")
        assert len(tail.poll()) == 1


# ═══════════════════════════════════════════════════════════════
# 图流 → 日志
# ═══════════════════════════════════════════════════════════════

class _StubJournal:
    """只记录调用，不碰磁盘 —— 翻译层是纯函数，不该依赖文件系统。"""

    def __init__(self):
        self.calls = []
        self.round_num = 0

    def stage_started(self, stage):
        self.calls.append(("started", stage))
        return stage

    def stage_finished(self, stage, duration, delta=None):
        self.calls.append(("finished", stage, delta))
        return stage

    def stage_failed(self, stage, duration, error):
        self.calls.append(("failed", stage, error))
        return stage

    def progress(self, stage, message, **extra):
        self.calls.append(("progress", stage, message))
        return stage

    def record(self, kind, **kw):
        self.calls.append(("record", kind, kw.get("payload")))
        return kind


class TestTranslateDebug:
    def test_task_becomes_stage_started(self):
        j = _StubJournal()
        _translate_debug({"type": "task", "payload": {"id": "t1", "name": "ops"}},
                         {}, j)
        assert j.calls == [("started", "ops")]

    def test_task_result_becomes_stage_finished_with_delta(self):
        j, started = _StubJournal(), {"t1": 0.0}
        events = _translate_debug(
            {"type": "task_result",
             "payload": {"id": "t1", "name": "coverage", "error": None,
                         "result": {"functional_coverage": 0.8}}},
            started, j)
        assert events is not None
        assert j.calls[0][0] == "finished"
        assert j.calls[0][2] == {"functional_coverage": 0.8}

    def test_result_with_error_becomes_stage_failed(self):
        j = _StubJournal()
        _translate_debug(
            {"type": "task_result",
             "payload": {"id": "t1", "name": "ops", "error": "RuntimeError: boom"}},
            {"t1": 0.0}, j)
        assert j.calls[0][0] == "failed"
        assert "boom" in j.calls[0][2]

    def test_start_timestamp_is_consumed_once(self):
        j, started = _StubJournal(), {}
        _translate_debug({"type": "task", "payload": {"name": "ops"}}, started, j)
        assert started
        _translate_debug({"type": "task_result",
                          "payload": {"name": "ops", "result": {}}}, started, j)
        assert not started          # 用完就 pop，不会无限增长

    @pytest.mark.parametrize("chunk", [
        {"type": "unknown", "payload": {"name": "x"}},
        {"type": "task", "payload": {}},
        "not a dict",
        None,
    ])
    def test_unknown_shapes_are_ignored(self, chunk):
        j = _StubJournal()
        assert _translate_debug(chunk, {}, j) == []
        assert j.calls == []


class TestTranslateCustom:
    def test_conventional_shape(self):
        j = _StubJournal()
        _translate_custom({"stage": "ops", "message": "跑了 32 个 case"}, j)
        assert j.calls == [("progress", "ops", "跑了 32 个 case")]

    def test_unconventional_shape_is_still_recorded(self):
        """丢掉一条看不懂的进度，比丢掉一条本该看到的进度更糟。"""
        j = _StubJournal()
        _translate_custom({"stage": "ops", "counter": 7}, j)
        assert j.calls[0][0] == "record"

    def test_scalar_becomes_a_progress_line(self):
        j = _StubJournal()
        _translate_custom("hello", j)
        assert j.calls == [("progress", "", "hello")]


class TestStateReaders:
    def test_round_from_dict_and_object(self):
        assert _round_of({"round_num": 3}) == 3
        assert _round_of(None) is None

        class S:
            round_num = 2
        assert _round_of(S()) == 2

    def test_coverage_empty_when_nothing_yet(self):
        assert _coverage_of({}) == {}
        assert _coverage_of(None) == {}

    def test_coverage_picks_effective_over_raw(self):
        cov = _coverage_of({"effective_coverage": 91.0, "coverage": 70.0,
                            "functional_coverage": 80.0})
        assert cov == {"total": 91.0, "functional": 80.0}

    def test_result_extraction(self):
        assert _result_of({"result": {"status": "PASS"}}) == {"status": "PASS"}
        assert _result_of({}) == {}
        assert _result_of(None) == {}


# ═══════════════════════════════════════════════════════════════
# 语义化记录器
# ═══════════════════════════════════════════════════════════════

def test_approval_round_trip(root):
    with RunJournal(root, run_id="r1") as j:
        j.approval_requested("REFACTOR_RTL", "high", "改了时序", token="ap-1")
        j.approval_decided("reject", token="ap-1", by="gui")
    asked, decided = read_journal(root)
    assert asked.status == "waiting" and asked.payload["token"] == "ap-1"
    assert decided.kind == KIND_APPROVAL_DECIDED
    assert decided.payload["decision"] == "reject" and decided.payload["by"] == "gui"


def test_cancelled_is_terminal(root):
    with RunJournal(root, run_id="r1") as j:
        j.run_cancelled("用户点了停止")
    (event,) = read_journal(root)
    assert event.kind == KIND_RUN_CANCELLED and event.is_terminal


def test_stage_summary_keeps_the_full_delta(root):
    """一行摘要给界面，完整增量给想查细节的人 —— 两个都要在。"""
    with RunJournal(root, run_id="r1") as j:
        j.stage_finished("ops", 0.2, {"passed": 30, "total": 32,
                                      "some_internal": {"a": 1}})
    (event,) = read_journal(root)
    assert event.payload["passed"] == 30
    assert event.payload["delta"]["some_internal"] == {"a": 1}


def test_iter_events_is_lazy_over_a_missing_file(tmp_path):
    assert list(iter_events(tmp_path / "nope" / "x.jsonl")) == []
