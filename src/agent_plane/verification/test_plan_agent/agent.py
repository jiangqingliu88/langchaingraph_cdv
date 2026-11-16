"""Test Plan Agent: independent agents using openai-agents/Runner loop."""

from src.agent_plane.reaction.core import ReActAgent, RoleSpec
from src.agent_plane.reaction.tools import unavailable_tool


class TestPlanAgent(ReActAgent):
    ROLE = RoleSpec(
        role_id="test_plan_agent",
        domain="verification",
        title="Test Plan Agent",
        responsibility="Produce Spec-grounded UVM test plan and feature/obligation candidates.",
        inputs=("Spec (required)",),
        instructions="Require actual spec. Do not make another agent name into TP Test Plan truth. Do not promote an unconnected generic VPlan CLI into verified TP synthesis.",
        allowed_tools=("read_source", "list_source_files", "generate_test_plan"),
        write_allowed=False,
    )

    def backend_tools(self, workspace_root, output_root):
        return [
            unavailable_tool(
                "generate_test_plan",
                "Spec-grounded test-plan synthesizer",
                "现有Specification/VPlan角色适配尚未绑定；未运行测试计划生成",
            )
        ]


def create_agent(**kwargs):
    return TestPlanAgent(**kwargs)


__all__ = ["TestPlanAgent", "create_agent"]
