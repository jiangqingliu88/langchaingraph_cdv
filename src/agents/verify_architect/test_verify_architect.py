"""Tests for VerificationArchitect agent"""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.agents.verify_architect import VerificationArchitect


@pytest.mark.asyncio
async def test_init():
    """Test verification architect initialization"""
    agent = VerificationArchitect()
    await agent.initialize()
    assert agent.status.value == "idle"


@pytest.mark.asyncio
async def test_basic():
    """Test verification architect basic execution"""
    agent = VerificationArchitect()
    await agent.initialize()
    result = await agent.execute_task({"input": "UART spec with tx/rx signals"})
    assert result.success


@pytest.mark.asyncio
async def test_basic_with_spec():
    """Test basic execution with UART spec"""
    agent = VerificationArchitect()
    await agent.initialize()
    result = await agent.execute_task({
        "input": "UART module with tx, rx, baud_rate signals",
    })
    assert result.success
