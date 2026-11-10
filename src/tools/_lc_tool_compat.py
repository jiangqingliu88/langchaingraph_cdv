"""
langchain-core 1.x 兼容垫片 —— 让 `@tool` 装饰后的对象重新可调用。

背景
    langchain-core 0.1.x 的 BaseTool 实例可以直接调用（转发到原函数）；
    1.x 移除了这个行为，实例调用会抛
        TypeError: 'StructuredTool' object is not callable

    本仓库有 49 处 `@tool("name")`，且大量调用点把工具对象当普通函数用
    （如 src/skills/design/main.py:53、src/layers/l2_orchestration/execution.py:366、
    src/skills/verify/main.py:143、src/skills/debug/main.py:119），
    升级到 langchain-core 1.x 后会全部失败。

做法
    产出的对象仍然是 StructuredTool 实例 —— isinstance / .invoke / .run /
    create_openai_tools_agent 都不受影响 —— 只是额外实现了 __call__，
    转发到 .func（即被装饰的原函数）。

退出条件
    这是过渡措施。P1 会把「直接 import 工具函数」的旁路调用点收敛到 ToolHub
    （见 docs/design/full_project_refactoring_plan.md ADR-3），届时本文件可删除。
"""
from typing import Any, Callable

from langchain_core.tools import StructuredTool
from langchain_core.tools import tool as _lc_tool


class CallableStructuredTool(StructuredTool):
    """StructuredTool 子类：额外支持直接调用，转发到 .func。"""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.func(*args, **kwargs)


def _as_callable(tool_obj: Any) -> Any:
    """就地把 BaseTool 实例换成可调用版本（改类而非拷贝，保留全部字段）。"""
    if isinstance(tool_obj, StructuredTool):
        tool_obj.__class__ = CallableStructuredTool
    return tool_obj


def tool(*args: Any, **kwargs: Any) -> Any:
    """`langchain_core.tools.tool` 的替代品：产出的工具对象可直接调用。

    同时支持 `@tool("name")` 与裸 `@tool` 两种写法。
    """
    # 裸 @tool 用法：args[0] 是被装饰的函数，langchain 直接返回 BaseTool
    if args and not isinstance(args[0], str) and callable(args[0]):
        return _as_callable(_lc_tool(*args, **kwargs))

    decorate = _lc_tool(*args, **kwargs)

    def _wrap(fn: Callable) -> Any:
        return _as_callable(decorate(fn))

    return _wrap
