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
