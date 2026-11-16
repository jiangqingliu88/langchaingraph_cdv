"""Functional Coverage Agent: independent agents using openai-agents/Runner loop."""

from src.agent_plane.reaction.core import ReActAgent, RoleSpec
from src.agent_plane.reaction.tools import unavailable_tool


class FunctionalCoverageAgent(ReActAgent):
    ROLE = RoleSpec(
        role_id="functional_coverage_agent",
        domain="verification",
        title="Functional Coverage Agent",
        responsibility="Inspect coverage results and generate coverage/open-gap candidates; never claim formal unreachable elimination or complete closure.",
        inputs=("RTL (optional Spec)",),
        instructions="Coverage values require real data. Formal pruning without an actual proof backend stays NOT_RUN.",
        allowed_tools=("read_source", "list_source_files", "read_coverage", "list_coverage_files", "prune_unreachable"),
        write_allowed=False,
    )

    def backend_tools(self, workspace_root, output_root):
        from src.agent_plane.specialists.functional_coverage.tools import ListCoverageFilesTool, ReadCoverageTool

        return [
            ReadCoverageTool(workspace_root),
            ListCoverageFilesTool(workspace_root),
            unavailable_tool("prune_unreachable", "formal unreachable-bin pruning", "未配置该剔除后端"),
        ]


def create_agent(**kwargs):
    return FunctionalCoverageAgent(**kwargs)


__all__ = ["FunctionalCoverageAgent", "create_agent"]
