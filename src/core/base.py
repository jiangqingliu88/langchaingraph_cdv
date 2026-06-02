"""
基础抽象类 - 更新使用LLM工厂
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Callable, TypeVar, Generic
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import asyncio
import json
from pydantic import BaseModel, Field
from langchain.agents import AgentExecutor
from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
import structlog

from src.core.llm_factory import LLMFactory
from config.settings import Settings

logger = structlog.get_logger()

# ==================== 基础数据模型 ====================

class AgentStatus(Enum):
    """Agent状态枚举"""
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    OFFLINE = "offline"

class AgentResult(BaseModel):
    """Agent执行结果"""
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    execution_time: float = 0.0
    tokens_used: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)



class AgentMessage(BaseModel):
    """Agent间通信消息"""
    id: str = Field(default_factory=lambda: f"msg_{datetime.now().timestamp()}")
    sender: str
    receiver: str
    content: Dict[str, Any] = Field(default_factory=dict)
    message_type: str = "task"
    timestamp: datetime = Field(default_factory=datetime.now)
    correlation_id: Optional[str] = None
    requires_response: bool = False

# ==================== 观察者模式 ====================

class AgentObserver(ABC):
    """Agent观察者接口"""
    
    @abstractmethod
    async def on_agent_start(self, agent_id: str, task: Dict[str, Any]):
        pass
    
    @abstractmethod
    async def on_agent_complete(self, agent_id: str, result: AgentResult):
        pass
    
    @abstractmethod
    async def on_agent_error(self, agent_id: str, error: Exception):
        pass

class AgentSubject:
    """被观察的Agent基类"""
    
    def __init__(self):
        self._observers: List[AgentObserver] = []
    
    def attach_observer(self, observer: AgentObserver):
        self._observers.append(observer)
    
    def detach_observer(self, observer: AgentObserver):
        self._observers.remove(observer)
    
    async def notify_start(self, agent_id: str, task: Dict[str, Any]):
        for observer in self._observers:
            await observer.on_agent_start(agent_id, task)
    
    async def notify_complete(self, agent_id: str, result: AgentResult):
        for observer in self._observers:
            await observer.on_agent_complete(agent_id, result)
    
    async def notify_error(self, agent_id: str, error: Exception):
        for observer in self._observers:
            await observer.on_agent_error(agent_id, error)

# ==================== 基础Agent类 ====================

class BaseAgent(ABC, AgentSubject):
    """
    基础Agent类
    
    使用模板方法模式定义Agent生命周期
    集成LLM工厂自动选择最优模型
    """
    
    # 子类需要定义的任务类型，用于LLM工厂选择模型
    task_type: str = "spec_analysis"
    
    def __init__(
        self,
        role: str,
        display_name: str,
        description: str,
        config: Optional[Dict[str, Any]] = None
    ):
        super().__init__()
        self.role = role
        self.display_name = display_name
        self.description = description
        self.config = config or {}
        self.status = AgentStatus.IDLE
        self.state: Dict[str, Any] = {}
        self.metrics: Dict[str, Any] = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "total_tokens": 0,
            "total_time": 0.0
        }
        
        # LLM和Executor
        self.llm: Optional[BaseChatModel] = None
        self._executor: Optional[AgentExecutor] = None
        self.tools: List[BaseTool] = []
        
        # 设置
        self.settings = Settings.get_instance()
        
        logger.info(f"Agent初始化", role=self.role, name=self.display_name)
    
    def _create_llm(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> BaseChatModel:
        """
        创建LLM实例
        
        使用LLM工厂根据任务类型自动选择最优模型
        """
        return LLMFactory.create_for_task(
            task_type=self.task_type,
            settings=self.settings
        )
    
    async def initialize(self):
        """
        初始化Agent

        模板方法 - 定义初始化流程
        1. 创建LLM (若 API Key 不可用则跳过，支持 bypass)
        2. 子类特定初始化
        3. 创建Agent Executor
        """
        logger.info(f"正在初始化Agent: {self.display_name}")

        # 1. 尝试创建LLM，失败则跳过（bypass 模式不需要）
        try:
            self.llm = self._create_llm()
        except (ValueError, Exception) as e:
            logger.warning(f"LLM创建失败，将使用 bypass 模式", error=str(e))
            self.llm = None

        # 2. 获取工具
        self.tools = await self._get_tools()

        # 3. 获取Prompt
        prompt = await self._get_prompt_template()

        # 4. 子类特定初始化
        await self._setup()

        # 5. 创建Agent Executor（仅当 LLM 可用时）
        if self.llm and self.tools and prompt:
            from langchain.agents import create_openai_tools_agent
            agent = create_openai_tools_agent(
                llm=self.llm,
                tools=self.tools,
                prompt=prompt
            )

            self._executor = AgentExecutor(
                agent=agent,
                tools=self.tools,
                verbose=self.settings.agent.verbose,
                max_iterations=self.settings.agent.max_iterations,
                handle_parsing_errors=True,
                return_intermediate_steps=False
            )

        self.status = AgentStatus.IDLE
        logger.info(f"Agent初始化完成: {self.display_name}")
    
    @abstractmethod
    async def _setup(self):
        """子类特定初始化"""
        pass
    
    @abstractmethod
    async def _get_prompt_template(self):
        """获取Prompt模板"""
        pass
    
    @abstractmethod
    async def _get_tools(self) -> List[BaseTool]:
        """获取工具列表"""
        pass
    
    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        bypass = task.get('bypass', False) if isinstance(task, dict) else False
        if bypass:
            result = AgentResult(success=True, data={"output": f"[{self.display_name}] bypass mode"})
            # 记录调试日志
            from src.middleware.debug_logger import debug_logger
            debug_logger.log_agent_call(self.role, self.display_name, str(task)[:500], "bypass", result.data.get("output", ""), [], 0, 0, True)
            return result
        start_time = datetime.now()
        self.status = AgentStatus.BUSY
        await self.notify_start(self.role, task)
        try:
            processed_input = await self._pre_process(task)
            if self._executor:
                result = await self._executor.ainvoke({"input": processed_input})
            else:
                result = await self._execute(processed_input)
            processed_result = await self._post_process(result)
            execution_time = (datetime.now() - start_time).total_seconds()
            self.metrics["tasks_completed"] += 1
            self.metrics["total_time"] += execution_time
            agent_result = AgentResult(success=True, data=processed_result, execution_time=execution_time)
            # 记录调试日志
            try:
                from src.middleware.debug_logger import debug_logger
                prompt_preview = str(getattr(self, '_last_prompt', ''))[:500]
                tools_names = [t.name for t in self.tools] if self.tools else []
                debug_logger.log_agent_call(self.role, self.display_name, str(task)[:500], prompt_preview, str(processed_result)[:500], tools_names, 0, execution_time, True)
            except:
                pass
            await self.notify_complete(self.role, agent_result)
            return agent_result
        except Exception as e:
            self.metrics["tasks_failed"] += 1
            error_result = AgentResult(success=False, error=str(e))
            await self.notify_error(self.role, e)
            return error_result
        finally:
            self.status = AgentStatus.IDLE

    async def _pre_process(self, task: Dict[str, Any]) -> str:
        """预处理任务输入"""
        return task.get("input", str(task))
    
    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """后处理执行结果"""
        return result
    
    @abstractmethod
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """直接执行（不使用Agent Executor时）"""
        pass
    
    def get_state(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "role": self.role,
            "status": self.status.value,
            "metrics": self.metrics.copy(),
            "state": self.state.copy()
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """获取性能指标"""
        return {
            "role": self.role,
            "display_name": self.display_name,
            "status": self.status.value,
            **self.metrics
        }

# ==================== 策略模式 ====================

class ExecutionStrategy(ABC):
    """执行策略抽象类"""
    @abstractmethod
    async def execute(self, tasks: list, executor) -> list:
        pass

class SequentialStrategy(ExecutionStrategy):
    """顺序执行策略"""
    async def execute(self, tasks: list, executor) -> list:
        results = []
        for task in tasks:
            result = await executor(task)
            results.append(result)
            if hasattr(result, 'success') and not result.success:
                break
        return results

class ParallelStrategy(ExecutionStrategy):
    """并行执行策略"""
    async def execute(self, tasks: list, executor) -> list:
        import asyncio
        coroutines = [executor(task) for task in tasks]
        return await asyncio.gather(*coroutines, return_exceptions=True)

class ConditionalStrategy(ExecutionStrategy):
    """条件执行策略"""
    def __init__(self, condition):
        self.condition = condition
    
    async def execute(self, tasks: list, executor) -> list:
        results = []
        for task in tasks:
            if self.condition(task):
                result = await executor(task)
                results.append(result)
        return results

# ==================== 命令模式 ====================

class Command(ABC):
    """命令抽象类"""
    @abstractmethod
    async def execute(self) -> AgentResult:
        pass
    
    @abstractmethod
    async def undo(self) -> AgentResult:
        pass

# ==================== 责任链模式 ====================

class Handler(ABC):
    """责任链处理器抽象类"""
    def __init__(self):
        self._next_handler = None
    
    def set_next(self, handler) -> 'Handler':
        self._next_handler = handler
        return handler
    
    @abstractmethod
    async def handle(self, request: dict) -> dict:
        if self._next_handler:
            return await self._next_handler.handle(request)
        return request

class ValidationHandler(Handler):
    """验证处理器"""
    async def handle(self, request: dict) -> dict:
        if not request.get("input"):
            raise ValueError("input cannot be empty")
        return await super().handle(request)

class EnrichmentHandler(Handler):
    """丰富处理器"""
    async def handle(self, request: dict) -> dict:
        from datetime import datetime
        request["timestamp"] = datetime.now().isoformat()
        request["agent_version"] = "1.0"
        return await super().handle(request)

# ==================== Agent消息 ====================

class AgentMessage(BaseModel):
    """Agent间通信消息"""
    id: str = Field(default_factory=lambda: f"msg_{datetime.now().timestamp()}")
    sender: str = ""
    receiver: str = ""
    content: Dict[str, Any] = Field(default_factory=dict)
    message_type: str = "task"
    timestamp: datetime = Field(default_factory=datetime.now)
    correlation_id: Optional[str] = None
    requires_response: bool = False
