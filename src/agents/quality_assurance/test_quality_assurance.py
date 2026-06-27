"""Tests for QualityAssurance agent"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.agents.quality_assurance import QualityAssurance


@pytest.mark.asyncio
async def test_init():
    """Test quality assurance initialization"""
    agent = QualityAssurance()
    await agent.initialize()
    assert agent.status.value == "idle"


@pytest.mark.asyncio
async def test_basic():
    """Test quality assurance basic execution"""
    agent = QualityAssurance()
    await agent.initialize()
    result = await agent.execute_task({"input": "test"})
    assert result.success
