"""RTL Upgrade Agent: independent agents using openai-agents/Runner loop."""

from src.agent_plane.reaction.core import ReActAgent, RoleSpec


class RTLUpgradeAgent(ReActAgent):
    ROLE = RoleSpec(
        role_id="rtl_upgrade_agent",
        domain="design_generation",
        title="RTL Upgrade Agent",
        responsibility="Inspect existing RTL and prepare ECN/change-request-aware upgrade steps in a bounded workspace.",
        inputs=("RTL + Change Request",),
        instructions="Distinguish upgrading existing RTL from spec-to-RTL generation. Inspect current design before changing. No unchecked overwrite of original files.",
        allowed_tools=("read_source", "list_source_files", "read_file", "list_rtl", "check_rtl"),
        write_allowed=True,
    )

    def backend_tools(self, workspace_root, output_root):
        from .tools import build_design_tools

        return [t for t in build_design_tools(workspace_root) if t.name in {"read_file", "list_rtl", "check_rtl"}]


def create_agent(**kwargs):
    return RTLUpgradeAgent(**kwargs)


__all__ = ["RTLUpgradeAgent", "create_agent"]
