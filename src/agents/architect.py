"""
验证架构师Agent —— 使用 generate_uvm 生成 UVM 组件代码

bypass 模式: 根据输入规格构造 YAML → generate_uvm() → 真实 SV 代码
LLM 模式:   通过 LangChain Agent + generate_uvm 工具生成
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.uvm import generate_uvm
import structlog
import yaml
import json

logger = structlog.get_logger()


@register_agent("verification_architect")
class VerificationArchitect(BaseAgent):
    """验证架构师Agent —— 使用参数化 generate_uvm 工具"""

    task_type = "code_generation"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="verification_architect",
            display_name="验证架构师",
            description="设计UVM验证环境架构并生成所有组件代码",
            config=config or {}
        )

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是UVM验证环境架构设计专家。

【职责】
1. 设计UVM验证环境整体架构
2. 定义组件层次和接口
3. 调用 generate_uvm 工具生成所有UVM组件代码

【工具使用】
- generate_uvm(tool_type="agent", yaml_spec=...) → 生成 Agent 全套代码(Driver/Monitor/Sequencer/...)
- generate_uvm(tool_type="env", yaml_spec=...)   → 生成 Environment 全套代码
- generate_uvm(tool_type="bench", yaml_spec=...) → 生成 Testbench Top
- tool_type 可选: agent | env | bench | constraint | util

【代码生成规范】
- 遵循UVM 1.2标准
- 使用`uvm_component_utils宏注册
- 实现完整phase
- 正确的TLM端口声明和连接
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return [generate_uvm]

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}

    # ── bypass: 不调 LLM，生成代码 + 写入磁盘 + 准备编译 ──

    DEFAULT_OUTPUT_DIR = "generated/uart"

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        bypass = task.get('bypass', False) if isinstance(task, dict) else False
        if not bypass:
            return await super().execute_task(task)

        from datetime import datetime
        from pathlib import Path
        import json
        start_time = datetime.now()

        try:
            raw_input = task.get("input", str(task))
            output_dir = Path(task.get("output_dir", self.DEFAULT_OUTPUT_DIR))
            output_dir.mkdir(parents=True, exist_ok=True)
            self._last_prompt = "bypass mode: generate_uvm + write files"

            # 解析 spec_planner 输出的 JSON
            arch = _parse_architecture(raw_input)

            from src.tools.uvm.tool_uvm.gen_uvm import (
                UVMGenerator, JinjaRenderer, TEMPLATES_DIR,
                AgentModel, AgentCollection, EnvironmentModel,
                BenchModel, ConstraintModel,
            )

            renderer = JinjaRenderer(TEMPLATES_DIR)
            generator = UVMGenerator(renderer, output_dir)
            all_files = []

            # ── 生成 Agent SV 文件 ──
            for agent_spec in arch.get("agents", []):
                agent_yaml_str = _agent_spec_to_yaml(agent_spec, arch)
                yaml_path = output_dir / f"yaml_{agent_spec['name']}.yaml"
                yaml_path.write_text(agent_yaml_str, encoding='utf-8')
                paths = generator.run([yaml_path])
                all_files.extend(paths)

            # ── 生成 Environment ──
            env_yaml_str = _build_env_yaml(arch)
            env_yaml_path = output_dir / "yaml_env.yaml"
            env_yaml_path.write_text(env_yaml_str, encoding='utf-8')
            paths = generator.run([env_yaml_path])
            all_files.extend(paths)

            # ── 生成 Bench ──
            bench_yaml_str = _build_bench_yaml(arch)
            bench_yaml_path = output_dir / "yaml_bench.yaml"
            bench_yaml_path.write_text(bench_yaml_str, encoding='utf-8')
            paths = generator.run([bench_yaml_path])
            all_files.extend(paths)

            # ── 生成 filelist (绝对路径，QuestaSim 兼容) ──
            filelist_path = output_dir / "filelist.f"
            fl_context = {
                "dut_path": str(Path("src/tools/compilesim/dut/uart.v").resolve()),
                "base_pkg_dir": str(Path("src/tools/uvm/tool_uvm/base_pkg").resolve()),
                "agents": arch.get("agents", []),
                "agent_dir": str(output_dir.resolve() / "agents"),
                "env_dir": str(output_dir.resolve() / "env"),
                "bench_dir": str(output_dir.resolve() / "bench"),
                "environment": {"env_name": "uart_env"},
                "bench_name": "uart_bench",
            }
            filelist_content = renderer.render(
                "environment_templates/env_pkg_filelist.f.j2", fl_context
            )
            filelist_path.write_text(filelist_content, encoding='utf-8')

            # ── 汇总 ──
            summary = f"Generated {len(all_files)} files into {output_dir.resolve()}\n"
            summary += f"Filelist: {filelist_path}\n"
            summary += f"\nRun simulation:\n"
            summary += f"  cd {output_dir.resolve()}\n"
            summary += f"  python {Path('src/tools/compilesim/Verify_run.py').resolve()} -c {Path('src/tools/compilesim/regress_uart.yaml').resolve()} --tags smoke"

            execution_time = (datetime.now() - start_time).total_seconds()
            self.metrics["tasks_completed"] += 1
            self.metrics["total_time"] += execution_time

            from src.middleware.debug_logger import debug_logger
            debug_logger.log_agent_call(
                self.role, self.display_name, str(task)[:500],
                f"generate_uvm + write files", summary[:500],
                ["generate_uvm"], len(all_files), execution_time, True
            )

            return AgentResult(success=True,
                data={"output": summary, "files": [str(f) for f in all_files], "filelist": str(filelist_path)},
                execution_time=execution_time)
        except Exception as e:
            import traceback
            return AgentResult(success=False, error=f"{e}\n{traceback.format_exc()}")


def _parse_architecture(raw_input: str) -> dict:
    """从 spec_planner 输出或原始规格中提取 verification_architecture"""
    try:
        data = json.loads(raw_input)
        if "verification_architecture" in data:
            return data["verification_architecture"]
        # fallback: 用 design_name 构造默认架构
        return _default_uart_arch()
    except (json.JSONDecodeError, TypeError):
        return _default_uart_arch()


def _agent_spec_to_yaml(agent_spec: dict, arch: dict) -> str:
    """将单个 agent 规格转为 gen_uvm YAML"""
    ports = agent_spec.get("ports", [])
    tx_vars = agent_spec.get("transaction_vars", [])
    return yaml.dump({
        "interfaces": {
            "name": agent_spec["name"],
            "clock": agent_spec.get("clock", "clk"),
            "reset": agent_spec.get("reset", "rst_n"),
            "parameters": [
                {"name": "DATA_WIDTH", "type": "int", "value": "32"},
            ],
            "ports": ports,
            "transaction_vars": tx_vars,
            "transaction_constraints": [
                {"name": "valid_c", "value": "{ data inside {[0:255]}; }"},
            ],
            "config": {"is_active": agent_spec.get("type", "UVM_ACTIVE")},
        }
    }, default_flow_style=False, allow_unicode=True)


def _build_env_yaml(arch: dict) -> str:
    """从架构规格构造 Environment YAML"""
    agents = {}
    for a in arch.get("agents", []):
        agents[a["name"]] = {
            "interface": a.get("interface", f"{a['name']}_interface"),
            "clock": a.get("clock", "clk"),
            "reset": a.get("reset", "rst_n"),
        }
    cr = arch.get("clock_reset", {})
    return yaml.dump({
        "environment": {
            "name": "uart_env",
            "env_name": "uart_env",
            "clk_rst_vip": {"enabled": False},
            "agents": agents,
            "scoreboards": arch.get("scoreboards", []),
            "virtual_sequencer": arch.get("virtual_sequencer", {"enabled": False}),
            "config_vars": arch.get("config_vars", []),
            "tlm_connections": arch.get("tlm_connections", []),
        }
    }, default_flow_style=False, allow_unicode=True)


def _build_bench_yaml(arch: dict) -> str:
    """从架构规格构造 Bench YAML"""
    cr = arch.get("clock_reset", {})
    agents = {}
    for a in arch.get("agents", []):
        agents[a["name"]] = {
            "interface": a.get("interface", f"{a['name']}_interface"),
            "clock": a.get("clock", "clk"),
            "reset": a.get("reset", "rst_n"),
        }
    return yaml.dump({
        "bench": {
            "name": "uart_bench",
            "env_name": "uart_env",
            "timeout": "10ms",
            "clk_rst_vip": {"enabled": False},
            "agents": agents,
        }
    }, default_flow_style=False, allow_unicode=True)


def _default_uart_arch() -> dict:
    """fallback —— UART 默认架构"""
    return {
        "agents": [{
            "name": "UART_in", "type": "UVM_ACTIVE", "interface": "uart_if",
            "clock": "pclk", "reset": "presetn",
            "ports": [
                {"name": "pclk", "dir": "input", "width": 1},
                {"name": "presetn", "dir": "input", "width": 1},
                {"name": "tx", "dir": "output", "width": 1},
                {"name": "rx", "dir": "input", "width": 1},
            ],
            "transaction_vars": [
                {"name": "data", "type": "bit [7:0]", "iscompare": "True", "isrand": "True"},
            ],
        }],
        "clock_reset": {"interface": "clk_rst_if", "clocks": ["pclk"], "resets": ["presetn"]},
        "virtual_sequencer": {"enabled": False},
    }
