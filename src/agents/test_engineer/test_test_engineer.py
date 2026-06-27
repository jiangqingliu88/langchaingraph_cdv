"""Tests for TestEngineer agent"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.agents.test_engineer import TestEngineer


@pytest.mark.asyncio
async def test_init():
    """Test test engineer initialization"""
    agent = TestEngineer()
    await agent.initialize()
    assert agent.status.value == "idle"


@pytest.mark.asyncio
async def test_basic():
    """Test test engineer basic execution"""
    agent = TestEngineer()
    await agent.initialize()
    result = await agent.execute_task({"input": "UART test spec"})
    assert result.success
