"""Agent tests — 当前 7 Agent（design/model/verify/ops/coverage/debug/audit）

说明：旧测试引用已删除的 11 Agent 结构（spec/asserts/cover/regress/qa/report），
重构后七 Agent 按领域聚合。本文件只测真实存在的 Agent 契约。
"""
import pytest

from src.layers.l2_orchestration.agents.registry import AgentRegistry
from src.agents.design import DesignAgent
from src.agents.model import ModelAgent
from src.agents.verify import VerifyAgent
from src.agents.ops import OpsAgent
from src.agents.coverage import CoverageAgent
from src.agents.debug import DebugAgent
from src.agents.audit import AuditAgent

CURRENT_AGENTS = [
    ("design", DesignAgent),
    ("model", ModelAgent),
    ("verify", VerifyAgent),
    ("ops", OpsAgent),
    ("coverage", CoverageAgent),
    ("debug", DebugAgent),
    ("audit", AuditAgent),
]


def test_registry_has_seven_agents():
    """7 个领域 Agent 全部注册进注册中心（@register_agent 装饰器生效）。"""
    registry = AgentRegistry.get_instance()
    for role, _cls in CURRENT_AGENTS:
        assert role in registry.list_agents(), f"Agent '{role}' 未注册"
        assert registry.get_agent_class(role) is not None


@pytest.mark.asyncio
async def test_agent_initialize():
    """每个 Agent 可初始化，状态回到 IDLE。"""
    for role, cls in CURRENT_AGENTS:
        agent = cls()
        await agent.initialize()
        assert agent.status.value == "idle", f"{role} 初始化后状态异常"


@pytest.mark.asyncio
async def test_debug_agent_no_evidence_fails_loudly(tmp_path):
    """失败响亮：无 EDA / 无日志时 debug 不得给 95 分假通过。

    这是审计修复的回归测试——历史 bug 是"无日志 = No errors found = 95 分"。
    现在：不存在输出目录 → 无任何诊断证据 → success=False 且 score=0。
    """
    agent = DebugAgent()
    await agent.initialize()
    result = await agent.execute_task({
        "input": "",
        "output_dir": str(tmp_path / "nonexistent_run"),
    })
    assert result.success is False
    assert result.data["score"] == 0
    status = result.data["debug"]["status"]
    assert status in ("EDA_MISSING", "NO_EVIDENCE")


# ═══════════════════════════════════════════════════════
# model agent：SV 参考模型真实语义（禁止 a+b 模板）
# ═══════════════════════════════════════════════════════

def test_model_sv_render_real_registers():
    """有 spec.registers → SV 模型含真实寄存器语义，placeholder=False。"""
    from src.agents.model.main import _render_sv
    regs = [
        {"offset": "0x00", "name": "CTRL", "width": 8, "access": "RW", "description": "控制字"},
        {"offset": "0x04", "name": "STATUS", "width": 8, "access": "RO", "description": "状态字"},
    ]
    interfaces = [
        {"name": "pclk", "data_width": 1, "direction": "INPUT", "protocol": "Clock"},
        {"name": "preset_n", "data_width": 1, "direction": "INPUT", "protocol": "Reset"},
        {"name": "paddr[7:0]", "data_width": 8, "direction": "INPUT", "protocol": "APB"},
        {"name": "pwdata[7:0]", "data_width": 8, "direction": "INPUT", "protocol": "APB"},
        {"name": "prdata[7:0]", "data_width": 8, "direction": "OUTPUT", "protocol": "APB"},
    ]
    r = _render_sv("apb_uart", [], regs, interfaces)
    assert r["placeholder"] is False
    code = r["source_code"]
    # 端口来自 spec 接口（不是 ALU 的 opcode/operand_a）
    assert "opcode" not in code
    assert "paddr" in code and "prdata" in code
    # 真实寄存器语义
    assert "reg_CTRL" in code
    assert "reg_STATUS" in code
    assert "0x00: reg_CTRL = pwdata;" in code


