"""Tests for ModelAgent agent"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.agents.model_agent import ModelAgent


@pytest.mark.asyncio
async def test_init():
    """Test model agent initialization"""
    agent = ModelAgent()
    await agent.initialize()
    assert agent.status.value == "idle"


@pytest.mark.asyncio
async def test_basic():
    """Test model agent basic execution"""
    agent = ModelAgent()
    await agent.initialize()
    result = await agent.execute_task({"input": "test design"})
    assert result.success
