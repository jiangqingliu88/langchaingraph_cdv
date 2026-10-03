"""后台任务 —— 编译、仿真、回归、覆盖率收集都不能卡住界面。

做法是 Qt 的标配组合：`QThreadPool` 跑 `QRunnable`，结果通过一个
**活在主线程的** `QObject` 发信号回来。跨线程连信号会自动排队投递到接收者
所属线程，所以槽函数是在主线程跑的 —— 可以直接碰控件。

刻意不提供的：取消、优先级、进度百分比。跑起来的仿真停不掉（那是 EDA 工具
自己的事），给一个点不动的「取消」按钮比没有更糟。
"""
from __future__ import annotations

import itertools
import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

_ids = itertools.count(1)


class TaskSignals(QObject):
    """任务结果的落点。**必须建在主线程**，否则信号不会排队回主线程。"""

    started = Signal(str, str)          # task_id, label
    finished = Signal(str, object)      # task_id, result
    failed = Signal(str, str)           # task_id, "ExceptionType: message"


class _Task(QRunnable):
    def __init__(self, task_id: str, label: str, fn: Callable[[], Any],
                 signals: TaskSignals) -> None:
        super().__init__()
        self.task_id = task_id
        self.label = label
        self.fn = fn
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:                     # 在工作线程里执行
        self.signals.started.emit(self.task_id, self.label)
        try:
            result = self.fn()
        except Exception as exc:               # noqa: BLE001  后台异常不能掀掉线程池
            # traceback 只进日志、不进信号：信号是给界面看的，一屏放不下栈
            message = f"{type(exc).__name__}: {exc}"
            self.signals.failed.emit(self.task_id, message)
            _ = traceback.format_exc()
        else:
            self.signals.finished.emit(self.task_id, result)


class TaskRunner(QObject):
    """提交后台任务并把结果转回主线程。

    用法：
        runner.finished.connect(self._on_result)
        runner.submit("扫描仿真日志", lambda: registry.call("debug.collect_sim_log", ...))
    """

    started = Signal(str, str)
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, parent: Optional[QObject] = None,
                 max_threads: Optional[int] = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        if max_threads:
            self._pool.setMaxThreadCount(max_threads)
        self._signals = TaskSignals(self)
        # 转一手而不是让调用方直接连 TaskSignals：外部只该看到 TaskRunner 这一层。
        #
        # 这里能靠 signal→signal 转发把线程掰回来，是因为**收发双方都归属主线程**
        # （TaskRunner 与 TaskSignals 都在主线程创建）：worker 线程发信号时，
        # 接收者不在当前线程，Qt 会自动改成排队投递，于是在主线程重发一次。
        # 调用方之后连的就是主线程上的信号，哪怕只连了个普通 lambda 也是安全的。
        # —— 换成在 worker 里直接发、或接收者归属 worker 线程，就没有这层保护了。
        self._signals.started.connect(self.started)
        self._signals.finished.connect(self.finished)
        self._signals.failed.connect(self.failed)
        self._labels: dict = {}

    def submit(self, label: str, fn: Callable[[], Any]) -> str:
        """排入线程池，返回 task_id。fn 会在工作线程执行，**不要碰控件**。"""
        task_id = f"task-{next(_ids)}"
        self._labels[task_id] = label
        self._pool.start(_Task(task_id, label, fn, self._signals))
        return task_id

    def label(self, task_id: str) -> str:
        return self._labels.get(task_id, "")

    def wait(self, timeout_ms: int = 10_000) -> bool:
        """等待所有任务结束 —— 测试与关闭窗口时用。"""
        return self._pool.waitForDone(timeout_ms)
