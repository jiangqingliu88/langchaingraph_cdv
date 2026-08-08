"""Test configuration — all tests run offline with deterministic Fake LLM."""
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


@pytest.fixture(autouse=True)
def fake_llm():
    """所有测试使用确定性 Fake LLM，不访问网络、不需要 API Key。

    按 agent role 返回不同预设 JSON 响应，触发 BaseAgent 的 auto-detect 评分。
    """
    from src.core.llm_factory import LLMFactory
    LLMFactory.enable_test_mode_per_role({
        "spec_and_test_planner": "spec_and_test_planner",
        "design_architect": "design_architect",
        "verification_architect": "verification_architect",
        "model_agent": "model_agent",
        "test_engineer": "test_engineer",
        "assertion_engineer": "assertion_engineer",
        "regression_manager": "regression_manager",
        "coverage_manager": "coverage_manager",
        "debug_engineer": "debug_engineer",
        "quality_assurance": "quality_assurance",
        "report_generator": "report_generator",
    })
    yield
    LLMFactory.disable_test_mode()
