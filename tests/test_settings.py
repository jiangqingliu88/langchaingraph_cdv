"""Settings tests"""
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
