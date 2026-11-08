"""极简事件总线 —— 模块之间只通过话题通信，不互相 import。

为什么需要：三条业务线早晚会有协作（换一次运行，覆盖视图要跟着刷）。
但「覆盖模块 import 建模模块」会让模块间长出一张网，插件化就名存实亡。
总线把这种耦合压成一条**明文的字符串话题**，读者在清单的 `params.subscribe`
里就能看出谁在听谁。

话题用点号命名（`input.changed`），与工具绑定名同一套风格。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

# 话题名与 payload 形状的唯一真相在 `topics.py`；这里 re-export，旧 import 不用改。
from .topics import (  # noqa: F401
    TOPIC_DECISION_UPDATED, TOPIC_EVIDENCE_UPDATED, TOPIC_INPUT_CHANGED,
    TOPIC_LOG, TOPIC_MODULE_ACTIVATED, TOPIC_RUN_COMPLETED, TOPIC_RUN_SELECTED,
    TOPIC_RUN_UPDATED, TOPIC_STATUS, TOPIC_TASK_COMPLETED, TOPIC_TASK_STARTED,
    TOPIC_TOOL_ERROR, RunSelected, RunUpdated, run_id_of,
)


class EventBus(QObject):
    """同步发布/订阅。发布即回调 —— 不做队列，避免「事件到了但界面还没建好」。

    发布方负责在主线程调用；跨线程的活儿走 `tasks.TaskRunner`，它的结果
    回到主线程后再发布。
    """

    #: 任何一次发布都会发一次，供测试与日志旁听
    published = Signal(str, object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._subs: Dict[str, List[Callable[[Any], None]]] = {}

    def subscribe(self, topic: str, slot: Callable[[Any], None]) -> Callable[[], None]:
        """订阅话题，返回退订函数 —— 谁订阅谁负责退订（模块销毁时用）。"""
        self._subs.setdefault(topic, []).append(slot)

        def unsubscribe() -> None:
            slots = self._subs.get(topic, [])
            if slot in slots:
                slots.remove(slot)

        return unsubscribe

    def publish(self, topic: str, payload: Any = None) -> None:
        for slot in list(self._subs.get(topic, ())):
            slot(payload)
        self.published.emit(topic, payload)

    def publish_run_selected(self, run_id: str, **fields: Any) -> None:
        """按契约发布 `run.selected`（dict 形状，见 `topics.RunSelected`）。

        订阅方用 `run_id_of(payload)` 取 run_id —— 它也认旧的字面量字符串。
        """
        self.publish(TOPIC_RUN_SELECTED,
                     RunSelected(run_id=str(run_id), **fields).to_payload())

    def publish_run_updated(self, run_id: str, **fields: Any) -> None:
        self.publish(TOPIC_RUN_UPDATED,
                     RunUpdated(run_id=str(run_id), **fields).to_payload())

    def subscribers(self, topic: str) -> int:
        """某话题的订阅数 —— 测试与自检用。"""
        return len(self._subs.get(topic, ()))
