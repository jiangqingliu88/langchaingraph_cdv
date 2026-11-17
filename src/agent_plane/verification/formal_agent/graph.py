"""Formal 专家子图（独立路径）：generate → store。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.mental_ir_plane.formal import FormalPlan


class FormalState(TypedDict, total=False):
    spec_text: str
    output_dir: str
    module: str
    spec_path: str
    formal_plan: dict[str, Any]
    result: dict[str, Any]


async def n_generate(state: FormalState, config) -> dict[str, Any]:
    from .main import generate_formal_plan

    plan = await asyncio.to_thread(
        generate_formal_plan,
        state.get("spec_text", ""),
        module=str(state.get("module") or "dut"),
        spec_path=str(state.get("spec_path") or ""),
        output_dir=Path(state.get("output_dir") or "."),
    )
    return {"formal_plan": plan.model_dump(mode="json")}


async def n_store(state: FormalState, config) -> dict[str, Any]:
    from .main import store_formal_plan

    plan = FormalPlan.model_validate(state.get("formal_plan") or {})
    files = store_formal_plan(state.get("output_dir") or ".", plan)
    return {
        "result": {
            "status": "ok",
            "module": plan.module,
            "digest": files["digest"],
            "counts": files["counts"],
            "engine": plan.engine,
            "files": files,
        }
    }


def build_formal_graph():
    g = StateGraph(FormalState)
    g.add_node("generate", n_generate)
    g.add_node("store", n_store)
    g.add_edge(START, "generate")
    g.add_edge("generate", "store")
    g.add_edge("store", END)
    return g.compile()


__all__ = ["FormalState", "n_generate", "n_store", "build_formal_graph"]
