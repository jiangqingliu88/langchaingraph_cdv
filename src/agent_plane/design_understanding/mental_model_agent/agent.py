"""Mental Model Agent — an independent openai-agents ReAct package."""

from src.agent_plane.reaction.adapters import legacy_function_tool
from src.agent_plane.reaction.core import ReActAgent, RoleSpec


class MentalModelAgent(ReActAgent):
    ROLE = RoleSpec(
        role_id="mental_model_agent",
        domain="design_understanding",
        title="Mental Model Agent",
        responsibility="Build/update a reviewable mental model and check documented RTL/Spec understanding.",
        inputs=("RTL + Spec",),
        instructions="Read source before generating. Preserve anchors. RTL text or spec text must be supplied instead of claiming full-chip understanding. Candidates require human review.",
        allowed_tools=("read_source", "list_source_files", "generate_mental_ir", "store_mental_ir"),
        write_allowed=True,
    )

    def backend_tools(self, workspace_root, output_root):
        from src.mental_ir_plane import MentalIR

        from . import write_mental_ir
        from .main import generate_mental_ir

        def _store(*, ir, output_dir=None):
            validated = ir if isinstance(ir, MentalIR) else MentalIR.model_validate(ir)
            return write_mental_ir(output_dir, validated)

        generate = legacy_function_tool(
            "generate_mental_ir",
            "reviewable Mental IR generation",
            generate_mental_ir,
            root=workspace_root,
            output_root=output_root,
        )
        store = legacy_function_tool(
            "store_mental_ir", "validated Mental IR persistence", _store, root=workspace_root, output_root=output_root
        )
        if output_root:
            setattr(store, "requires_approval", True)
        return [generate, store]


def create_agent(**kwargs):
    return MentalModelAgent(**kwargs)


__all__ = ["MentalModelAgent", "create_agent"]
