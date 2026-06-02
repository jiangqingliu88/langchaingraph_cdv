"""
管道模式实现 - 数据处理管道
"""
from typing import List, Callable, Any, Optional, TypeVar, Generic
from dataclasses import dataclass
import asyncio
import structlog

logger = structlog.get_logger()

T = TypeVar('T')

@dataclass
class PipelineContext:
    """管道上下文"""
    data: Any
    metadata: dict = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

class PipelineStage:
    """管道阶段"""
    
    def __init__(
        self,
        name: str,
        processor: Callable,
        validator: Optional[Callable] = None,
        error_handler: Optional[Callable] = None
    ):
        self.name = name
        self.processor = processor
        self.validator = validator
        self.error_handler = error_handler
    
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """执行管道阶段"""
        try:
            logger.debug(f"执行管道阶段", stage=self.name)
            
            # 验证输入
            if self.validator:
                if not self.validator(context.data):
                    raise ValueError(f"输入验证失败: {self.name}")
            
            # 处理
            result = await self.processor(context)
            
            # 更新上下文
            if isinstance(result, PipelineContext):
                context = result
            else:
                context.data = result
            
            return context
            
        except Exception as e:
            logger.error(f"管道阶段失败", stage=self.name, error=str(e))
            
            if self.error_handler:
                return await self.error_handler(context, e)
            
            raise

class Pipeline:
    """
    管道 - 组合多个处理阶段
    """
    
    def __init__(self, name: str):
        self.name = name
        self.stages: List[PipelineStage] = []
        self._observers: List[Callable] = []
    
    def add_stage(self, stage: PipelineStage) -> 'Pipeline':
        """添加阶段"""
        self.stages.append(stage)
        return self
    
    def add_observer(self, observer: Callable):
        """添加观察者"""
        self._observers.append(observer)
    
    async def execute(self, initial_data: Any) -> PipelineContext:
        """执行管道"""
        context = PipelineContext(data=initial_data)
        
        for stage in self.stages:
            # 通知观察者
            for observer in self._observers:
                try:
                    await observer(stage.name, "start", context)
                except Exception:
                    pass
            
            context = await stage.execute(context)
            
            # 通知观察者
            for observer in self._observers:
                try:
                    await observer(stage.name, "complete", context)
                except Exception:
                    pass
        
        return context

class VerificationPipeline(Pipeline):
    """验证专用管道"""
    
    @classmethod
    def create_full_verification_pipeline(cls, orchestrator) -> 'VerificationPipeline':
        """创建完整验证管道"""
        pipeline = cls("full_verification")
        
        # 阶段1: 规格分析
        pipeline.add_stage(PipelineStage(
            name="spec_analysis",
            processor=lambda ctx: asyncio.ensure_future(
                orchestrator.registry.get_agent_instance("spec_and_test_planner")
                .execute_task({"input": ctx.data})
            )
        ))
        
        # 阶段2: 架构设计
        pipeline.add_stage(PipelineStage(
            name="architecture",
            processor=lambda ctx: asyncio.ensure_future(
                orchestrator.registry.get_agent_instance("verification_architect")
                .execute_task({"input": str(ctx.data)})
            )
        ))
        
        return pipeline