"""端口协议分组 —— 单端口的 LLM 猜测不能劫持整份 spec。

真实故障：npu_sched 的 12 个 `instr_*` 端口里，LLM 把 1 个猜成 `axi`。
放行后 env 只生成了一个 `axi_agent`，其余 11 个端口走方向兜底 ——
DUT 检查器在 18 拍上求值为 X，整轮 p0 回归失败。
"""
from __future__ import annotations

import pytest

from src.tools.generation.uvm_tools.tool_find_spec_yaml import main as find_yaml


def _spec(*names, protocol=""):
    return {"interfaces": [
        {"name": n, "direction": "input", "data_width": 1, "protocol": protocol}
        for n in names
    ]}


def test_single_llm_only_port_group_falls_back_to_direction(monkeypatch):
    monkeypatch.setattr(find_yaml, "_llm_classify_protocols",
                        lambda names: {"instr_opcode": "axi"})
    groups = find_yaml._group_agents_by_protocol(
        _spec("instr_valid", "instr_opcode", "issue_valid"), {}, "npu_sched")
    # 没有可信协议边界 → 交给 _in/_out 方向拆分
    assert groups == []


def test_explicitly_declared_single_port_protocol_is_kept(monkeypatch):
    monkeypatch.setattr(find_yaml, "_llm_classify_protocols", lambda names: {})
    spec = {"interfaces": [
        {"name": "tx", "direction": "input", "data_width": 1, "protocol": "uart"},
        {"name": "misc", "direction": "input", "data_width": 1, "protocol": ""},
    ]}
    groups = find_yaml._group_agents_by_protocol(spec, {}, "dut")
    assert [ag["name"] for ag, _iface in groups] == ["uart"]


def test_multi_port_llm_group_is_kept(monkeypatch):
    """LLM 识别出真正的一组 AXI 端口时仍应保留。"""
    monkeypatch.setattr(find_yaml, "_llm_classify_protocols",
                        lambda names: {"awvalid": "axi", "wvalid": "axi"})
    groups = find_yaml._group_agents_by_protocol(
        _spec("awvalid", "wvalid", "misc"), {}, "dut")
    assert [ag["name"] for ag, _iface in groups] == ["axi"]
