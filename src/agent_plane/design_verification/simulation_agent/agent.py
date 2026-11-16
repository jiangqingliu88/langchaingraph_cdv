"""Unit Testing Agent (simulation-agent): independent agents using openai-agents/Runner loop."""

from src.agent_plane.reaction.adapters import legacy_function_tool
from src.agent_plane.reaction.core import ReActAgent, RoleSpec
from src.agent_plane.reaction.tools import unavailable_tool


class SimulationAgent(ReActAgent):
    ROLE = RoleSpec(
        role_id="simulation_agent",
        domain="design_verification",
        title="Unit Testing Agent (simulation-agent)",
        responsibility="Generate directed SV unit-test candidates; execution and reports remain separate from generation.",
        inputs=("RTL + Spec",),
        instructions="Use actual RTL and specification inputs. Pure testbench generation never means a simulation pass. Actual compile/run is out of this phase.",
        allowed_tools=("read_source", "list_source_files", "generate_tb", "run_unit_test"),
        write_allowed=False,
    )

    def backend_tools(self, workspace_root, output_root):
        from src.agent_plane.specialists.unit_testing.main import generate_tb

        return [
            legacy_function_tool(
                "generate_tb",
                "directed pure-SV unit TB candidate",
                generate_tb,
                root=workspace_root,
                output_root=output_root,
            ),
            unavailable_tool("run_unit_test", "real SV compile/simulation backend", "本轮未启用仿真执行"),
        ]


def create_agent(**kwargs):
    return SimulationAgent(**kwargs)


__all__ = ["SimulationAgent", "create_agent"]
