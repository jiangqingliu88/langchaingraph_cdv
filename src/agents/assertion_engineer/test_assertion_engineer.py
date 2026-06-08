"""Tests for AssertionEngineer agent"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.agents.assertion_engineer import AssertionEngineer


@pytest.mark.asyncio
async def test_init():
    """Test assertion engineer initialization"""
    agent = AssertionEngineer()
    await agent.initialize()
    assert agent.status.value == "idle"


@pytest.mark.asyncio
async def test_bypass():
    """Test assertion engineer bypass mode"""
    agent = AssertionEngineer()
    await agent.initialize()
    result = await agent.execute_task({"input": "test", "bypass": True})
    assert result.success
