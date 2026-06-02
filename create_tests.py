import os

# ==================== conftest.py ====================
with open('tests/conftest.py', 'w', encoding='utf-8') as f:
    f.write('''"""Test configuration"""
import asyncio
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
''')

# ==================== test_agents.py ====================
with open('tests/test_agents.py', 'w', encoding='utf-8') as f:
    f.write('''"""Agent tests"""
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
''')

# ==================== test_tools.py ====================
with open('tests/test_tools.py', 'w', encoding='utf-8') as f:
    f.write('''"""Tool tests"""
import json
from src.tools.spec_tools import analyze_specification, extract_features, generate_test_plan
from src.tools.uvm_tools import UVMTools
from src.tools.assertion_tools import generate_sva_assertions
from src.tools.debug_tools import analyze_simulation_log
from src.tools.coverage_tools import collect_coverage

def test_analyze_specification():
    result = analyze_specification("UART spec")
    data = json.loads(result)
    assert "features" in data
    assert "interfaces" in data

def test_extract_features():
    result = extract_features("spec")
    data = json.loads(result)
    assert "basic_features" in data

def test_generate_test_plan():
    result = generate_test_plan("reqs")
    data = json.loads(result)
    assert "test_categories" in data
    assert len(data["test_categories"]) > 0

def test_uvm_driver_generation():
    tools = UVMTools()
    code = tools.generate_uvm_driver('{"driver_name": "test_driver"}')
    assert "class test_driver" in code
    assert "uvm_driver" in code

def test_uvm_monitor_generation():
    tools = UVMTools()
    code = tools.generate_uvm_monitor('{}')
    assert "uvm_monitor" in code

def test_sva_assertions():
    result = generate_sva_assertions("{}")
    data = json.loads(result)
    assert "assertions" in data

def test_analyze_log():
    result = analyze_simulation_log("test.log")
    data = json.loads(result)
    assert "errors" in data

def test_collect_coverage():
    result = collect_coverage("all")
    data = json.loads(result)
    assert "code_coverage" in data
''')

# ==================== test_registry.py ====================
with open('tests/test_registry.py', 'w', encoding='utf-8') as f:
    f.write('''"""Registry tests"""
from src.core.registry import AgentRegistry, register_agent
from src.core.base import BaseAgent

class MockAgent(BaseAgent):
    task_type = "test"
    async def _setup(self): pass
    async def _get_prompt_template(self): pass
    async def _get_tools(self): return []
    async def _execute(self, text): return {"output": text}

def test_registry_singleton():
    r1 = AgentRegistry.get_instance()
    r2 = AgentRegistry.get_instance()
    assert r1 is r2

def test_register_agent():
    registry = AgentRegistry.get_instance()
    registry.register("test_agent", MockAgent)
    assert "test_agent" in registry.list_agents()
    cls = registry.get_agent_class("test_agent")
    assert cls is MockAgent

def test_decorator_register():
    @register_agent("decorated_agent")
    class DecoratedMock(MockAgent):
        pass
    registry = AgentRegistry.get_instance()
    assert "decorated_agent" in registry.list_agents()
''')

# ==================== test_settings.py ====================
with open('tests/test_settings.py', 'w', encoding='utf-8') as f:
    f.write('''"""Settings tests"""
import os
from config.settings import Settings, LLMSettings, AgentSettings

def test_settings_singleton():
    s1 = Settings.get_instance()
    s2 = Settings.get_instance()
    assert s1 is s2

def test_llm_settings_defaults():
    llm = LLMSettings()
    assert llm.provider == "deepseek"
    assert llm.temperature == 0.0

def test_agent_settings_defaults():
    agent = AgentSettings()
    assert agent.max_agents == 9
    assert agent.verbose == True

def test_settings_env_override():
    os.environ["LLM_PROVIDER"] = "test_provider"
    llm = LLMSettings()
    assert llm.provider == "test_provider"
    del os.environ["LLM_PROVIDER"]
''')

print("All test files created!")
