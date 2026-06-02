"""
测试配置
"""
import asyncio
import pytest
from pathlib import Path
import sys

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Settings

@pytest.fixture
def settings():
    """Settings fixture"""
    return Settings.get_instance()

@pytest.fixture
def event_loop():
    """Event loop fixture"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def mock_llm():
    """Mock LLM fixture"""
    class MockLLM:
        async def ainvoke(self, *args, **kwargs):
            return {"output": "Mock response"}
    
    return MockLLM()