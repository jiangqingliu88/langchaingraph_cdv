"""verify_architect 单独测试 —— 不依赖 pipeline，直接通过 ctx 传入 YAML 架构数据"""
import asyncio, sys, os, yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.agents.verify_architect import VerificationArchitect

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "generated/verify_architect_test")

# ═══════════════════════════════════════════════════════════════
# ctx 中的 YAML 架构数据（模拟 spec_planner 输出）
# ── 全部通过 ctx 传递，不依赖任何硬编码 default ──
# ═══════════════════════════════════════════════════════════════

VERIFICATION_ARCHITECTURE = {
    "env_name": "uart_env",
    "agents": [
        {
            "name": "APB_agent",
            "type": "UVM_ACTIVE",
            "interface": "apb_if",
            "clock": "clk",
            "reset": "rst_n",
            "ports": [
                {"name": "clk",       "dir": "input",  "width": 1,  "desc": "system clock"},
                {"name": "rst_n",     "dir": "input",  "width": 1,  "desc": "async reset active low"},
                {"name": "paddr",     "dir": "output", "width": 8,  "desc": "APB address"},
                {"name": "psel",      "dir": "output", "width": 1,  "desc": "APB select"},
                {"name": "penable",   "dir": "output", "width": 1,  "desc": "APB enable"},
                {"name": "pwrite",    "dir": "output", "width": 1,  "desc": "APB write"},
                {"name": "pwdata",    "dir": "output", "width": 32, "desc": "APB write data"},
                {"name": "prdata",    "dir": "input",  "width": 32, "desc": "APB read data"},
                {"name": "pready",    "dir": "input",  "width": 1,  "desc": "APB ready"},
                {"name": "pslverr",   "dir": "input",  "width": 1,  "desc": "APB slave error"},
            ],
            "transaction_vars": [
                {"name": "paddr",   "type": "bit [7:0]",  "iscompare": "True", "isrand": "True"},
                {"name": "pwdata",  "type": "bit [31:0]", "iscompare": "True", "isrand": "True"},
                {"name": "pwrite",  "type": "bit",        "iscompare": "True", "isrand": "True"},
                {"name": "psel",    "type": "bit",        "iscompare": "False","isrand": "False"},
                {"name": "penable", "type": "bit",        "iscompare": "False","isrand": "False"},
            ],
            "transaction_constraints": [
                {"name": "valid_c", "value": "{ psel == 1; penable == 1; }"},
            ],
        },
        {
            "name": "UART_agent",
            "type": "UVM_ACTIVE",
            "interface": "uart_if",
            "clock": "clk",
            "reset": "rst_n",
            "ports": [
                {"name": "clk",       "dir": "input",  "width": 1,  "desc": "system clock"},
                {"name": "rst_n",     "dir": "input",  "width": 1,  "desc": "async reset active low"},
                {"name": "uart_tx",   "dir": "output", "width": 1,  "desc": "UART transmit"},
                {"name": "uart_rx",   "dir": "input",  "width": 1,  "desc": "UART receive"},
                {"name": "uart_cts",  "dir": "input",  "width": 1,  "desc": "clear to send (flow ctrl)"},
                {"name": "uart_rts",  "dir": "output", "width": 1,  "desc": "request to send (flow ctrl)"},
                {"name": "interrupt", "dir": "output", "width": 1,  "desc": "interrupt output"},
                {"name": "baud_div",  "dir": "input",  "width": 16, "desc": "baud rate divider"},
            ],
            "transaction_vars": [
                {"name": "uart_tx",  "type": "bit", "iscompare": "True", "isrand": "True"},
                {"name": "uart_rts", "type": "bit", "iscompare": "True", "isrand": "True"},
                {"name": "interrupt","type": "bit", "iscompare": "True", "isrand": "True"},
            ],
            "transaction_constraints": [],
        },
    ],
    "scoreboards": [
        {"name": "uart_scoreboard", "type": "register"},
    ],
    "virtual_sequencer": {"enabled": False},
    "clock_reset": {
        "interface": "clk_rst_if",
        "clocks": ["clk"],
        "resets": ["rst_n"],
    },
    "config_vars": [
        {"name": "BAUD_RATE", "type": "int", "value": "115200"},
        {"name": "CLK_FREQ",  "type": "int", "value": "100000000"},
    ],
}


async def main():
    print(f"[input] ctx 中传入 verification_architecture YAML 数据")
    print(f"        agents: {[a['name'] for a in VERIFICATION_ARCHITECTURE['agents']]}")
    print(f"        env_name: {VERIFICATION_ARCHITECTURE['env_name']}")
    print(f"[output] dir = {OUTPUT_DIR}")

    agent = VerificationArchitect()
    await agent.initialize()

    # ── 全部通过 ctx 传递，input 作为简要描述 ──
    result = await agent.execute_task({
        "input": "UART top-level module with APB slave + UART TX/RX",
        "output_dir": OUTPUT_DIR,
        "bypass": True,
        "ctx": {
            "spec": {
                "verification_architecture": VERIFICATION_ARCHITECTURE,
            },
        },
    })

    print(f"\n[result] success={result.success}")
    if result.error:
        print(f"[error] {result.error[:800]}")
    if result.data:
        out = str(result.data.get("output", ""))
        print(f"[data] output preview:\n{out[:800]}")
        print(f"[data] score={result.data.get('score', '?')}")
        env = result.data.get("env", {})
        if env:
            print(f"[data] env_name={env.get('env_name', '?')}")
            print(f"[data] agent_count={env.get('agent_count', '?')}")
            print(f"[data] output_dir={env.get('output_dir', '?')}")


if __name__ == "__main__":
    asyncio.run(main())
