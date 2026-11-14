"""Mental 专家子图（独立路径）：generate → store。

不挂 supervisor 主图：这一版先保证「能独立跑通、产物可审阅」。
将来若要进闭环，只需在 supervisor 里加一个节点并在 verify 之前路由过来。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.mental_ir_plane import MentalIR, write_mental_ir


class MentalState(TypedDict, total=False):
    spec_text: str
    output_dir: str
    module: str
    spec_path: str
    mental_ir: dict[str, Any]
    result: dict[str, Any]


async def n_generate(state: MentalState, config) -> dict[str, Any]:
    from .main import generate_mental_ir

    ir = await asyncio.to_thread(
        generate_mental_ir,
        state.get("spec_text", ""),
        module=str(state.get("module") or "dut"),
        spec_path=str(state.get("spec_path") or ""),
        output_dir=Path(state.get("output_dir") or "."),
    )
    return {"mental_ir": ir.model_dump(mode="json")}


async def n_store(state: MentalState, config) -> dict[str, Any]:
    ir = MentalIR.model_validate(state.get("mental_ir") or {})
    files = write_mental_ir(state.get("output_dir") or ".", ir)
    return {
        "result": {
            "status": "ok",
            "module": ir.module,
            "digest": files["digest"],
            "counts": files["counts"],
            "files": files,
        }
    }


def build_mental_graph():
    g = StateGraph(MentalState)
    g.add_node("generate", n_generate)
    g.add_node("store", n_store)
    g.add_edge(START, "generate")
    g.add_edge("generate", "store")
    g.add_edge("store", END)
    return g.compile()


__all__ = ["MentalState", "n_generate", "n_store", "build_mental_graph"]
