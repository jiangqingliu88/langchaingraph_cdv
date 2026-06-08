"""Tests for RegressionManager agent"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.agents.regression_manager import RegressionManager


@pytest.mark.asyncio
async def test_init():
    """Test regression manager initialization"""
    agent = RegressionManager()
    await agent.initialize()
    assert agent.status.value == "idle"


@pytest.mark.asyncio
async def test_bypass():
    """Test regression manager bypass mode"""
    agent = RegressionManager()
    await agent.initialize()
    result = await agent.execute_task({"input": "test", "bypass": True})
    assert result.success
