"""Agent tests"""
import pytest
import asyncio
from src.agents.spec_planner import SpecAndTestPlanner
from src.agents.verify_architect import VerificationArchitect
from src.agents.assertion_engineer import AssertionEngineer
from src.agents.coverage_manager import CoverageManager
from src.agents.regression_manager import RegressionManager
from src.agents.debug_engineer import DebugEngineer
from src.agents.quality_assurance import QualityAssurance
from src.agents.report_generator import ReportGenerator
from src.core.registry import AgentRegistry
from src.core.llm_factory import LLMFactory

AGENTS = [
    SpecAndTestPlanner,
    VerificationArchitect,
    AssertionEngineer,
    CoverageManager,
    RegressionManager,
    DebugEngineer,
    QualityAssurance,
    ReportGenerator,
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
async def test_spec_planner_analyze():
    """Test spec planner analysis"""
    agent = SpecAndTestPlanner()
    await agent.initialize()
    result = await agent.execute_task({"input": "UART design spec"})
    assert result.success
    assert "output" in result.data

@pytest.mark.asyncio
async def test_architect_generate():
    """Test architect basic execution"""
    agent = VerificationArchitect()
    await agent.initialize()
    result = await agent.execute_task({"input": "UART spec with tx/rx signals"})
    assert result.success

@pytest.mark.asyncio
async def test_agent_metrics():
    """Test agent metrics tracking"""
    agent = SpecAndTestPlanner()
    await agent.initialize()
    await agent.execute_task({"input": "test"})
    metrics = agent.get_metrics()
    assert metrics["tasks_completed"] >= 1
    assert metrics["status"] == "idle"
