"""
设计架构师 Agent —— 模块 Spec ->function_hier(代码风格) + 寄存器 + RTL hierarchy

Output: 函数模块声明 + 寄存器 map + RTL 例化层次 + signoff checklist
"""
from typing import Dict, List, Any
from datetime import datetime as dt
from pathlib import Path
import json, re

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent


@register_agent("design")
class DesignAgent(BaseAgent):
    """模块分解器 —— 将功能描述分解为模块层次、寄存器字段语义"""

    task_type = "code_generation"
    consumes = {"spec": ["features", "interfaces", "registers"]}  # 字段级
    produces = "design_arch"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="design", display_name="设计架构师",
            description="功能描述 → 模块层次分解 + 寄存器字段语义设计",
            config=config or {})
        self.min_score = 50

    async def _setup(self): pass
    async def _get_prompt_template(self):
        from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
        return ChatPromptTemplate.from_messages([
            ("system", """You are a digital design architect. Output ONLY a single JSON object, no other text.

REQUIRED OUTPUT FORMAT (copy this exact structure):
{{"module_name":"<name>","function_hier":{{"name":"<TOP>","children":[{{"name":"<sub>","children":[]}}]}},"registers":[{{"name":"<reg>","offset":"0x00","width":8,"access":"RW","reset":"0","desc":"","fields":[{{"bits":"[0]","name":"<field>","access":"RW","reset":"0"}}]}}],"signoff_checklist":[{{"item":"verify <x>","cat":"function","status":"pending"}}]}}

RULES:
- module_name: extract from spec (e.g. "ALU")
- function_hier: create leaf nodes for each operation (ADD/SUB/MUL/DIV/AND/OR/XOR/SLL etc.)
- registers: use the register table from the spec exactly
- signoff_checklist: one item per function + one per register
- NO markdown, NO code blocks, NO explanation. Raw JSON only.
"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
    async def _get_tools(self) -> List: return []
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}

    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract design_arch JSON from LLM output text."""
        output_text = result.get("output", "") if isinstance(result, dict) else str(result)
        from src.core.base import _extract_json_from_llm
        design = _extract_json_from_llm(output_text)
        if design:
            result["design_arch"] = design
            n_regs = len(design.get("registers", []))
            n_funcs = len(str(design.get("function_hier", "")))
            result["score"] = min(30 + 5*n_regs + min(n_funcs//100, 10), 90)
        elif result.get("score", 0) >= 55:
            result["design_arch"] = {"module_name": "DUT", "status": "llm_output_unparseable"}
        return result

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        # Always use LLM
        return await super().execute_task(task)
