"""后台任务生命周期 → 事件总线。

主窗口（`main_window_layout`）和入口（`app`）都要发这两条事件，但前者不能
从后者 import —— `app` 会 import 主窗口，反过来就是循环导入。所以发布逻辑
拆到这个中立模块，两边共用一份。

实测事故：拆分主窗口时把函数的**调用**留在了 `main_window_layout.py`，
定义留在了 `app.py` 且没 import —— GUI 一有后台任务就报
`NameError: name '_publish_task_done' is not defined`。
"""
from __future__ import annotations

from .context import AppContext
from .topics import (
    TOPIC_TASK_COMPLETED, TOPIC_TASK_STARTED, TaskCompleted, TaskStarted,
)


def publish_task_started(ctx: AppContext, task_id: str, label: str) -> None:
    """任务开始 → `task.started`（带上模块归属与所属 run）。"""
    rec = ctx.tasks.record(task_id)
    ctx.bus.publish(TOPIC_TASK_STARTED, TaskStarted(
        task_id=task_id,
        module_id=rec.module_id if rec else "",
        operation=rec.operation if rec else label,
        run_id=rec.run_id if rec else "").to_payload())


def publish_task_done(ctx: AppContext, task_id: str) -> None:
    """任务结束（成功或失败）→ `task.completed`。"""
    rec = ctx.tasks.record(task_id)
    ctx.bus.publish(TOPIC_TASK_COMPLETED, TaskCompleted(
        task_id=task_id,
        status=rec.status if rec else "",
        run_id=rec.run_id if rec else "",
        error=rec.error if rec else "").to_payload())


__all__ = ["publish_task_started", "publish_task_done"]
