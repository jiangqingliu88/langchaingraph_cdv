"""LLM spec 契约解析：JSON → 设计/模型契约；失败退回空。"""
from __future__ import annotations

import json

from src.generation.planning import dplan as llm_contract


def test_extract_contracts_parses_design_and_model(monkeypatch):
    payload = {
        "design_name": "npu_sched",
        "overview": "CMD scheduler",
        "interfaces": [
            {"name": "clk", "data_width": 1, "direction": "INPUT",
             "protocol": "clock", "description": "clock"},
            {"name": "instr_valid", "data_width": 1, "direction": "INPUT",
             "protocol": "generic", "description": "valid"},
        ],
        "registers": [
            {"name": "ctrl", "width": 32, "offset": "0x00", "access": "RW",
             "description": "control"},
        ],
        "features": [
            {"name": "issue", "priority": "P0", "description": "issue cmd"},
        ],
        "architecture": {"top": "npu_sched", "stages": ["decode", "issue"],
                         "method": "pipeline"},
        "modules": [{
            "name": "cmd_decode", "level": "sub", "parent": "npu_sched",
            "function": "decode instruction", "method": "combinational",
            "interfaces": [{"name": "instr_valid", "data_width": 1,
                            "direction": "INPUT"}],
            "combinational": ["decode_opcode"],
            "sequential": ["instr_valid_q"],
        }],
        "model_contract": {
            "module": "npu_sched",
            "ports": [
                {"name": "clk", "data_width": 1, "direction": "INPUT"},
            ],
            "state": ["queue_level"],
            "behaviors": [
                {"name": "raw_blocks", "when": "dep_type == RAW",
                 "expect": "issue_valid == 0", "checks": ["sva"]},
            ],
            "scoreboard": "npu_sched_scb",
        },
    }

    def fake_call_llm(*args, **kwargs):
        assert kwargs.get("output_format") == "json"
        assert kwargs.get("prompt_version")
        return json.dumps(payload)

    monkeypatch.setattr("src.tools.common.lib.llm_call.call_llm", fake_call_llm)
    doc = llm_contract.extract_contracts("a spec", module_hint="npu_sched")
    assert doc["design_name"] == "npu_sched"
    assert len(doc["interfaces"]) == 2
    assert doc["model_contract"]["behaviors"][0]["name"] == "raw_blocks"
    assert doc["architecture"]["top"] == "npu_sched"
    assert doc["modules"][0]["name"] == "cmd_decode"
    assert doc["modules"][0]["sequential"] == ["instr_valid_q"]


def test_extract_contracts_empty_on_llm_failure(monkeypatch):
    monkeypatch.setattr("src.tools.common.lib.llm_call.call_llm",
                        lambda *a, **k: "")
    assert llm_contract.extract_contracts("a spec") == {}


def test_extract_contracts_rejects_contract_without_ports_or_features(monkeypatch):
    monkeypatch.setattr(
        "src.tools.common.lib.llm_call.call_llm",
        lambda *a, **k: json.dumps({"design_name": "dut", "interfaces": [],
                                    "registers": [], "features": [],
                                    "model_contract": {}}))
    assert llm_contract.extract_contracts("spec") == {}


def test_extract_contracts_normalizes_llm_shapes(monkeypatch):
    payload = {
        "design_name": "npu_sched",
        "interfaces": [{"name": "clk", "data_width": "1",
                        "direction": "input"}],
        "registers": [{"name": "ctrl", "width": "32"}],
        "features": [{"name": "issue"}],
        # LLM 可能把 ports 写成一句说明而不是数组
        "model_contract": {"module": "npu_sched", "ports": "same as interfaces",
                           "behaviors": "no"},
    }
    monkeypatch.setattr("src.tools.common.lib.llm_call.call_llm",
                        lambda *a, **k: json.dumps(payload))
    doc = llm_contract.extract_contracts("spec")
    assert doc["interfaces"][0]["data_width"] == 1
    assert doc["registers"][0]["width"] == 32
    assert doc["model_contract"]["ports"] == doc["interfaces"]
    assert doc["model_contract"]["behaviors"] == []


def test_merge_contracts_prefers_llm_values():
    base = {"design_name": "dut", "interfaces": [{"name": "old"}],
            "features": []}
    merged = llm_contract.merge_contracts(base, {
        "design_name": "npu_sched",
        "interfaces": [{"name": "clk"}],
        "features": [{"name": "issue"}],
        "model_contract": {"module": "npu_sched"},
    })
    assert merged["design_name"] == "npu_sched"
    assert merged["interfaces"] == [{"name": "clk"}]
    assert merged["features"] == [{"name": "issue"}]
    assert merged["model_contract"]["module"] == "npu_sched"
