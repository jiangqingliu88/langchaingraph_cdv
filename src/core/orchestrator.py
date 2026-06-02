"""
编排器 - 使用中介者模式 + 管道模式
"""
from typing import Dict, List, Any, Optional
import asyncio
from datetime import datetime
import structlog
from pydantic import BaseModel, Field

from src.core.base import (
    BaseAgent, AgentResult, AgentStatus, AgentMessage,
    SequentialStrategy, ParallelStrategy, ConditionalStrategy,
    Handler, ValidationHandler, EnrichmentHandler
)
from src.core.registry import AgentRegistry

logger = structlog.get_logger()

class WorkflowPhase(BaseModel):
    """工作流阶段"""
    name: str
    agent_role: str
    input_mapper: Optional[str] = None
    condition: Optional[str] = None
    parallel: bool = False
    parallel_agents: List[str] = Field(default_factory=list)
    retry_count: int = 0
    timeout: int = 300

class VerificationWorkflow(BaseModel):
    """验证工作流定义"""
    name: str
    description: str
    phases: List[WorkflowPhase]
    created_at: datetime = Field(default_factory=datetime.now)

class VerificationOrchestrator:
    """
    验证编排器
    中介者模式 - 协调所有Agent的交互
    """
    
    def __init__(self, registry: AgentRegistry):
        self.registry = registry
        self.workflows: Dict[str, VerificationWorkflow] = {}
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        
        # 责任链
        self._setup_chain()
        
        logger.info("编排器初始化完成")
    
    def _setup_chain(self):
        """设置责任链"""
        validation = ValidationHandler()
        enrichment = EnrichmentHandler()
        validation.set_next(enrichment)
        self.request_chain = validation
    
    def register_workflow(self, workflow: VerificationWorkflow):
        """注册工作流"""
        self.workflows[workflow.name] = workflow
        logger.info(f"工作流已注册", name=workflow.name)
    
    async def execute_workflow(
        self,
        workflow_name: str,
        initial_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行工作流
        使用管道模式串联各个阶段
        """
        workflow = self.workflows.get(workflow_name)
        if not workflow:
            raise ValueError(f"工作流不存在: {workflow_name}")
        
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.active_sessions[session_id] = {
            "workflow": workflow_name,
            "started_at": datetime.now(),
            "current_phase": None,
            "results": {}
        }
        
        logger.info(f"开始执行工作流", session=session_id, workflow=workflow_name)
        
        current_input = initial_input
        phase_results = {}
        
        for phase in workflow.phases:
            logger.info(f"执行阶段", phase=phase.name, agent=phase.agent_role)
            self.active_sessions[session_id]["current_phase"] = phase.name
            
            try:
                # 处理输入
                processed_input = await self.request_chain.handle({
                    "input": current_input.get("output", str(current_input)),
                    "phase": phase.name
                })
                
                if phase.parallel:
                    # 并行执行
                    results = await self._execute_parallel(
                        phase.parallel_agents,
                        processed_input
                    )
                    phase_results[phase.name] = results
                else:
                    # 顺序执行
                    result = await self._execute_single(
                        phase.agent_role,
                        processed_input
                    )
                    phase_results[phase.name] = result
                    
                    if result.success:
                        current_input = {"output": str(result.data)}
                    else:
                        logger.error(f"阶段执行失败", phase=phase.name, error=result.error)
                        if phase.retry_count > 0:
                            # 重试逻辑
                            for i in range(phase.retry_count):
                                logger.info(f"重试阶段", phase=phase.name, attempt=i+1)
                                result = await self._execute_single(
                                    phase.agent_role,
                                    processed_input
                                )
                                if result.success:
                                    break
                        
                        if not result.success:
                            break
                
            except Exception as e:
                logger.error(f"阶段异常", phase=phase.name, error=str(e))
                phase_results[phase.name] = AgentResult(
                    success=False,
                    error=str(e)
                )
                break
        
        self.active_sessions[session_id]["completed_at"] = datetime.now()
        self.active_sessions[session_id]["results"] = phase_results
        
        return {
            "session_id": session_id,
            "workflow": workflow_name,
            "success": all(
                r.success if isinstance(r, AgentResult) 
                else all(rr.success for rr in r)
                for r in phase_results.values()
            ),
            "phase_results": phase_results
        }
    
    async def _execute_single(
        self,
        agent_role: str,
        input_data: Dict[str, Any]
    ) -> AgentResult:
        """执行单个Agent"""
        agent = self.registry.get_agent_instance(agent_role)
        if not agent:
            return AgentResult(
                success=False,
                error=f"Agent未找到: {agent_role}"
            )
        
        return await agent.execute_task(input_data)
    
    async def _execute_parallel(
        self,
        agent_roles: List[str],
        input_data: Dict[str, Any]
    ) -> List[AgentResult]:
        """并行执行多个Agent"""
        tasks = []
        for role in agent_roles:
            agent = self.registry.get_agent_instance(role)
            if agent:
                tasks.append(agent.execute_task(input_data))
            else:
                tasks.append(asyncio.ensure_future(
                    asyncio.sleep(0, result=AgentResult(
                        success=False,
                        error=f"Agent未找到: {role}"
                    ))
                ))
        
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """获取会话状态"""
        return self.active_sessions.get(session_id, {})
    
    def cancel_session(self, session_id: str):
        """取消会话"""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
            logger.info(f"会话已取消", session=session_id)