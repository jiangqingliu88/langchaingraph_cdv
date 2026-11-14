"""Unit Testing 专家子图（独立路径）。

只有一个真实节点：`run()` 内部完成 生成 TB → 编译 → 运行 → report。
保留子图形态是为了将来挂 supervisor 时无需改调用方。
"""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class UnitTestState(TypedDict, total=False):
    rtl_path: str
    output_dir: str
    module: str
    compile: bool
    simulate: bool
    result: dict[str, Any]


async def n_unit_test(state: UnitTestState, config) -> dict[str, Any]:
    from .main import run

    result = await asyncio.to_thread(
        run,
        state.get("rtl_path", ""),
        state.get("output_dir", "."),
        module=str(state.get("module") or ""),
        compile=bool(state.get("compile", True)),
        simulate=bool(state.get("simulate", True)),
    )
    return {"result": result}


def build_unit_test_graph():
    g = StateGraph(UnitTestState)
    g.add_node("unit_test", n_unit_test)
    g.add_edge(START, "unit_test")
    g.add_edge("unit_test", END)
    return g.compile()


__all__ = ["UnitTestState", "n_unit_test", "build_unit_test_graph"]
