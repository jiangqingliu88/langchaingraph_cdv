from __future__ import annotations

from src.tools.generation.uvm_tools.tool_uvm.ir.uvm_ir import (
    UVMConnectionIR, build_uvm_ir, validate_agent_ir, validate_ir,
)
from src.tools.generation.uvm_tools.tool_uvm.models import EnvSpec


def _spec():
    return EnvSpec(module="dut", agents=[
        {"name": "apb", "type": "UVM_ACTIVE",
         "ports": [{"name": "pclk", "direction": "input"},
                   {"name": "pwdata", "direction": "input"}]},
        {"name": "mon", "type": "UVM_PASSIVE",
         "ports": [{"name": "prdata", "direction": "output"}]},
    ], tests=[
        {"name": "smoke_test", "agent": "apb", "tags": ["p0"]},
    ])


def test_builds_ir_from_env_spec():
    ir = _spec().to_uvm_ir()
    assert ir.module == "dut"
    assert [a.name for a in ir.agents] == ["apb", "mon"]
    assert ir.agent("apb").ports[0].name == "pclk"
    assert ir.tests[0].agents == ["apb"]
    assert ir.env.agents == ["apb", "mon"]
    assert ir.schema == "uvm_ir_v1"


def test_validate_accepts_a_consistent_ir():
    assert validate_ir(_spec().to_uvm_ir()) == []


def test_validate_reports_unknown_test_agent():
    spec = _spec()
    spec.tests.append({"name": "bad", "agent": "ghost"})
    issues = validate_ir(spec.to_uvm_ir())
    assert any(i["code"] == "test_agent_unknown" for i in issues)


def test_validate_reports_duplicate_and_missing_ports():
    spec = EnvSpec(module="dut", agents=[
        {"name": "a", "ports": []},
        {"name": "a", "ports": [{"name": "p", "direction": "sideways"}]},
    ])
    codes = {i["code"] for i in validate_ir(spec.to_uvm_ir())}
    assert "agent_duplicate" in codes
    assert "agent_ports_missing" in codes
    assert "port_direction_invalid" in codes


def test_validate_connection_checks_agents_and_ports():
    spec = _spec()
    ir = spec.to_uvm_ir()
    ir.connections.append(UVMConnectionIR("apb", "pclk", "mon", "nope"))
    codes = {i["code"] for i in validate_ir(ir)}
    assert "connection_port_unknown" in codes
    ir.connections.append(UVMConnectionIR("ghost", "x", "apb", "pclk"))
    codes = {i["code"] for i in validate_ir(ir)}
    assert "connection_agent_unknown" in codes


# ── 渲染期真正消费 IR：解析后的模型也要能映射 ──

def _agent(**kw):
    from src.tools.generation.uvm_tools.tool_uvm.models import AgentModel

    base = dict(name="apb", agent_name="apb", interface="apb",
                interface_name="apb")
    base.update(kw)
    return AgentModel(**base)


def test_environment_model_maps_to_ir():
    from src.tools.generation.uvm_tools.tool_uvm.models import (
        AgentCollection, EnvironmentModel,
    )

    env = EnvironmentModel(name="apb_env", env_name="apb_env",
                           agents=AgentCollection([
                               _agent(), _agent(name="apb_slave"),
                           ]))
    ir = env.to_uvm_ir()
    assert ir.env.name == "apb_env"
    assert ir.env.agents == ["apb", "apb_slave"]
    assert ir.agents[0].interface == "apb"
    assert ir.agents[0].agent_type == "apb_agent"


def test_agent_model_port_direction_uses_dir_key():
    """接口 YAML 写 `dir:`（AXI-VIP 风格）—— IR 必须认这个键，否则方向全丢。"""
    agent = _agent(ports=[{"name": "pwrite", "dir": "output", "width": 1}])
    ir = agent.to_uvm_ir()
    assert ir.ports[0].direction == "output"
    assert validate_agent_ir(ir) == []


def test_validate_agent_ir_flags_empty_name_and_bad_direction():
    agent = _agent(ports=[{"name": "", "dir": "sideways"}])
    codes = {i["code"] for i in validate_agent_ir(agent.to_uvm_ir())}
    assert "port_name_missing" in codes
    assert "port_direction_invalid" in codes


def test_env_level_validation_does_not_require_ports():
    """`EnvironmentModel` 的 agent 只声明名字，端口在 interface 侧。"""
    from src.tools.generation.uvm_tools.tool_uvm.models import EnvironmentModel

    env = EnvironmentModel(name="e", env_name="e")
    env.agents.append(_agent())          # 没有端口
    ir = env.to_uvm_ir()
    assert any(i["code"] == "agent_ports_missing" for i in validate_ir(ir))
    assert validate_ir(ir, require_ports=False) == []


def test_environment_model_reports_duplicate_agents():
    from src.tools.generation.uvm_tools.tool_uvm.models import (
        AgentCollection, EnvironmentModel,
    )

    env = EnvironmentModel(name="e", env_name="e",
                           agents=AgentCollection([_agent(), _agent()]))
    codes = {i["code"] for i in validate_ir(env.to_uvm_ir(), require_ports=False)}
    assert "agent_duplicate" in codes
