"""后台任务事件发布的回归守卫。

实测事故：主窗口拆分后，`main_window_layout.py` 里还调着
`_publish_task_started/_publish_task_done`，但定义留在 `app.py` 且没 import，
GUI 一有后台任务就 `NameError`（整条对话看起来"没有响应"）。这里钉两件事：
发布函数本身能发对话题；layout 里引用的 `_publish_*` 名字必须真的存在。
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from src.workbench.task_events import publish_task_done, publish_task_started
from src.workbench.topics import TOPIC_TASK_COMPLETED, TOPIC_TASK_STARTED


class _Bus:
    def __init__(self):
        self.calls = []

    def publish(self, topic, payload):
        self.calls.append((topic, payload))


def _ctx():
    return SimpleNamespace(bus=_Bus(), tasks=SimpleNamespace(record=lambda tid: None))


def test_publish_task_started_and_done_topics():
    ctx = _ctx()
    publish_task_started(ctx, "t-1", "对话")
    publish_task_done(ctx, "t-1")
    assert [c[0] for c in ctx.bus.calls] == [TOPIC_TASK_STARTED, TOPIC_TASK_COMPLETED]
    assert ctx.bus.calls[0][1]["task_id"] == "t-1"
    assert ctx.bus.calls[1][1]["task_id"] == "t-1"


def test_main_window_layout_references_only_defined_publishers():
    """静态检查：layout 里用到的 `_publish_*` 必须在模块命名空间里。"""
    import src.workbench.main_window_layout as layout

    tree = ast.parse(Path(layout.__file__).read_text(encoding="utf-8"))
    used = {node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and node.id.lstrip("_").startswith("publish_task_")}
    assert used, "layout 至少应通过 task_events 发布任务事件"
    assert used <= set(vars(layout)), used - set(vars(layout))
