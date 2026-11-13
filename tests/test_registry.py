"""Registry tests — 当前 7 Agent 注册中心"""
from src.orchestration_plane.l2.executors.registry import ExecutorRegistry, register_executor
from src.orchestration_plane.l2.executors.base import BaseExecutor


class MockExecutor(BaseExecutor):
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
    r1 = ExecutorRegistry.get_instance()
    r2 = ExecutorRegistry.get_instance()
    assert r1 is r2


def test_register_executor():
    registry = ExecutorRegistry.get_instance()
    registry.register("test_agent", MockExecutor)
    assert "test_agent" in registry.list_agents()
    cls = registry.get_agent_class("test_agent")
    assert cls is MockExecutor


def test_decorator_register():
    @register_executor("decorated_agent")
    class DecoratedMock(MockExecutor):
        pass

    registry = ExecutorRegistry.get_instance()
    assert "decorated_agent" in registry.list_agents()
