"""DV Debug Agent: independent agents using openai-agents/Runner loop."""

from src.agent_plane.reaction.core import ReActAgent, RoleSpec


class DVDebugAgent(ReActAgent):
    ROLE = RoleSpec(
        role_id="dv_debug_agent",
        domain="verification",
        title="DV Debug Agent",
        responsibility="Read actual failures, classify their evidence and propose RCA/candidate repairs.",
        inputs=("xcelium failure DB/log",),
        instructions="Do not create a failure DB or attribute an unobserved root cause. Missing engines/log backends are INCOMPLETE. Fix candidates must be independently checked.",
        allowed_tools=(
            "read_source",
            "list_source_files",
            "collect_sim_log",
            "collect_compile_log",
            "fingerprint_error",
        ),
        write_allowed=False,
    )

    def backend_tools(self, workspace_root, output_root):
        from src.engine_plane.diagnostics import DebugTools

        return [
            t
            for t in DebugTools().get_tools()
            if t.name in {"collect_sim_log", "collect_compile_log", "fingerprint_error"}
        ]


def create_agent(**kwargs):
    return DVDebugAgent(**kwargs)


__all__ = ["DVDebugAgent", "create_agent"]
