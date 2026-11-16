"""Formal Agent: independent agents using openai-agents/Runner loop."""

from src.agent_plane.reaction.adapters import legacy_function_tool
from src.agent_plane.reaction.core import ReActAgent, RoleSpec
from src.agent_plane.reaction.tools import unavailable_tool


class FormalAgent(ReActAgent):
    ROLE = RoleSpec(
        role_id="formal_agent",
        domain="verification",
        title="Formal Agent",
        responsibility="Generate FormalPlan/SVA/checker/proof-obligation candidates; do not substitute for a proof engine.",
        inputs=("RTL (optional Spec)",),
        instructions="Engine.ran=false is preserved unless actual engine execution exists. A FormalPlan or SVA text is only a candidate for review.",
        allowed_tools=(
            "read_source",
            "list_source_files",
            "generate_formal_plan",
            "store_formal_plan",
            "run_formal_engine",
        ),
        write_allowed=True,
    )

    def backend_tools(self, workspace_root, output_root):
        from src.agent_plane.verification.formal_agent.main import generate_formal_plan, store_formal_plan
        from src.ir_plane.formal import FormalPlan

        def _convert_plan(*, plan, output_dir=None):
            validated = plan if isinstance(plan, FormalPlan) else FormalPlan.model_validate(plan)
            return store_formal_plan(output_dir, validated)

        generate = legacy_function_tool(
            "generate_formal_plan",
            "Spec to FormalPlan/IR with unverified proof obligations",
            generate_formal_plan,
            root=workspace_root,
            output_root=output_root,
        )
        store = legacy_function_tool(
            "store_formal_plan",
            "validated FormalPlan persistence",
            _convert_plan,
            root=workspace_root,
            output_root=output_root,
        )
        if output_root:
            setattr(store, "requires_approval", True)
        return [
            generate,
            store,
            unavailable_tool("run_formal_engine", "formal engine proof adapter", "本期未接入真实形式证明引擎"),
        ]


def create_agent(**kwargs):
    return FormalAgent(**kwargs)


__all__ = ["FormalAgent", "create_agent"]
