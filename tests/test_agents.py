"""Agent tests"""
import pytest
import asyncio
from src.agents.spec_planner import SpecAndTestPlanner
from src.agents.architect import VerificationArchitect
from src.agents.sequence_engineer import SequenceEngineer
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
    SequenceEngineer,
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
    assert agent.llm is not None

@pytest.mark.parametrize("agent_cls", AGENTS)
@pytest.mark.asyncio
async def test_agent_bypass(agent_cls):
    """Test agent bypass mode"""
    agent = agent_cls()
    await agent.initialize()
    result = await agent.execute_task({"input": "test", "bypass": True})
    assert result.success

@pytest.mark.asyncio
async def test_spec_planner_analyze():
    """Test spec planner analysis"""
    agent = SpecAndTestPlanner()
    await agent.initialize()
    result = await agent.execute_task({"input": "UART design spec", "bypass": True})
    assert result.success
    assert "output" in result.data

@pytest.mark.asyncio
async def test_architect_generate():
    """Test architect code generation"""
    agent = VerificationArchitect()
    await agent.initialize()
    code = await agent.generate_component("driver", {"name": "test"})
    assert len(code) > 0

@pytest.mark.asyncio
async def test_agent_metrics():
    """Test agent metrics tracking"""
    agent = SpecAndTestPlanner()
    await agent.initialize()
    await agent.execute_task({"input": "test", "bypass": True})
    metrics = agent.get_metrics()
    assert metrics["tasks_completed"] >= 1
    assert metrics["status"] == "idle"
