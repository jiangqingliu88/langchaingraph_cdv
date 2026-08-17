"""Agent tests"""
import pytest
import asyncio
from src.agents.spec import SpecAgent
from src.agents.design import DesignAgent
from src.agents.asserts import AssertsAgent
from src.agents.cover import CoverAgent
from src.agents.regress import RegressAgent
from src.agents.debug import DebugAgent
from src.agents.qa import QaAgent
from src.agents.report import ReportAgent
from src.layers.l2_orchestration.registry import AgentRegistry
from src.layers.l2_orchestration.llm_factory import LLMFactory

AGENTS = [
    SpecAgent,
    DesignAgent,
    AssertsAgent,
    CoverAgent,
    RegressAgent,
    DebugAgent,
    QaAgent,
    ReportAgent,
]

@pytest.mark.parametrize("agent_cls", AGENTS)
@pytest.mark.asyncio
async def test_agent_init(agent_cls):
    """Test agent initialization"""
    agent = agent_cls()
    await agent.initialize()
    assert agent.status.value == "idle"
    # LLM may be None if API key is not configured (environment-dependent)

@pytest.mark.parametrize("agent_cls", AGENTS)
@pytest.mark.asyncio
async def test_agent_basic(agent_cls):
    """Test agent basic execution"""
    agent = agent_cls()
    await agent.initialize()
    result = await agent.execute_task({"input": "test"})
    assert result.success

@pytest.mark.asyncio
async def test_spec_agent_analyze():
    """Test spec agent analysis"""
    agent = SpecAgent()
    await agent.initialize()
    result = await agent.execute_task({"input": "UART design spec"})
    assert result.success
    assert "output" in result.data

@pytest.mark.asyncio
async def test_design_agent_generate():
    """Test design agent basic execution"""
    agent = DesignAgent()
    await agent.initialize()
    result = await agent.execute_task({"input": "UART spec with tx/rx signals"})
    assert result.success

@pytest.mark.asyncio
async def test_agent_metrics():
    """Test agent metrics tracking"""
    agent = SpecAgent()
    await agent.initialize()
    await agent.execute_task({"input": "test"})
    metrics = agent.get_metrics()
    assert metrics["tasks_completed"] >= 1
    assert metrics["status"] == "idle"
