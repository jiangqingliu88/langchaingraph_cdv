"""Tests for SpecAndTestPlanner agent"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.agents.spec_planner import SpecAndTestPlanner


@pytest.mark.asyncio
async def test_init():
    """Test spec planner initialization"""
    agent = SpecAndTestPlanner()
    await agent.initialize()
    assert agent.status.value == "idle"


@pytest.mark.asyncio
async def test_bypass():
    """Test spec planner bypass mode"""
    agent = SpecAndTestPlanner()
    await agent.initialize()
    result = await agent.execute_task({"input": "UART design spec", "bypass": True})
    assert result.success


@pytest.mark.asyncio
async def test_analyze():
    """Test spec planner outputs proper data structure"""
    agent = SpecAndTestPlanner()
    await agent.initialize()
    result = await agent.execute_task({"input": "UART design spec", "bypass": True})
    assert result.success
    assert "output" in result.data
