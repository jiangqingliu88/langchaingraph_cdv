"""UVM Coding Agent: independent agents using openai-agents/Runner loop."""

from src.agent_plane.reaction.core import ReActAgent, RoleSpec


class UVMCodingAgent(ReActAgent):
    ROLE = RoleSpec(
        role_id="uvm_coding_agent",
        domain="verification",
        title="UVM Coding Agent",
        responsibility="Create or upgrade UVM components in an explicitly bounded output workspace.",
        inputs=("UVM TB (may create)",),
        instructions="Use generation helpers and existing environment checks rather than duplicate code. Code is a candidate until actual verification. No unbounded production writes.",
        allowed_tools=(
            "read_source",
            "list_source_files",
            "find_spec_yaml",
            "jinja_render",
            "check_static",
            "read_file",
            "write_file",
        ),
        write_allowed=True,
    )

    def backend_tools(self, workspace_root, output_root):
        from .tools import build_uvm_tools

        return build_uvm_tools(workspace_root, output_root)


def create_agent(**kwargs):
    return UVMCodingAgent(**kwargs)


__all__ = ["UVMCodingAgent", "create_agent"]
