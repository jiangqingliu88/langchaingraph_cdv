"""Registry tests — 当前 7 Agent 注册中心"""
from src.layers.l2_orchestration.agents.registry import AgentRegistry, register_agent
from src.layers.l2_orchestration.agents.base import BaseAgent


class MockAgent(BaseAgent):
    task_type = "test"

    async def _setup(self):
        pass

    async def _get_prompt_template(self):
        return None

    async def _get_tools(self):
        return []

    async def _execute(self, text):
        return {"output": text}


def test_registry_singleton():
    r1 = AgentRegistry.get_instance()
    r2 = AgentRegistry.get_instance()
    assert r1 is r2


def test_register_agent():
    registry = AgentRegistry.get_instance()
    registry.register("test_agent", MockAgent)
    assert "test_agent" in registry.list_agents()
    cls = registry.get_agent_class("test_agent")
    assert cls is MockAgent


def test_decorator_register():
    @register_agent("decorated_agent")
    class DecoratedMock(MockAgent):
        pass

    registry = AgentRegistry.get_instance()
    assert "decorated_agent" in registry.list_agents()