def test_model_sv_render_placeholder_without_registers():
    """无 spec.registers → 占位模型（placeholder=True），audit 门禁据此拒绝。"""
    from src.agents.model.main import _render_sv
    interfaces = [
        {"name": "clk", "data_width": 1, "direction": "INPUT", "protocol": "Clock"},
        {"name": "rst_n", "data_width": 1, "direction": "INPUT", "protocol": "Reset"},
        {"name": "tx", "data_width": 1, "direction": "OUTPUT", "protocol": "UART"},
    ]
    r = _render_sv("uart", [], [], interfaces)
    assert r["placeholder"] is True
    # 端口仍然对齐 spec 接口（结构真实），但无功能语义
    assert "tx" in r["source_code"]
    assert "占位参考模型" in r["source_code"]


@pytest.mark.asyncio
async def test_model_agent_placeholder_flag_in_result(tmp_path):
    """model agent 结果带 placeholder 标记（audit 门禁 model_real 的数据源）。"""
    agent = ModelAgent()
    await agent.initialize()
    result = await agent.execute_task({
        "ctx": {"design_arch": {"module_name": "apb_uart", "interfaces": [
            {"name": "clk", "data_width": 1, "direction": "INPUT", "protocol": "Clock"},
        ], "registers": [], "function_hier": {"children": [{"name": "tx"}]}}},
        "input": "",
        "output_dir": str(tmp_path),
        "params": {"model_type": "systemverilog"},
    })
    assert result.success is True
    assert result.data["model"]["placeholder"] is True
    assert result.data["model"]["spec_interfaces"] == 1


# ═══════════════════════════════════════════════════════
# 黄金模型库：APB 设计命中 apb_slave（真实模型，非占位）
# ═══════════════════════════════════════════════════════

APB_SPEC_ARCH = {
    "module_name": "apb_uart",
    "interfaces": [
        {"name": "pclk", "data_width": 1, "direction": "INPUT", "protocol": "Clock"},
        {"name": "preset_n", "data_width": 1, "direction": "INPUT", "protocol": "Reset"},
        {"name": "paddr[7:0]", "data_width": 8, "direction": "INPUT", "protocol": "APB"},
        {"name": "pwdata[7:0]", "data_width": 8, "direction": "INPUT", "protocol": "APB"},
        {"name": "prdata[7:0]", "data_width": 8, "direction": "OUTPUT", "protocol": "APB"},
        {"name": "pwrite", "data_width": 1, "direction": "INPUT", "protocol": "APB"},
        {"name": "psel", "data_width": 1, "direction": "INPUT", "protocol": "APB"},
        {"name": "penable", "data_width": 1, "direction": "INPUT", "protocol": "APB"},
        {"name": "tx", "data_width": 1, "direction": "OUTPUT", "protocol": "UART"},
    ],
    "registers": [],
    "function_hier": {"children": [{"name": "uart_tx"}, {"name": "uart_rx"}]},
}


def test_golden_library_match_apb():
    """APB 接口 → 命中 apb_slave 黄金模型（带参数化）。"""
    from src.tools.lib.golden_library import match_golden
    hit = match_golden(APB_SPEC_ARCH)
    assert hit is not None
    assert hit["ip"] == "apb_slave"
    assert hit["version"] == "v1"
    assert hit["params"]["DATA_W"] == 8
    assert hit["params"]["NREGS"] >= 1


def test_golden_library_uart_only_matches_tx():
    """UART-only 设计（无 APB）→ 命中 uart_tx 黄金模型（不再是占位）。"""
    from src.tools.lib.golden_library import match_golden
    arch = {"module_name": "uart", "interfaces": [
        {"name": "clk", "data_width": 1, "direction": "INPUT", "protocol": "Clock"},
        {"name": "tx", "data_width": 1, "direction": "OUTPUT", "protocol": "UART"},
        {"name": "rx", "data_width": 1, "direction": "INPUT", "protocol": "UART"},
    ], "registers": [], "function_hier": {"children": []}}
    assert match_golden(arch) is not None


