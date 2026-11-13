"""RunService —— Qt 与 asyncio 的唯一交界处。

这一层要用假图跑：真图需要 LLM 与 EDA，而这里验证的是**服务语义**——
立即返回、串行、可取消、进度从磁盘可查、日志不撞目录。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.orchestration_plane.supervisor import graph as graph_mod
from src.orchestration_plane.l2.execution import PipelineExecutionService
from src.orchestration_plane.l2.run_service import (
    RunRequest, RunService, get_run_service,
)
from src.orchestration_plane.l2.state import PipelineState


def _graph(checkpointer=None, store=None, *, delay: float = 0.0, fail: bool = False,
           system_exit: bool = False):
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(PipelineState)

    def n_design(state):
        if delay:
            time.sleep(delay)
        return {"spec": {"n": 1}, "phases": [{"name": "design", "status": "passed"}]}

    def n_ops(state):
        if system_exit:
            # 复刻真实事故：`uvm_tools/gen_uvm` 是照着独立 CLI 写的，
            # schema 校验不过就 `raise SystemExit`。
            raise SystemExit("Schema validation failed: 4 error(s), 0 warning(s)")
        if fail:
            raise RuntimeError("仿真炸了")
        return {"regression": {"passed": 3}}

    def n_finalize(state):
        return {"result": {"status": "PASS", "final_coverage": 91.0,
                           "converged": True, "iterations": 1}}

    g.add_node("design", n_design)
    g.add_node("ops", n_ops)
    g.add_node("finalize", n_finalize)
    g.add_edge(START, "design")
    g.add_edge("design", "ops")
    g.add_edge("ops", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer, store=store)


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                        lambda **kw: _graph(**kw))
    PipelineExecutionService.get_instance()._initialized = True
    service = RunService(output_base=str(tmp_path))
    yield service
    service.shutdown(timeout=5)


def _req(tmp_path, **kw):
    kw.setdefault("output_root", str(tmp_path / "run"))
    kw.setdefault("target", 95.0)
    kw.setdefault("max_rounds", 1)
    return RunRequest(spec_text="# 假规格", **kw)


def _wait_until(pred, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


# ═══════════════════════════════════════════════════════════════
# 启动与等待
# ═══════════════════════════════════════════════════════════════

class TestStart:
    def test_returns_a_run_id_immediately(self, svc, tmp_path, monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(delay=0.3, **kw))
        t0 = time.time()
        run_id = svc.start(_req(tmp_path))
        elapsed = time.time() - t0
        assert run_id
        assert elapsed < 0.2, "start() 必须立即返回，不能等运行跑完"
        svc.wait(run_id, timeout=20)

    def test_wait_returns_the_result(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        result = svc.wait(run_id, timeout=20)
        assert result.get("status") == "PASS"
        assert result.get("final_coverage") == 91.0

    def test_wait_on_unknown_run_is_empty(self, svc):
        assert svc.wait("nope", timeout=0.1) == {}

    def test_wait_times_out_without_raising(self, svc, tmp_path, monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(delay=1.5, **kw))
        run_id = svc.start(_req(tmp_path))
        assert svc.wait(run_id, timeout=0.05) == {}
        svc.wait(run_id, timeout=20)          # 收尾，别让后台线程挂太久

    def test_run_id_is_the_output_directory_name(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=20)
        assert any(r["run_id"] == run_id for r in svc.list_runs())


# ═══════════════════════════════════════════════════════════════
# 串行（纪律 2）
# ═══════════════════════════════════════════════════════════════

class TestSerialisation:
    def test_a_second_run_queues_behind_the_first(self, svc, tmp_path, monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(delay=0.4, **kw))
        first = svc.start(_req(tmp_path, run_id="first"))
        assert _wait_until(lambda: svc.current_run_id() == "first")
        second = svc.start(_req(tmp_path, run_id="second"))

        status = svc.status()
        assert status["busy"] is True
        assert status["current"] == "first"
        assert "second" in status["queued"]

        svc.wait(first, timeout=20)
        svc.wait(second, timeout=20)

    def test_busy_is_false_when_idle(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=20)
        assert _wait_until(lambda: not svc.busy)
        assert svc.status()["current"] == ""

    def test_runs_do_not_share_an_output_directory(self, svc, tmp_path):
        """时间戳精确到秒 —— 同一秒里的两次运行必须落在不同目录。

        共用一个目录的话，日志、证据链、覆盖率全混在一起，
        而且是在"可复现·可审计"最要紧的地方混。
        """
        a = svc.start(_req(tmp_path, run_id="a"))
        svc.wait(a, timeout=20)
        b = svc.start(_req(tmp_path, run_id="b"))
        svc.wait(b, timeout=20)
        dirs = {r["dir"] for r in svc.list_runs()}
        assert len(dirs) == 2


# ═══════════════════════════════════════════════════════════════
# 取消
# ═══════════════════════════════════════════════════════════════

class TestCancel:
    def test_cancel_stops_at_a_node_boundary(self, svc, tmp_path, monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(delay=0.3, **kw))
        run_id = svc.start(_req(tmp_path))
        assert _wait_until(lambda: svc.current_run_id() == run_id)
        assert svc.cancel(run_id) is True
        assert svc.wait(run_id, timeout=20) == {}
        assert svc.summary(run_id)["state"] == "cancelled"

    def test_cancel_on_idle_service_is_false(self, svc):
        assert svc.cancel() is False

    def test_cancel_a_finished_run_is_false(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=20)
        assert svc.cancel(run_id) is False

    def test_cancel_marks_the_journal(self, svc, tmp_path, monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(delay=0.3, **kw))
        run_id = svc.start(_req(tmp_path))
        assert _wait_until(lambda: svc.current_run_id() == run_id)
        svc.cancel(run_id)
        svc.wait(run_id, timeout=20)
        kinds = [e["kind"] for e in svc.journal(run_id)]
        assert kinds[-1] == "run.cancelled"


# ═══════════════════════════════════════════════════════════════
# 观测：进度从磁盘来
# ═══════════════════════════════════════════════════════════════

class TestObservability:
    def test_journal_is_readable_after_a_run(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=20)
        kinds = [e["kind"] for e in svc.journal(run_id)]
        assert "run.started" in kinds and kinds[-1] == "run.finished"

    def test_journal_is_readable_while_running(self, svc, tmp_path, monkeypatch):
        """运行**期间**就能看到进度 —— 这是整个设计的目的。"""
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(delay=0.5, **kw))
        run_id = svc.start(_req(tmp_path))
        got = _wait_until(lambda: bool(svc.journal(run_id)))
        assert got, "运行期间读不到任何事件"
        svc.cancel(run_id)
        svc.wait(run_id, timeout=20)

    def test_summary_reports_the_current_stage(self, svc, tmp_path, monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(delay=0.6, **kw))
        run_id = svc.start(_req(tmp_path))
        assert _wait_until(lambda: svc.summary(run_id).get("state") == "running")
        svc.cancel(run_id)
        svc.wait(run_id, timeout=20)

    def test_list_runs_includes_unfinished_ones(self, svc, tmp_path, monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(delay=0.6, **kw))
        run_id = svc.start(_req(tmp_path))
        assert _wait_until(lambda: any(r["run_id"] == run_id
                                       for r in svc.list_runs()))
        svc.cancel(run_id)
        svc.wait(run_id, timeout=20)

    def test_on_event_callback_fires_in_process(self, svc, tmp_path):
        seen = []
        run_id = svc.start(_req(tmp_path), on_event=seen.append)
        svc.wait(run_id, timeout=20)
        assert seen
        assert any(getattr(e, "kind", "") == "run.finished" for e in seen)

    def test_run_detail_merges_disk_and_journal(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=20)
        detail = svc.run_detail(run_id)
        assert detail["run_id"] == run_id
        assert detail["state"] == "completed"


# ═══════════════════════════════════════════════════════════════
# 失败
# ═══════════════════════════════════════════════════════════════

class TestFailure:
    def test_a_failed_run_marks_the_journal(self, svc, tmp_path, monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(fail=True, **kw))
        run_id = svc.start(_req(tmp_path))
        with pytest.raises(Exception):
            svc.wait(run_id, timeout=20)
        kinds = [e["kind"] for e in svc.journal(run_id)]
        assert kinds[-1] == "run.failed"

    def test_a_failure_does_not_block_the_next_run(self, svc, tmp_path,
                                                  monkeypatch):
        """串行不等于"一次失败就卡死" —— 工人线程必须继续消费队列。"""
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(fail=True, **kw))
        bad = svc.start(_req(tmp_path, run_id="bad"))
        with pytest.raises(Exception):
            svc.wait(bad, timeout=20)

        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(**kw))
        good = svc.start(_req(tmp_path, run_id="good"))
        assert svc.wait(good, timeout=20).get("status") == "PASS"


# ═══════════════════════════════════════════════════════════════
# 工具调了 sys.exit —— 服务的自保
# ═══════════════════════════════════════════════════════════════
#
# 这是一次实测事故的回归测试：`uvm_tools/gen_uvm` 是照着独立 CLI 写的，
# schema 校验不过就 `raise SystemExit`。它在进程内跑在运行服务的 loop 线程上，
# 而 asyncio 的 `Task.__step` 对 SystemExit 是**捕获后原样重抛**的（刻意保留
# "终止"语义，不经过 await 链），`threading` 又把线程里的 SystemExit 静默吞掉。
# 于是 loop 线程无声消失、future 永不完成、worker 卡死在 `fut.result()` 上 ——
# 症状是「点了启动没反应」，而且**此后每一次启动都照样卡死**，只能重启程序。
#
# 这几条钉住的是：一个工具写成了 CLI 形状，不能让整个运行服务报废。

class TestToolCallingSysExit:
    """"点了启动没反应"那次事故的回归测试。

    `wait()` 而不是轮询 `busy`：**`busy` 在工人线程捡起任务之前就是 False**，
    拿它当"跑完了"会立刻为真，测出来的东西是假的。
    """

    @staticmethod
    def _boom(monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(system_exit=True, **kw))

    def test_the_loop_survives(self, svc, tmp_path, monkeypatch):
        self._boom(monkeypatch)
        run_id = svc.start(_req(tmp_path))
        with pytest.raises(Exception):          # SystemExit 被转成了普通异常
            svc.wait(run_id, timeout=20)
        assert svc._thread.is_alive(), "loop 线程被 SystemExit 打死了"
        assert svc._loop.is_running(), "loop 停了，之后的启动都会卡住"

    def test_the_failure_is_recorded_not_swallowed(self, svc, tmp_path, monkeypatch):
        """失败要如实记账 —— 否则界面上它永远是「运行中」，比报错更难查。"""
        self._boom(monkeypatch)
        run_id = svc.start(_req(tmp_path))
        with pytest.raises(Exception):
            svc.wait(run_id, timeout=20)
        kinds = [e["kind"] for e in svc.journal(run_id)]
        assert "run.failed" in kinds or "stage.failed" in kinds, \
            f"SystemExit 被吞了，日志里什么都没留下：{kinds}"

    def test_the_next_run_still_works(self, svc, tmp_path, monkeypatch):
        """**这条才是那次事故的要害**：一个工具把服务废掉之后，后面全卡死。"""
        self._boom(monkeypatch)
        boom = svc.start(_req(tmp_path, run_id="boom"))
        with pytest.raises(Exception):
            svc.wait(boom, timeout=20)

        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _graph(**kw))
        good = svc.start(_req(tmp_path, run_id="good"))
        assert svc.wait(good, timeout=20).get("status") == "PASS"

    def test_a_dead_loop_fails_fast_instead_of_hanging(self, svc, tmp_path):
        """循环线程要是真没了，宁可立刻报错也不要挂在 `fut.result()` 上。

        （上面几条是"不让它死"；这条是"万一还是死了"的兜底 —— 界面无声卡住
        比报错难查得多。）
        """
        import asyncio

        original = svc._ensure_loop()
        # 一个从没跑起来、也永远不会跑的循环 —— 相当于 loop 线程已经没了。
        # 换回来是必须的：夹具收尾的 `shutdown()` 要拿原循环去 stop。
        svc._loop = asyncio.new_event_loop()
        try:
            run_id = svc.start(_req(tmp_path))
            with pytest.raises(Exception, match="loop") as info:
                svc.wait(run_id, timeout=10)
            assert "loop" in str(info.value)
        finally:
            dead, svc._loop = svc._loop, original
            dead.close()


# ═══════════════════════════════════════════════════════════════
# 分层守卫
# ═══════════════════════════════════════════════════════════════

def test_no_qt_in_the_service_layer():
    """Qt 与 asyncio 只在一个地方交界 —— 而这个文件里不该有 Qt。

    真依赖上了的话，"换个界面"会变成"改服务层"，而服务层还要给 CLI 用。
    """
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import sys\n"
        "import src.orchestration_plane.l2.run_service\n"
        "bad = [m for m in sys.modules if m.startswith('PySide6')]\n"
        "print(bad)\n"
    )
    result = subprocess.run([sys.executable, "-c", code],
                            cwd=str(Path(__file__).resolve().parents[1]),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_no_qt_anywhere_in_the_layers():
    """**整个 `src/runtime_plane/` 都不许 import Qt。**

    `run_service.py` 的模块头写着这条规矩（"`grep PySide6 src/runtime_plane/` 必须为空"），
    但上面那个守卫只 import 了一个模块 —— 别处新加一份 Qt 依赖没人拦。证据层
    刚加了新文件，正好撞上这个缺口，所以补成**整层扫描**。

    用 AST 而不是 grep：文件里出现 "PySide6" 这个词不代表它 import 了它 ——
    `run_service` 的文档字符串本身就写着这个词，grep 会自己把自己判成违规。
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "layers"
    offenders = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n.split(".")[0] == "PySide6" for n in names):
                offenders.append(f"{path.relative_to(root.parent.parent)}:{node.lineno}")
    assert offenders == [], f"layers 里出现了 Qt 依赖：{offenders}"


def test_get_run_service_is_a_singleton():
    """"一次一个 run"这条约束只对单例有意义 —— 两个实例会互相不知道对方在跑。"""
    assert get_run_service() is get_run_service()


def test_vplan_project_is_mounted_into_the_run(svc, tmp_path, monkeypatch):
    """GUI/CLI 传的 VPlan 项目挂到 `<run>/inputs/vplan/`。"""
    monkeypatch.setenv("SIGNOFFAI_ALLOW_UNREVIEWED", "1")  # 跳过人工审阅门
    project = Path(__file__).resolve().parents[1] / "specs" / "npu_sched"
    run_id = svc.start(RunRequest(spec_text="# 假规格", vplan=str(project)))
    svc.wait(run_id, timeout=20)
    run_root = svc._handles[run_id].root       # noqa: SLF001 测试要看真实落点
    base = Path(run_root) / "inputs" / "vplan"
    assert (base / "data" / "execution_meta.csv").is_file()
    assert (base / "cases").is_dir()
    assert not (Path(run_root) / "inputs" / "casemodel.yaml").exists()
