"""
规格与测试规划Agent - 使用LLM工厂
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.spec_tools import SpecAnalysisTools
import structlog
import json

logger = structlog.get_logger()

import re


class SpecAndTestPlanner(BaseAgent):
    """规格分析与测试规划Agent"""
    
    # 设置任务类型，LLM工厂会自动选择最优模型
    task_type = "spec_analysis"
    consumes = []
    produces = "spec"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="spec_and_test_planner",
            display_name="规格与测试规划师",
            description="分析设计规格文档，生成验证测试计划",
            config=config or {}
        )
        self.spec_tools = SpecAnalysisTools()
        self.min_score = 60   # must have features/interfaces/registers
        self.max_retries = 2

    async def _setup(self):
        """子类特定初始化"""
        logger.info(f"{self.display_name} 特定初始化完成")
    
    # ── schema: design_name 不能是占位符 ──
    _DESIGN_NAME_PLACEHOLDERS = {"dut", "dut_top", "dut_env", "top", "chip", "block", "design", "module", ""}

    async def _get_prompt_template(self):
        """获取Prompt模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是IC验证规格分析专家。分析输入的设计文档，严格只输出 JSON（不要 Markdown 代码块，不要解释文字）。

**约束 1 — design_name**：从文档中提取真实模块名，严禁 dut/DUT/top/chip/block/design/module。

**约束 2 — interfaces 必须列出每个端口信号**（不能留空！从文档的接口描述/端口列表中逐行提取）：
  "interfaces":[{{"name":"APB","type":"APB","clock":"pclk","signals":{{"pclk":{{"direction":"input","width":1}},"psel":{{"direction":"input","width":1}},"penable":{{"direction":"input","width":1}},"paddr":{{"direction":"input","width":8}},"pwdata":{{"direction":"input","width":8}},"prdata":{{"direction":"output","width":8}},"pwrite":{{"direction":"input","width":1}}}}}},...]

**约束 3 — verification_architecture.agents 必须列出 ports**（不能留空！与 interfaces.signals 保持一致）：
  "agents":[{{"name":"apb_agent","type":"UVM_ACTIVE","interface":"APB","clock":"pclk","reset":"preset_n","ports":[{{"name":"paddr","direction":"output","width":8}},{{"name":"pwdata","direction":"output","width":8}},{{"name":"prdata","direction":"input","width":8}},...],"transaction_vars":[{{"name":"addr","type":"bit [7:0]","iscompare":"True","isrand":"True"}}]}}]

完整 JSON 格式：{{"design_name":"...","version":"...","overview":"...","features":[...],"interfaces":[...],"registers":[...],"test_points":[...],"coverage_goals":{{}},"verification_architecture":{{"agents":[...],"scoreboards":[],"virtual_sequencer":{{"enabled":false}},"clock_reset":{{"clk":"...","rst_n":"..."}},"config_vars":[]}}}}"""),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
    
    async def _get_tools(self) -> List:
        """获取工具列表"""
        return self.spec_tools.get_tools()
    
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """Fallback only — base class calls executor directly."""
        return {"output": "Agent未初始化", "score": 0}

    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Extract structured spec data from agent executor output."""
        output_text = result.get("output", "") if isinstance(result, dict) else str(result)
        from src.core.base import _extract_json_from_llm
        import json as _json

        spec = _extract_json_from_llm(output_text)
        if not spec:
            steps = result.get("intermediate_steps", []) if isinstance(result, dict) else []
            for action, tool_output in steps:
                try:
                    data = _json.loads(str(tool_output))
                    if "design_name" in data:
                        spec = data
                        break
                except Exception:
                    pass

        if spec:
            result["spec"] = spec
            nf = len(spec.get("features", [])); ni = len(spec.get("interfaces", []))
            nt = sum(len(tp.get("tests", [])) for tp in spec.get("test_points", []))
            nr = len(spec.get("registers", []))
            base_score = min(10*nf + 5*ni + 3*nt + 5*nr, 90)

            # schema 校验：逐项检查
            errors = []
            dn = spec.get("design_name", "")
            if self._is_design_name_invalid(dn):
                errors.append(f"design_name '{dn}' 是占位符，必须提取真实模块名")

            # 检查 interfaces 是否有真实信号
            for i, iface in enumerate(spec.get("interfaces", []) or []):
                sigs = iface.get("signals", {})
                if not sigs or not isinstance(sigs, dict) or len(sigs) == 0:
                    errors.append(f"interfaces[{i}].signals 为空，必须列出每个端口信号")
                    break

            # 检查 agents 是否有真实 ports
            agents = spec.get("verification_architecture", {}).get("agents", [])
            for i, ag in enumerate(agents or []):
                ports = ag.get("ports", [])
                if not ports or len(ports) == 0:
                    errors.append(f"agents[{i}].ports 为空，必须列出端口（与 interfaces.signals 对应）")
                    break

            if errors:
                result["score"] = min(base_score, 45)  # 压低分数触发重试
                result["_validate_error"] = "; ".join(errors)
            else:
                result["score"] = base_score
        elif result.get("score", 0) >= 55:
            result["spec"] = {"design_name": "DUT", "status": "llm_output_unparseable",
                              "raw_output": str(output_text)[:500]}
            result["score"] = 40
        return result

    def _is_design_name_invalid(self, name: str) -> bool:
        return (not name or name.lower().strip() in self._DESIGN_NAME_PLACEHOLDERS)

    # ── schema 校验 ──

    def validate(self, result_data: dict) -> tuple[bool, str]:
        """验证 spec 质量：design_name + interfaces.signals + agents.ports 都不能是空的"""
        score = result_data.get("score", 0)
        if score < self.min_score:
            err = result_data.get("_validate_error", "")
            if err:
                return False, err
            return False, f"score {score} < min {self.min_score}"

        spec = result_data.get("spec", {})
        if not isinstance(spec, dict):
            return False, "spec 不是有效的 dict"

        dn = spec.get("design_name", "")
        if self._is_design_name_invalid(dn):
            return False, f"design_name '{dn}' 是无效占位符"

        # 至少有一个 interface 且有 signals
        ifaces = spec.get("interfaces", []) or []
        if not ifaces:
            return False, "interfaces 为空，必须从文档提取接口信号定义"
        for i, iface in enumerate(ifaces):
            sigs = iface.get("signals", {})
            if not sigs or not isinstance(sigs, dict) or len(sigs) == 0:
                return False, f"interfaces[{i}].signals 为空，必须列出所有端口信号"

        # agents 必须有 ports
        agents = spec.get("verification_architecture", {}).get("agents", []) or []
        if not agents:
            return False, "verification_architecture.agents 为空"
        for i, ag in enumerate(agents):
            ports = ag.get("ports", [])
            if not ports or len(ports) == 0:
                return False, f"agents[{i}].ports 为空，必须列出端口"

        return True, "OK"


    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        # Always use LLM
        return await super().execute_task(task)