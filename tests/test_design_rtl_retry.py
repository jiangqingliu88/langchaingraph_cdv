"""design 写手的重试必须真的换 prompt（否则进程内缓存会原样返回坏 RTL）。"""
from __future__ import annotations

from src.skills.design.main import DesignExecutor


def test_retry_prompt_contains_attempt_and_compile_feedback(monkeypatch):
    seen = {}

    def fake_llm(prompt, *args, **kwargs):
        seen["prompt"] = prompt
        return "module foo (); endmodule\n"

    monkeypatch.setattr("src.tools.common.lib.llm_call.call_llm", fake_llm)
    ip = {"ip_name": "scoreboard", "category": "logic",
          "function_desc": "状态表比较", "interface": [],
          "combinational": [], "sequential": [], "method": "state"}
    DesignExecutor._llm_write_ip(
        ip, {"interfaces": []}, attempt=2,
        feedback="** Error: (vlog-7) Failed to open design unit")

    prompt = seen["prompt"]
    assert "第 2 次尝试" in prompt
    assert "vlog-7" in prompt


def test_rtl_ports_resolves_parameterized_width(tmp_path):
    (tmp_path / "sb.sv").write_text(
        "module sb #(parameter int W = 64) (\n"
        "  input  logic [W-1:0] bus,\n"
        "  output logic         ok\n);\nendmodule\n", encoding="utf-8")
    ports = {p["name"]: p for p in DesignExecutor._rtl_ports(tmp_path, "sb")}
    assert ports["bus"]["width"] == 64
    assert ports["ok"]["width"] == 1


def test_top_generator_zero_extends_narrow_driver(tmp_path):
    """1-bit 驱动 → 64-bit 读口必须显式零扩展（否则 Questa 高位接成 Z）。"""
    spec = {
        "design_name": "top",
        "architecture": {"top": "top"},
        "interfaces": [{"name": "clk", "data_width": 1, "protocol": "clock"},
                       {"name": "rst_n", "data_width": 1, "protocol": "reset"}],
        "modules": [{"name": "top", "level": "top", "interfaces": [
            {"name": "clk", "data_width": 1, "protocol": "clock"},
            {"name": "rst_n", "data_width": 1, "protocol": "reset"}]}],
    }
    ips = [
        {"ip_name": "prod", "_ports": [
            {"name": "bus", "width": 1, "direction": "OUTPUT", "drives": True}]},
        {"ip_name": "cons", "_ports": [
            {"name": "bus", "width": 64, "direction": "INPUT", "drives": False}]},
    ]
    top = DesignExecutor._gen_top_module("top", ips, spec)
    assert "wire bus;" in top
    assert ".bus({{63{1'b0}}, bus})" in top


def test_top_generator_connects_ports_by_name():
    """确定性顶层兜底不能只连 clk/rst —— 否则所有子模块悬空、输出恒 X。"""
    spec = {
        "design_name": "top",
        "architecture": {"top": "top"},
        "interfaces": [
            {"name": "clk", "data_width": 1, "direction": "INPUT", "protocol": "clock"},
            {"name": "rst_n", "data_width": 1, "direction": "INPUT", "protocol": "reset"},
            {"name": "cmd_vld", "data_width": 1, "direction": "INPUT"},
            {"name": "cmd_rdy", "data_width": 1, "direction": "OUTPUT"},
        ],
        "modules": [{"name": "top", "level": "top", "interfaces": [
            {"name": "clk", "data_width": 1, "direction": "INPUT", "protocol": "clock"},
            {"name": "rst_n", "data_width": 1, "direction": "INPUT", "protocol": "reset"},
            {"name": "cmd_vld", "data_width": 1, "direction": "INPUT"},
            {"name": "cmd_rdy", "data_width": 1, "direction": "OUTPUT"},
        ]}],
    }
    ips = [
        {"ip_name": "decode", "interface": [
            {"name": "cmd_vld", "data_width": 1},
            {"name": "internal_bus", "data_width": 8},
            {"name": "cmd_rdy", "data_width": 1, "direction": "OUTPUT"}]},
        {"ip_name": "dispatch", "interface": [
            {"name": "internal_bus", "data_width": 8},
            {"name": "cmd_rdy", "data_width": 1, "direction": "OUTPUT"}]},
    ]
    top = DesignExecutor._gen_top_module("top", ips, spec)
    assert ".cmd_vld(cmd_vld)" in top
    assert ".cmd_rdy(cmd_rdy)" in top
    assert "wire [7:0] internal_bus;" in top
    assert ".internal_bus(internal_bus)" in top
    # 同名输出只能有一个主驱动；第二个接 shadow，避免 vopt multi-driver
    assert "wire __dispatch_cmd_rdy;" in top
    assert ".cmd_rdy(__dispatch_cmd_rdy)" in top
    # 不再是只有 clk/rst 的骨架
    assert top.count("    .") > 4


def test_first_attempt_prompt_has_no_retry_noise(monkeypatch):
    seen = {}

    def fake_llm(prompt, *args, **kwargs):
        seen["prompt"] = prompt
        return "module foo (); endmodule\n"

    monkeypatch.setattr("src.tools.common.lib.llm_call.call_llm", fake_llm)
    DesignExecutor._llm_write_ip(
        {"ip_name": "x", "category": "logic", "function_desc": "f",
         "interface": [], "combinational": [], "sequential": [], "method": ""},
        {"interfaces": []})
    assert "次尝试" not in seen["prompt"]
