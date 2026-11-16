"""RTL Early Estimation Agent: independent agents using openai-agents/Runner loop."""

from src.agent_plane.reaction.core import ReActAgent, RoleSpec
from src.agent_plane.reaction.tools import unavailable_tool


class RTLEarlyEstimationAgent(ReActAgent):
    ROLE = RoleSpec(
        role_id="rtl_early_estimation_agent",
        domain="design_generation",
        title="RTL Early Estimation Agent",
        responsibility="Prepare early PPA inputs and uncertainties; no Joules execution or measured PPA claim.",
        inputs=("RTL",),
        instructions="Never invent power/performance/area numbers or claim an estimate was measured. Require a real backend and observable tool evidence.",
        allowed_tools=("read_source", "list_source_files", "estimate_ppa"),
        write_allowed=False,
    )

    def backend_tools(self, workspace_root, output_root):
        return [
            unavailable_tool("estimate_ppa", "Joules experimental PPA adapter", "未接入Joules/PPA执行后端，不生成数值")
        ]


def create_agent(**kwargs):
    return RTLEarlyEstimationAgent(**kwargs)


__all__ = ["RTLEarlyEstimationAgent", "create_agent"]
