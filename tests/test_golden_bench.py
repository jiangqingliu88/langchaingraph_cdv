"""黄金模型 bench 接入测试：ref_model 配置生成 + tb_top 模板渲染。

验证"参考模型比对真正发生"的接入链路（修复历史缺口：ref_model_enabled 默认 false）。
"""
from pathlib import Path

import jinja2

from src.tools.common.lib.golden_library import build_ref_model_config
from src.generation.uvm_tools.tool_uvm.constants import TEMPLATES_DIR
from src.generation.uvm_tools.tool_uvm.render.jinja_renderer import JinjaRenderer

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
    {"name": "irq", "direction": "output", "protocol": "Intr"},
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
    """用 bench dict 渲染 tb_top.sv.j2（复用 gen_uvm 的 JinjaRenderer）。

    必须复用 JinjaRenderer（而非裸 jinja2.Environment）：base_template.sv.j2 依赖
    其注册的 `now`/`trademark`/`copyright_year` globals，且 searchpath 为 templates 根目录
    （`{% include "base_templates/..." %}` 才能解析）。
    """
    renderer = JinjaRenderer(TEMPLATES_DIR)
    return renderer.render("bench_templates/tb_top.sv.j2", {"bench": bench, "agents": agents})


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


def test_tb_top_never_instantiates_a_ref_model():
    """tb_top **不复刻**参考模型 —— 比对不在这一层做。

    这里原先钉的是「tb_top 渲染 `u_ref_model` + 逐拍比对块」。那条路已经**退役**：
    harness 被删掉（commit `88a27ae4` "udpdate harness" 把 tb_top 改成直连式接口，
    顺带删了那段 ref_model 块），而 `bench` 的 schema 是 `additionalProperties:
    false`、`ref_model` 根本不在允许键里 —— 当初那次删除是对的。

    参考模型比对现在落在 **env 级**：`find_spec_yaml` 在门禁通过时往 env.yaml 写
    `analysis_components` + `scoreboards` + `tlm_connections`，由 `util_comp.sv.j2`
    渲染出的 predictor 镜像算出期望值喂给 scoreboard 的 expected 侧。

    这条测试钉的是**退役状态**（免得有人又往 tb_top 里塞一份），真正的比对链在
    `tests/test_ref_model_wiring.py`。
    """
    cfg = build_ref_model_config("apb_uart", APB_INTERFACES, [])
    assert cfg is not None, "黄金仍然命中（配置本身还在用，见 _ref_mirror_gate）"
    sv = _render_tb_top(_minimal_bench(cfg), agents=[])
    assert "u_ref_model" not in sv
    assert "REF_CMP" not in sv


# ═══════════════════════════════════════════════════════
# 复合参考模型（APB+UART + 寄存器表 → 多黄金 IP 接线）
# ═══════════════════════════════════════════════════════

REGS = [
    {"offset": "0x00", "name": "TX_DATA", "width": 8, "access": "RW", "description": "写触发发送"},
    {"offset": "0x01", "name": "RX_DATA", "width": 8, "access": "RO", "description": "接收数据"},
    {"offset": "0x02", "name": "STATUS", "width": 8, "access": "RO", "description": "状态字"},
    {"offset": "0x03", "name": "BAUD_DIV", "width": 16, "access": "RW", "description": "波特率分频"},
    {"offset": "0x04", "name": "IRQ_EN", "width": 8, "access": "RW", "description": "中断使能"},
]


def test_composite_ref_model_generated():
    """寄存器表含 tx_data/rx_data → 生成复合参考模型（多黄金 IP 实例化 + 接线）。"""
    from src.tools.common.lib.golden_library import build_composite_ref_model
    sv = build_composite_ref_model("apb_uart", APB_INTERFACES, REGS)
    assert sv is not None
    assert "module apb_uart_ref_model" in sv
    # 多黄金 IP 实例化
    assert "uart_tx_golden" in sv
    assert "uart_rx_golden" in sv
    # 寄存器语义 + 触发接线
    assert "reg_tx_data" in sv
    assert "reg_rx_data" in sv
    assert "reg_irq_en" in sv
    assert "0x00: reg_tx_data <= pwdata;" in sv
    assert "0x01: prdata = reg_rx_data;" in sv
    # UART 触发与回写
    assert "paddr == 0x00" in sv        # 写 TX_DATA 触发 uart_tx
    assert "rx_valid) reg_rx_data <= rx_data_w" in sv or "rx_valid) reg_rx_data <=" in sv
    # irq 门控（IRQ_EN 寄存器存在）
    assert "& reg_irq_en[0]" in sv
    # 无 a+b 模板痕迹
    assert "operand_a" not in sv


def test_composite_requires_tx_rx_registers():
    """寄存器表缺 tx/rx 数据寄存器 → 不生成复合（诚实：无法接线，回退单模型）。"""
    from src.tools.common.lib.golden_library import build_composite_ref_model
    partial = [{"offset": "0x00", "name": "CTRL", "width": 8, "access": "RW"}]
    assert build_composite_ref_model("dut", APB_INTERFACES, partial) is None
    assert build_composite_ref_model("dut", APB_INTERFACES, []) is None


def test_ref_model_config_composite():
    """bench 接入配置：复合模型 → golden=composite + 扩展比对输出（tx/irq）。"""
    cfg = build_ref_model_config("apb_uart", APB_INTERFACES, REGS)
    assert cfg is not None
    assert cfg["golden"]["ip"] == "composite"
    assert "uart_tx" in cfg["golden"]["parts"]
    assert "tx" in cfg["compare_outputs"]
    assert "irq" in cfg["compare_outputs"]
    ref_ports = {m["ref_port"] for m in cfg["port_map"]}
    assert {"tx", "rx", "irq"} <= ref_ports
