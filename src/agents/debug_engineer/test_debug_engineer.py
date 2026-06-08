"""Tests for DebugEngineer agent"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.agents.debug_engineer import DebugEngineer


@pytest.mark.asyncio
async def test_init():
    """Test debug engineer initialization"""
    agent = DebugEngineer()
    await agent.initialize()
    assert agent.status.value == "idle"


@pytest.mark.asyncio
async def test_bypass():
    """Test debug engineer bypass mode"""
    agent = DebugEngineer()
    await agent.initialize()
    result = await agent.execute_task({"input": "test", "bypass": True})
    assert result.success
