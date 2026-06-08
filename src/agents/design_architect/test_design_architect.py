"""Tests for DesignArchitect agent"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.agents.design_architect import DesignArchitect


@pytest.mark.asyncio
async def test_init():
    """Test design architect initialization"""
    agent = DesignArchitect()
    await agent.initialize()
    assert agent.status.value == "idle"


@pytest.mark.asyncio
async def test_bypass():
    """Test design architect bypass mode"""
    agent = DesignArchitect()
    await agent.initialize()
    result = await agent.execute_task({"input": "module UART ... bypass spec", "bypass": True})
    assert result.success
