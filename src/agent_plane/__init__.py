"""Agent Plane facade (Architecture 4.0).

Implementation lives in `src/agent_plane/{runtime,memory,planner,subagents}/`.
"""
from src.agent_plane.runtime.harness import Harness, HarnessConfig
from src.agent_plane.memory import (
    ProjectMemory, TaskStore, render_working, working_summary,
)
from src.agent_plane.planner import (
    acceptance_met, downstream_of, layers, new_plan, replan, should_replan,
)
from src.agent_plane.collaboration import (
    AGENT_TYPES, SubagentContract, SubagentManager, SubagentResult,
    build_contract,
)

from src.workbench.modes.agent_mode import run_goal

__all__ = [
    "run_goal", "Harness", "HarnessConfig", "ProjectMemory", "TaskStore",
    "render_working", "working_summary", "new_plan", "replan",
    "should_replan", "acceptance_met", "downstream_of", "layers",
    "AGENT_TYPES", "SubagentContract", "SubagentResult", "SubagentManager",
    "build_contract",
]
