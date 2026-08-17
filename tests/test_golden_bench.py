"""黄金模型 bench 接入测试：ref_model 配置生成 + tb_top 模板渲染。

验证"参考模型比对真正发生"的接入链路（修复历史缺口：ref_model_enabled 默认 false）。
"""
from pathlib import Path

import jinja2

from src.tools.lib.golden_library import build_ref_model_config

APB_INTERFACES = [
    {"name": "pclk", "direction": "input", "protocol": "Clock"},
    {"name": "preset_n", "direction": "input", "protocol": "Reset"},
    {"name": "paddr", "direction": "input", "protocol": "APB"},
    {"name": "pwdata", "direction": "input", "protocol": "APB"},
    {"name": "prdata", "direction": "output", "protocol": "APB"},
    {"name": "pwrite", "direction": "input", "protocol": "APB"},
    {"name": "psel", "direction": "input", "protocol": "APB"},
    {"name": "penable", "direction": "input", "protocol": "APB"},
    {"name": "tx", "direction": "output", "protocol": "UART"},
    {"name": "rx", "direction": "input", "protocol": "UART"},
]


def test_build_ref_model_config_apb():
    """APB 设计 → 生成 ref_model 配置：端口映射 + 比对输出。"""
    cfg = build_ref_model_config("apb_uart", APB_INTERFACES, [])
    assert cfg is not None
    assert cfg["enabled"] is True
    assert cfg["module"] == "apb_uart_ref_model"
    assert cfg["golden"] == {"ip": "apb_slave", "version": "v1"}
    assert cfg["compare_outputs"] == ["prdata"]
    port_map = {m["ref_port"]: m["dut_port"] for m in cfg["port_map"]}
    assert port_map["clk"] == "pclk"
    assert port_map["rst_n"] == "preset_n"
    assert port_map["paddr"] == "paddr"
    assert port_map["prdata"] == "prdata"
    # dut_port 必须去位宽后缀（paddr[7:0] → paddr），否则 tb_top 端口连接非法 SV
    for m in cfg["port_map"]:
        assert "[" not in m["dut_port"], f"dut_port 不能带位宽后缀: {m['dut_port']}"


def test_build_ref_model_config_bus_suffix_stripped():
    """接口名带 [7:0] 后缀 → dut_port 解析后无后缀。"""
    ifaces = [{"name": "paddr[7:0]", "direction": "input", "protocol": "APB"},
              {"name": "pwdata[7:0]", "direction": "input", "protocol": "APB"},
              {"name": "prdata[7:0]", "direction": "output", "protocol": "APB"}]
    cfg = build_ref_model_config("apb_uart", ifaces, [])
    assert cfg is not None
    port_map = {m["ref_port"]: m["dut_port"] for m in cfg["port_map"]}
    assert port_map["paddr"] == "paddr"
    assert port_map["pwdata"] == "pwdata"
    assert port_map["prdata"] == "prdata"


def test_build_ref_model_config_uart_only():
    """UART-only 设计 → uart_tx 配置（无可比对输出，诚实）。"""
    cfg = build_ref_model_config("uart", [
        {"name": "clk", "direction": "input", "protocol": "Clock"},
        {"name": "rst_n", "direction": "input", "protocol": "Reset"},
        {"name": "tx", "direction": "output", "protocol": "UART"},
    ], [])
    assert cfg is not None
    assert cfg["golden"]["ip"] == "uart_tx"
    assert cfg["compare_outputs"] == []


def _render_tb_top(bench: dict, agents: list) -> str:
    """用 bench dict 渲染 tb_top.sv.j2（模拟 gen_uvm 的 JinjaRenderer）。"""
    tpl_path = (Path(__file__).parent.parent / "src" / "tools" / "uvm_tools"
                / "tool_uvm" / "templates" / "bench_templates" / "tb_top.sv.j2")
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(tpl_path.parent)))
    return env.get_template(tpl_path.name).render(bench=bench, agents=agents)


def _minimal_bench(ref_model: dict) -> dict:
    return {
        "name": "apb_uart_bench",
        "env_name": "apb_uart_env",
        "timeout": "10ms",
        "clk_rst": {
            "clocks": [{"name": "pclk", "period": "10ns", "init": 0}],
            "resets": [{"name": "preset_n", "init": 0, "release_delay": 10}],
        },
        "wire_decls": [{"name": "paddr", "width": 8}, {"name": "prdata", "width": 8}],
        "assignments": [],
        "dut": {"module": "apb_uart", "instance": "u_apb_uart",
                "parameters": [], "ports": [{"name": "paddr", "connection": "paddr"}]},
        "uvm_config": {"verbosity": ""},
        "wave_dump": {"enabled": False},
        "simulation": {"max_runtime": None, "stop_on_fatal": None},
        "ref_model": ref_model,
    }


def test_tb_top_renders_ref_model_compare():
    """黄金命中 → tb_top 渲染 u_ref_model 实例化 + 逐拍比对块。"""
    cfg = build_ref_model_config("apb_uart", APB_INTERFACES, [])
    assert cfg is not None
    sv = _render_tb_top(_minimal_bench(cfg), agents=[])
    assert "apb_uart_ref_model u_ref_model" in sv
    assert ".clk(pclk)" in sv
    assert ".rst_n(preset_n)" in sv
    assert "u_ref_model.prdata" in sv
    assert 'mismatch prdata: expected=0x%0h actual=0x%0h' in sv
    # 触发时钟是 bench 的实际时钟（pclk），不是硬编码 clk
    assert "@(posedge pclk)" in sv


def test_tb_top_no_ref_model_when_not_matched():
    """黄金未命中 → 模板不渲染 ref_model 块（诚实：不假装比对）。"""
    sv = _render_tb_top(_minimal_bench({"enabled": False}), agents=[])
    assert "u_ref_model" not in sv
    assert "REF_CMP" not in sv
