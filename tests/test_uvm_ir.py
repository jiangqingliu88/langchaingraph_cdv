from __future__ import annotations

from src.tools.generation.uvm_tools.generation.ir.uvm_ir import (
    UVMConnectionIR, build_uvm_ir, validate_ir,
)
from src.tools.generation.uvm_tools.generation.models import EnvSpec


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
