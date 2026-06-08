from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", extra="allow")
    url: str = "sqlite+aiosqlite:///ic_verification.db"
    echo: bool = False

class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_", env_file=".env", env_file_encoding="utf-8", extra="allow")
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    temperature: float = 0.0
    max_tokens: int = 4096
    api_key: str = ""
    base_url: Optional[str] = "https://api.deepseek.com/v1"

class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="allow")
    max_agents: int = 9
    max_iterations: int = 8
    timeout: int = 300
    verbose: bool = True

class VerificationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VERIFY_", extra="allow")
    regression_timeout: int = 3600
    coverage_target: float = 95.0
    max_retries: int = 3

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="allow")
    database: DatabaseSettings = DatabaseSettings()
    llm: LLMSettings = LLMSettings()
    agent: AgentSettings = AgentSettings()
    verification: VerificationSettings = VerificationSettings()
    agent_config: dict = {}

_instance = None

def get_settings():
    global _instance
    if _instance is None:
        _instance = Settings()
    return _instance

Settings.get_instance = staticmethod(get_settings)
