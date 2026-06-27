"""Tests for ReportGenerator agent"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.agents.report_generator import ReportGenerator


@pytest.mark.asyncio
async def test_init():
    """Test report generator initialization"""
    agent = ReportGenerator()
    await agent.initialize()
    assert agent.status.value == "idle"


@pytest.mark.asyncio
async def test_basic():
    """Test report generator basic execution"""
    agent = ReportGenerator()
    await agent.initialize()
    result = await agent.execute_task({"input": "test"})
    assert result.success
