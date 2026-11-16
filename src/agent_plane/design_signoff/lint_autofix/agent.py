"""Lint AutoFix: independent agents using openai-agents/Runner loop."""

from src.agent_plane.reaction.core import ReActAgent, RoleSpec
from src.agent_plane.reaction.tools import unavailable_tool


class LintAutoFixAgent(ReActAgent):
    ROLE = RoleSpec(
        role_id="lint_autofix",
        domain="design_signoff",
        title="Lint AutoFix",
        responsibility="Read evidence and propose lint diagnosis/candidate repairs; do not claim SuperLint runs or applied fixes.",
        inputs=("RTL + Spec",),
        instructions="SuperLint or actual repair execution is not configured. Never mark guessed lint findings as signed-off RTL.",
        allowed_tools=("read_source", "list_source_files", "run_superlint", "propose_lint_fix"),
        write_allowed=False,
    )

    def backend_tools(self, workspace_root, output_root):
        return [
            unavailable_tool("run_superlint", "Jasper SuperLint adapter", "本期未启用 SuperLint"),
            unavailable_tool(
                "propose_lint_fix", "lint repair generation and guarded review", "lint 修复生成与受控复核未完成接入"
            ),
        ]


def create_agent(**kwargs):
    return LintAutoFixAgent(**kwargs)


__all__ = ["LintAutoFixAgent", "create_agent"]
