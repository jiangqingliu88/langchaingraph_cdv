"""分环境配置 — dev / test / prod profiles"""
from __future__ import annotations

import os
import sys
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DB_", extra="allow")
    url: str = "sqlite+aiosqlite:///ic_verification.db"
    echo: bool = False


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_", env_file=".env", env_file_encoding="utf-8", extra="allow")
    provider: str = "deepseek"
    model: str = "deepseek-flash"
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
    #: **闭环按哪个覆盖率收敛** —— `functional`（默认）或 `code`。
    #:
    #: 它决定 `state.final_coverage`（收敛信号）、审计的达标门槛、以及"这一轮
    #: 有没有长进"的判断全部盯哪个数。
    #:
    #:   · `functional` —— **功能覆盖率**（covergroup 的 bin 命中）。它是本项目的
    #:     方法学落点，也是闭环**动作推得动**的那个数：定向补测补的是覆盖点/bins，
    #:     "补了 → 涨了"这条因果链是通的。
    #:   · `code` —— 代码覆盖率（statement/branch/condition…）。它对定向补测不
    #:     敏感（把一条激励从"没走到"变成"走到了"通常只动个位数 branch），拿它当
    #:     闭环目标实测会**长期卡死在同一个数**（六轮不动，32.5%）。
    #:
    #: 两个数都留在报告里（`report.json` 的 `coverage` / `code_coverage`），
    #: 换口径只影响"闭环盯哪个"，不影响"人能看到什么"。
    coverage_metric: str = "functional"
    max_retries: int = 3
    # 回归模式：True=增量（只跑 planned/generated）；False=全量（每次跑所有用例，含已 passed，默认）
    incremental_regression: bool = False
    # QuestaSim 安装根目录（不含 win64）。留空则回落到 QUESTA_HOME 环境变量与候选探测，
    # 见本模块的 questa_home()。此处配置对应环境变量 VERIFY_QUESTA_HOME。
    questa_home: str = ""


class PlatformSettings(BaseSettings):
    """平台运维配置"""
    model_config = SettingsConfigDict(env_prefix="PLATFORM_", extra="allow")
    # 环境标识: dev / test / prod
    env: str = "production"
    # 人工操作者署名 —— 写进证据链的"谁改的 / 谁批的"。留空则回落到系统登录名。
    # 单独留一个可配置的名字（像 git 的 user.name）而不是直接用登录名：这个名字
    # 是审计答案的一部分，跟着"当前登录的是谁"漂移的话，换台机器同一个人就成了
    # 两个作者。环境变量：PLATFORM_USER_NAME
    user_name: str = ""
    # 产品等级: personal / community / enterprise
    tier: str = "personal"
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

    # ── 产品等级 ──

    @property
    def tier(self) -> str:
        """personal | community | enterprise"""
        return self.platform.tier

    @property
    def is_personal(self) -> bool:
        return self.tier == "personal"

    @property
    def is_enterprise(self) -> bool:
        return self.tier == "enterprise"

    # ── 等级差异化开关（按 cost/benefit 优先级排列）──

    @property
    def max_agents(self) -> int:
        """Agent 并发上限"""
        return {"personal": 5, "community": 9, "enterprise": 20}.get(self.tier, 5)

    @property
    def feedback_loop_enabled(self) -> bool:
        """debug→修复→重试 闭环"""
        return self.tier in ("enterprise",)

    @property
    def evidence_chain_enabled(self) -> bool:
        """签核证据链收集"""
        return self.tier in ("community", "enterprise")

    @property
    def sse_enabled(self) -> bool:
        """SSE 实时推送"""
        return self.tier != "personal"

    @property
    def engines_enabled(self) -> bool:
        """五大差异化引擎 (VPlan/SmartRegress/DebugCopilot/Triage)"""
        return self.tier in ("enterprise",)

    @property
    def web_dashboard_enabled(self) -> bool:
        """Web 仪表盘"""
        return self.tier != "personal"

    @property
    def multi_user_enabled(self) -> bool:
        """多用户 / RBAC"""
        return self.tier == "enterprise"

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

        # 生产环境安全提醒（写 stderr，避免污染 stdout 的 --json 输出）
        if _instance.is_production:
            issues = _instance.validate_production()
            for i in issues:
                print(f"[settings] WARNING: {i}", file=sys.stderr)
    return _instance


Settings.get_instance = staticmethod(get_settings)


# ═══════════════════════════════════════════════════════════════
# QuestaSim 定位 —— 全仓唯一来源
# ═══════════════════════════════════════════════════════════════
# 历史上这条路径以字面量散落在 10+ 个模块里（f:/questasim64_2024.1/win64），
# 换机器/换版本就得全仓搜改。统一收敛到此处。

# 候选探测路径（兜底，非唯一真理）
_QUESTA_CANDIDATES = (
    "f:/questasim64_2024.1",
    "c:/questasim64_2024.1",
    "/opt/questasim",
)


def _normalize_questa_root(path: str) -> str:
    """归一化为「不含 win64」的根目录。"""
    p = str(path).strip().rstrip("/\\")
    if p.lower().endswith("win64"):
        p = p[:-len("win64")].rstrip("/\\")
    return p


def _has_questa(root: str) -> bool:
    """根目录下能找到一个 vlog.exe 即认为有效（带或不带 win64 子目录）。"""
    if not root:
        return False
    return (os.path.exists(os.path.join(root, "win64", "vlog.exe"))
            or os.path.exists(os.path.join(root, "vlog.exe")))


def questa_home() -> str:
    """QuestaSim 安装根目录（**不含** win64）。

    优先级: QUESTA_HOME 环境变量 > Settings.verification.questa_home > 候选探测。
    都找不到时返回首个候选（不抛异常），由调用方按 os.path.exists 报
    "vlog not found"，保持原有失败可见性。
    """
    candidates = []
    env = os.environ.get("QUESTA_HOME", "").strip()
    if env:
        candidates.append(env)
    try:
        cfg = (get_settings().verification.questa_home or "").strip()
        if cfg:
            candidates.append(cfg)
    except Exception:
        pass
    candidates.extend(_QUESTA_CANDIDATES)

    for c in candidates:
        root = _normalize_questa_root(c)
        if _has_questa(root):
            return root
    return _normalize_questa_root(candidates[0]) if candidates else ""


def questa_exe(name: str) -> str:
    """QuestaSim 可执行文件全路径，如 questa_exe("vlog.exe")。

    依次尝试 <root>/win64/<name>、<root>/<name>；都找不到时返回
    <root>/win64/<name>，由调用方按 os.path.exists 判失败。
    """
    root = questa_home()
    for cand in (os.path.join(root, "win64", name), os.path.join(root, name)):
        if os.path.exists(cand):
            return cand
    return os.path.join(root, "win64", name)
