"""
Agent注册中心 - 使用注册表模式
"""
from typing import Dict, Type, Optional, List
from src.core.base import BaseExecutor
import structlog

logger = structlog.get_logger()

class ExecutorRegistry:
    """
    Agent注册中心
    Singleton模式 + 注册表模式
    """
    
    _instance: Optional["ExecutorRegistry"] = None
    _agents: Dict[str, Type[BaseExecutor]] = {}
    _instances: Dict[str, BaseExecutor] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "ExecutorRegistry":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register(self, role: str, agent_class: Type[BaseExecutor]):
        """注册Agent类"""
        if role in self._agents:
            logger.warning(f"Agent已存在，将被覆盖", role=role)
        
        self._agents[role] = agent_class
        logger.info(f"Agent已注册", role=role)
    
    def unregister(self, role: str):
        """取消注册"""
        if role in self._agents:
            del self._agents[role]
            logger.info(f"Agent已取消注册", role=role)
    
    def get_agent_class(self, role: str) -> Optional[Type[BaseExecutor]]:
        """获取Agent类"""
        return self._agents.get(role)
    
    def get_agent_instance(self, role: str) -> Optional[BaseExecutor]:
        """获取Agent实例"""
        return self._instances.get(role)
    
    def set_agent_instance(self, role: str, instance: BaseExecutor):
        """设置Agent实例"""
        self._instances[role] = instance
    
    def list_agents(self) -> List[str]:
        """列出所有注册的Agent"""
        return list(self._agents.keys())
    
    def get_all_instances(self) -> Dict[str, BaseExecutor]:
        """获取所有实例"""
        return self._instances

# 装饰器简化注册
def register_executor(role: str):
    """Agent注册装饰器"""
    def decorator(agent_class: Type[BaseExecutor]):
        ExecutorRegistry.get_instance().register(role, agent_class)
        return agent_class
    return decorator