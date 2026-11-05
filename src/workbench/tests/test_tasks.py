"""后台任务 —— 结果要回到主线程，界面线程不能被卡住。"""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QEventLoop, QTimer

from ..tasks import TaskRunner

TIMEOUT_MS = 5000


def run_task(runner: TaskRunner, fn, label: str = "任务", timeout_ms: int = TIMEOUT_MS):
    """先连信号再提交任务，返回 `(task_id, 收到的参数元组或 None)`。

    顺序不能反：`submit` 之后才连信号的话，一个跑得快的任务会在连接建立之前
    就把信号发完，测试随机失败 —— 这种竞态在开发机上几乎每次都「碰巧通过」。
    """
    captured = []
    loop = QEventLoop()

    def handler(*args):
        captured.append(args)
        loop.quit()

    runner.finished.connect(handler)
    runner.failed.connect(handler)
    task_id = runner.submit(label, fn)

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)
    loop.exec()

    runner.finished.disconnect(handler)
    runner.failed.disconnect(handler)
    return task_id, (captured[0] if captured else None)


class TestTaskRunner:
    def test_finished_carries_the_result(self, qt_app):
        runner = TaskRunner()
        task_id, got = run_task(runner, lambda: 6 * 7, "算一下")
        assert got == (task_id, 42)

    def test_failure_reports_the_exception_type_and_message(self, qt_app):
        runner = TaskRunner()

        def boom():
            raise ValueError("炸了")

        task_id, got = run_task(runner, boom, "会炸的任务")
        assert got == (task_id, "ValueError: 炸了")

    def test_started_fires_before_finished(self, qt_app):
        runner = TaskRunner()
        order = []
        runner.started.connect(lambda *a: order.append("started"))
        runner.finished.connect(lambda *a: order.append("finished"))
        run_task(runner, lambda: 1, "顺序")
        assert order[0] == "started" and order[-1] == "finished"

    def test_slot_runs_on_the_main_thread(self, qt_app):
        """worker 线程里碰控件会崩 —— 所以回调必须排队回主线程再执行。

        注意：要记的是**回调自己所在的线程**，不是任务返回的那个线程号 ——
        后者当然是 worker 的，那正是任务在后台跑的证明。
        """
        runner = TaskRunner()
        main_thread = threading.current_thread().ident
        seen = []

        def slot(_task_id, result):
            seen.append((threading.current_thread().ident, result))

        runner.finished.connect(slot)
        run_task(runner, lambda: "任务跑完了", "线程检查")

        assert seen, "回调没有触发"
        assert seen[0][0] == main_thread, "结果回调跑到 worker 线程上去了"
        assert seen[0][1] == "任务跑完了"

    def test_the_body_really_runs_off_the_main_thread(self, qt_app):
        """反过来也要成立：任务体本身必须在别的线程上，否则界面就是卡住的。"""
        runner = TaskRunner()
        main_thread = threading.current_thread().ident
        _task_id, got = run_task(
            runner, lambda: threading.current_thread().ident, "线程检查")
        assert got is not None
        assert got[1] != main_thread

    def test_submit_returns_immediately(self, qt_app):
        """慢任务不能阻塞提交方 —— 否则界面就是卡住的。"""
        runner = TaskRunner()
        runner.submit("慢任务", lambda: time.sleep(0.4))
        started = time.monotonic()
        runner.submit("第二个", lambda: 1)
        assert time.monotonic() - started < 0.3
        assert runner.wait(3000)

    def test_label_is_kept_for_the_console(self, qt_app):
        runner = TaskRunner()
        task_id = runner.submit("扫描仿真日志", lambda: None)
        assert runner.label(task_id) == "扫描仿真日志"
        assert runner.wait(3000)


class TestTaskRecords:
    """任务归属 —— 哪个模块起的、属于哪次验证，界面必须答得上来。"""

    def test_submit_records_ownership_and_lifecycle(self, qt_app):
        runner = TaskRunner()
        captured = []
        loop = QEventLoop()
        runner.finished.connect(lambda *a: (captured.append(a), loop.quit()))
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(TIMEOUT_MS)

        task_id = runner.submit("扫描", lambda: 42, module_id="flow.runs",
                                operation="scan", run_id="run-1")
        loop.exec()
        runner.wait(1000)

        rec = runner.record(task_id)
        assert (rec.module_id, rec.operation, rec.run_id) == ("flow.runs", "scan", "run-1")
        assert rec.status == "finished" and rec.result == 42
        assert rec.started_at and rec.finished_at
        assert [r.task_id for r in runner.records()] == [task_id]
        assert runner.pending() == []

    def test_failure_is_recorded_with_the_message(self, qt_app):
        runner = TaskRunner()

        def boom():
            raise RuntimeError("炸了")

        loop = QEventLoop()
        runner.failed.connect(lambda *a: loop.quit())
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(TIMEOUT_MS)

        task_id = runner.submit("构建", boom, module_id="ops.output")
        loop.exec()
        runner.wait(1000)

        rec = runner.record(task_id)
        assert rec.status == "failed"
        assert "RuntimeError" in rec.error and "炸了" in rec.error
        assert rec.finished_at