def test_golden_library_match_uart_tx():
    """UART TX 信号 → 命中 uart_tx 黄金模型。"""
    from src.tools.lib.golden_library import match_golden
    arch = {"module_name": "uart", "interfaces": [
        {"name": "clk", "data_width": 1, "direction": "INPUT", "protocol": "Clock"},
        {"name": "tx", "data_width": 1, "direction": "OUTPUT", "protocol": "UART"},
        {"name": "rx", "data_width": 1, "direction": "INPUT", "protocol": "UART"},
    ], "registers": [], "function_hier": {"children": []}}
    hit = match_golden(arch)
    assert hit["ip"] == "uart_tx"
    assert hit["version"] == "v1"


def test_golden_library_uart_models_are_verifiable():
    """uart_tx/uart_rx 黄金模型文件存在且 manifest 结构完整（待 EDA 验证盖章）。"""
    from src.tools.lib.golden_library import load_golden, verify_manifest
    for ip in ("uart_tx", "uart_rx", "fifo16", "irq_gen"):
        sv = load_golden(ip, "v1")
        assert "module" in sv and "endmodule" in sv, f"{ip} 模型不完整"
        m = verify_manifest(ip, "v1")
        assert m.get("ip") == ip
        assert m.get("verified") is False  # 未验证前必须 verified=false（禁止入库）


def test_golden_library_match_fifo_and_irq():
    """FIFO/中断信号 → 命中 fifo16/irq_gen 黄金模型。"""
    from src.tools.lib.golden_library import match_golden
    fifo_arch = {"module_name": "fifo", "interfaces": [
        {"name": "clk", "data_width": 1, "direction": "INPUT", "protocol": "Clock"},
        {"name": "wdata", "data_width": 8, "direction": "INPUT", "protocol": "generic"},
        {"name": "rdata", "data_width": 8, "direction": "OUTPUT", "protocol": "generic"},
    ], "registers": [], "function_hier": {"children": []}}
    assert match_golden(fifo_arch)["ip"] == "fifo16"
    irq_arch = {"module_name": "irq", "interfaces": [
        {"name": "clk", "data_width": 1, "direction": "INPUT", "protocol": "Clock"},
        {"name": "irq", "data_width": 1, "direction": "OUTPUT", "protocol": "Intr"},
    ], "registers": [], "function_hier": {"children": []}}
    assert match_golden(irq_arch)["ip"] == "irq_gen"


def test_golden_model_parameterize_module_name():
    """黄金模型参数化：模块名 → {module}_ref_model，parameter 默认值更新为 spec 推导值。"""
    from src.tools.lib.golden_library import parameterize
    sv = ("module apb_slave_golden #(parameter int NREGS = 16, parameter int ADDR_W = 8, "
          "parameter int DATA_W = 8) (input logic clk); endmodule")
    out = parameterize(sv, "apb_uart", {"NREGS": 256, "ADDR_W": 8, "DATA_W": 8})
    assert "module apb_uart_ref_model" in out
    assert "parameter int NREGS = 256" in out
    assert "parameter int ADDR_W = 8" in out


@pytest.mark.asyncio
async def test_model_agent_golden_hit(tmp_path):
    """APB 设计 → model agent 命中黄金模型：placeholder=False + golden_ref 可追溯。"""
    agent = ModelAgent()
    await agent.initialize()
    result = await agent.execute_task({
        "ctx": {"design_arch": APB_SPEC_ARCH},
        "input": "",
        "output_dir": str(tmp_path),
        "params": {"model_type": "systemverilog"},
    })
    assert result.success is True
    m = result.data["model"]
    assert m["placeholder"] is False
    assert m["golden_ref"] is not None
    assert m["golden_ref"]["ip"] == "apb_slave"
    assert m["golden_ref"]["sha256"], "golden_ref 必须带 sha256（可追溯）"
    # 落盘的 SV 是黄金模型（含 APB 读写语义），不是 a+b 模板
    from pathlib import Path
    sv_text = Path(m["files"][0]).read_text(encoding="utf-8")
    assert "regs[paddr]" in sv_text
    assert "apb_slave_golden" not in sv_text  # 模块名已参数化为 {module}_ref_model
