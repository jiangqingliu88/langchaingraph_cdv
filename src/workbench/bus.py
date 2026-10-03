"""极简事件总线 —— 模块之间只通过话题通信，不互相 import。

为什么需要：三条业务线早晚会有协作（改一个 case 模型，覆盖视图要跟着刷）。
但「覆盖模块 import 建模模块」会让模块间长出一张网，插件化就名存实亡。
总线把这种耦合压成一条**明文的字符串话题**，读者在清单的 `params.subscribe`
里就能看出谁在听谁。

话题用点号命名（`input.changed`），与工具绑定名同一套风格。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

# ── 话题常量 ── 写成常量而不是散落的字符串字面量，改名时 grep 得到

#: 某个模块的业务输入变了（payload: ModuleSpec.id 与 Path）
TOPIC_INPUT_CHANGED = "input.changed"
#: 模块被激活（切标签页 / raise dock）（payload: ModuleSpec.id）
TOPIC_MODULE_ACTIVATED = "module.activated"
#: 状态栏消息（payload: str）
TOPIC_STATUS = "status.message"
#: 工具调用出错（payload: (name, message)）
TOPIC_TOOL_ERROR = "tool.error"
#: 控制台日志（payload: (level, text)）
TOPIC_LOG = "log"
#: 选中的运行变了（payload: run_id str）—— 左窗格的运行列表发，其余视图跟
TOPIC_RUN_SELECTED = "run.selected"
#: 某次运行的进度有新事件（payload: run_id str）
TOPIC_RUN_UPDATED = "run.updated"


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

    def subscribers(self, topic: str) -> int:
        """某话题的订阅数 —— 测试与自检用。"""
        return len(self._subs.get(topic, ()))
