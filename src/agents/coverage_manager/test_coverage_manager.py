"""Tests for CoverageManager agent"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.agents.coverage_manager import CoverageManager


@pytest.mark.asyncio
async def test_init():
    """Test coverage manager initialization"""
    agent = CoverageManager()
    await agent.initialize()
    assert agent.status.value == "idle"


@pytest.mark.asyncio
async def test_basic():
    """Test coverage manager basic execution"""
    agent = CoverageManager()
    await agent.initialize()
    result = await agent.execute_task({"input": "test"})
    assert result.success
