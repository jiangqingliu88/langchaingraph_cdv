"""
Agent注册中心
"""
from typing import Dict, Type, Optional, List
import structlog

logger = structlog.get_logger()

class AgentRegistry:
    """Agent注册中心 - Singleton模式"""
    
    _instance: Optional["AgentRegistry"] = None
    _agents: Dict[str, Type] = {}
    _instances: Dict[str, object] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "AgentRegistry":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register(self, role: str, agent_class: Type):
        """注册Agent类"""
        self._agents[role] = agent_class
        logger.info(f"Agent已注册", role=role)
    
    def unregister(self, role: str):
        """取消注册"""
        if role in self._agents:
            del self._agents[role]
    
    def get_agent_class(self, role: str) -> Optional[Type]:
        """获取Agent类"""
        return self._agents.get(role)
    
    def get_agent_instance(self, role: str):
        """获取Agent实例"""
        return self._instances.get(role)
    
    def set_agent_instance(self, role: str, instance):
        """设置Agent实例"""
        self._instances[role] = instance
    
    def list_agents(self) -> List[str]:
        """列出所有注册的Agent"""
        return list(self._agents.keys())
    
    def get_all_instances(self) -> Dict:
        """获取所有实例"""
        return self._instances

def register_agent(role: str):
    """Agent注册装饰器"""
    def decorator(agent_class: Type):
        AgentRegistry.get_instance().register(role, agent_class)
        return agent_class
    return decorator
