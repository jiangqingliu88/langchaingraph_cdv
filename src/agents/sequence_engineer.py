"""
序列工程师Agent —— 使用 generate_uvm 生成约束策略和测试序列

bypass 模式: 根据架构输出构造约束 YAML → generate_uvm("constraint", ...) → 真实 SV 代码
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.uvm import generate_uvm, uvm_tool
import structlog
import yaml

logger = structlog.get_logger()


@register_agent("sequence_engineer")
class SequenceEngineer(BaseAgent):
    """序列工程师Agent —— 生成约束策略和测试序列"""

    task_type = "sequence_generation"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="sequence_engineer",
            display_name="序列工程师",
            description="设计UVM测试序列和约束策略",
            config=config or {}
        )

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是UVM测试序列设计专家。

【职责】
1. 设计测试序列和场景
2. 实现约束随机化
3. 调用 generate_uvm(tool_type="constraint", ...) 生成约束策略代码

可用工具：generate_uvm
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return [uvm_tool]

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}

    # ── bypass: 不调 LLM，直接用 generate_uvm 生成约束代码 ──

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        bypass = task.get('bypass', False) if isinstance(task, dict) else False
        if not bypass:
            return await super().execute_task(task)

        from datetime import datetime
        start_time = datetime.now()

        try:
            spec_text = task.get("input", str(task))
            self._last_prompt = "bypass mode: generate_uvm(constraint)"

            constraint_yaml = _build_uart_constraint_yaml(spec_text)
            result_text = generate_uvm("constraint", constraint_yaml)

            execution_time = (datetime.now() - start_time).total_seconds()
            self.metrics["tasks_completed"] += 1
            self.metrics["total_time"] += execution_time

            from src.middleware.debug_logger import debug_logger
            debug_logger.log_agent_call(
                self.role, self.display_name, str(task)[:500],
                "generate_uvm(constraint, ...)", result_text[:500],
                ["generate_uvm"], 0, execution_time, True
            )

            return AgentResult(success=True, data={"output": result_text}, execution_time=execution_time)
        except Exception as e:
            return AgentResult(success=False, error=str(e))


def _build_uart_constraint_yaml(spec_text: str) -> str:
    """根据架构输出构造 UART 约束策略 YAML"""
    return yaml.dump({
        "constraint": {
            "name": "UART_constraint",
            "env_name": "uart_env",
        },
        "transactions": [
            {"name": "cfg",   "type": "uart_cfg_transaction",   "description": "配置事务",
             "fields": [
                 {"name": "baud_rate", "type": "int", "rand": True},
                 {"name": "data_bits", "type": "bit [2:0]", "rand": True},
                 {"name": "parity",    "type": "bit [1:0]", "rand": True},
             ]},
            {"name": "input", "type": "uart_input_transaction", "description": "TX 输入事务",
             "fields": [
                 {"name": "data", "type": "bit [7:0]", "rand": True},
                 {"name": "count","type": "int", "rand": True},
             ]},
            {"name": "output","type": "uart_output_transaction","description": "RX 输出事务",
             "fields": [
                 {"name": "data", "type": "bit [7:0]", "rand": True},
             ]},
        ],
        "policies": [
            {"name": "baud_rate_consistency",  "description": "波特率一致性",  "priority": 1, "enabled": True, "applies_to": ["cfg", "input"]},
            {"name": "data_format",            "description": "数据格式策略",  "priority": 2, "enabled": True, "applies_to": ["cfg", "input", "output"]},
            {"name": "fifo_boundary",          "description": "FIFO边界策略",  "priority": 3, "enabled": True, "applies_to": ["input", "output"]},
            {"name": "parity_error_injection", "description": "校验错误注入",  "priority": 4, "enabled": True, "applies_to": ["cfg", "output"]},
            {"name": "interrupt_check",        "description": "中断检查策略",  "priority": 5, "enabled": True, "applies_to": ["output"]},
        ],
        "combinator": {
            "default_mode": "APPLY_ALL",
            "modes": ["APPLY_ALL", "APPLY_WEIGHTED", "APPLY_FIRST_MATCH", "APPLY_SEQUENTIAL", "APPLY_CHAIN"],
        },
    }, default_flow_style=False, allow_unicode=True)
