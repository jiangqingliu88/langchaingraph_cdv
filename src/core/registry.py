"""
Agent注册中心 —— 支持领域角色名 + 认知任务元数据
"""
from typing import Dict, Type, Optional, List
import structlog

logger = structlog.get_logger()

class AgentRegistry:
    """Agent注册中心 - Singleton模式"""

    _instance: Optional["AgentRegistry"] = None
    _agents: Dict[str, Type] = {}
    _instances: Dict[str, object] = {}
    _cognitive_tasks: Dict[str, str] = {}  # role → cognitive_task label

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

    def register(self, role: str, agent_class: Type, cognitive_task: str = ""):
        """注册Agent类，可选附加认知任务标签"""
        self._agents[role] = agent_class
        if cognitive_task:
            self._cognitive_tasks[role] = cognitive_task
        logger.info(f"Agent已注册", role=role)

    def unregister(self, role: str):
        """取消注册"""
        if role in self._agents:
            del self._agents[role]
        if role in self._cognitive_tasks:
            del self._cognitive_tasks[role]

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

    def get_cognitive_task(self, role: str) -> str:
        """获取 Agent 的认知任务标签"""
        return self._cognitive_tasks.get(role, "")

    def list_cognitive_tasks(self) -> Dict[str, str]:
        """列出所有 Agent 的认知任务映射"""
        return dict(self._cognitive_tasks)


def register_agent(role: str, cognitive_task: str = ""):
    """Agent注册装饰器

    Args:
        role: 领域角色名（如 'spec_planner', 'design_architect'）
        cognitive_task: LLM 认知动作标签（如 'intent_extraction', 'module_decomposition'）
    """
    def decorator(agent_class: Type):
        AgentRegistry.get_instance().register(role, agent_class, cognitive_task)
        return agent_class
    return decorator
