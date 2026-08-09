"""分环境配置 — dev / test / prod profiles"""
from __future__ import annotations

import os
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
    api_key: str = ""           # 生产环境必须显式设置
    base_url: Optional[str] = "https://api.deepseek.com/v1"


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="allow")
    max_agents: int = 9
    max_iterations: int = 8
    timeout: int = 300
    verbose: bool = True
    fallback_on_llm_error: bool = True


class VerificationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VERIFY_", extra="allow")
    regression_timeout: int = 3600
    coverage_target: float = 95.0
    max_retries: int = 3


class PlatformSettings(BaseSettings):
    """平台运维配置"""
    model_config = SettingsConfigDict(env_prefix="PLATFORM_", extra="allow")
    # 环境标识: dev / test / prod
    env: str = "production"
    # 安全
    jwt_secret: str = ""
    bootstrap_admin_password: str = ""    # 生产环境必须显式设置
    demo_enabled: bool = False            # 生产环境必须关闭
    # 审计
    audit_retention_days: int = 90
    # 备份
    backup_enabled: bool = True
    backup_dir: str = "backups"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="allow",
        env_nested_delimiter="__",
    )
    database: DatabaseSettings = DatabaseSettings()
    llm: LLMSettings = LLMSettings()
    agent: AgentSettings = AgentSettings()
    verification: VerificationSettings = VerificationSettings()
    platform: PlatformSettings = PlatformSettings()
    agent_config: dict = {}

    @property
    def is_production(self) -> bool:
        return self.platform.env == "production"

    @property
    def is_development(self) -> bool:
        return self.platform.env == "development"

    @property
    def is_test(self) -> bool:
        return self.platform.env == "test"

    def validate_production(self):
        """生产环境安全校验"""
        if not self.is_production:
            return []
        issues = []
        if not self.platform.jwt_secret:
            issues.append("PLATFORM_JWT_SECRET 未设置")
        if self.platform.demo_enabled:
            issues.append("生产环境不应启用 DEMO_ENABLED")
        if not self.llm.api_key:
            issues.append("LLM_API_KEY 未设置")
        return issues


_instance: Optional[Settings] = None


def get_settings() -> Settings:
    global _instance
    if _instance is None:
        env = os.environ.get("PLATFORM_ENV", "production")
        # 自动加载对应环境的 .env 文件
        env_file = ".env" if env == "production" else f".env.{env}"
        _instance = Settings(_env_file=env_file if os.path.exists(env_file) else ".env")

        # 生产环境安全提醒
        if _instance.is_production:
            issues = _instance.validate_production()
            for i in issues:
                print(f"[settings] WARNING: {i}")
    return _instance


Settings.get_instance = staticmethod(get_settings)
