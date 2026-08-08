"""
LLM 工厂 — 多提供商抽象层

支持的提供商:
  - deepseek:  DeepSeek API (OpenAI 兼容)
  - openai:    OpenAI API
  - anthropic: Anthropic Claude API
  - custom:    自定义 OpenAI 兼容 API (vLLM / Ollama / local)

设计原则:
  1. 所有 Agent 通过 create_llm() / create_for_task() 获取 LLM
  2. 禁止硬编码 API URL（如 verify_architect 的 _call_llm）
  3. 支持 fallback 链：主提供商失败 → 自动切换备用
"""
from typing import Optional, Dict, Any, List
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
import structlog, time

from config.settings import Settings

logger = structlog.get_logger()

# ── 支持的提供商 ──
ProviderType = str
PROVIDER_DEEPSEEK: ProviderType = "deepseek"
PROVIDER_OPENAI:   ProviderType = "openai"
PROVIDER_ANTHROPIC: ProviderType = "anthropic"
PROVIDER_CUSTOM:   ProviderType = "custom"


class LLMTracerCallback(BaseCallbackHandler):
    """LangChain callback that logs LLM calls to ExecutionTracer."""

    def on_llm_start(self, serialized, prompts, **kwargs):
        self._start_time = time.time()
        self._prompts = prompts

    def on_llm_end(self, response: LLMResult, **kwargs):
        elapsed = time.time() - self._start_time
        try:
            from src.middleware.debug_logger import tracer
            prompt_text = self._prompts[0][:200] if self._prompts else ""
            resp_text = str(response.generations[0][0].text)[:200] if response.generations else ""
            tokens = response.llm_output.get("token_usage", {}).get("total_tokens", 0) if response.llm_output else 0
            tracer.llm_call("langchain", prompt_text, resp_text, tokens, elapsed, True)
        except Exception:
            pass


class LLMFactory:
    """
    LLM 工厂 — 提供商抽象 + 任务路由 + fallback

    用法:
      # 按任务类型
      llm = LLMFactory.create_for_task("code_generation")

      # 直接指定
      llm = LLMFactory.create_llm(model="claude-sonnet-4-6")

      # 测试模式（不访问网络）
      LLMFactory.enable_test_mode()
      LLMFactory.disable_test_mode()
    """

    _test_llm: Optional[BaseChatModel] = None
    """注入测试替身：非 None 时 create_llm / create_for_task 直接返回此实例。"""
    _test_role_map: dict = {}
    """按 role 返回不同替身：{role: FakeChatModel}。"""

    @classmethod
    def enable_test_mode(cls, task_type: str = "spec_analysis") -> None:
        """启用测试模式：所有 LLM 请求返回确定性 FakeChatModel。"""
        from src.core.fake_llm import FakeChatModel
        cls._test_llm = FakeChatModel(role=task_type)
        cls._test_role_map = {}

    @classmethod
    def enable_test_mode_per_role(cls, role_map: dict) -> None:
        """启用测试模式并按 role 返回不同 FakeChatModel。"""
        from src.core.fake_llm import FakeChatModel
        cls._test_llm = None
        cls._test_role_map = {role: FakeChatModel(role=role) for role in role_map}

    @classmethod
    def disable_test_mode(cls) -> None:
        """关闭测试模式。"""
        cls._test_llm = None
        cls._test_role_map = {}

    @classmethod
    def _get_test_llm(cls, role_hint: str = "spec_and_test_planner") -> Optional[BaseChatModel]:
        """按 role 获取测试替身。"""
        if cls._test_role_map:
            return cls._test_role_map.get(role_hint, next(iter(cls._test_role_map.values())))
        return cls._test_llm
    
    # DeepSeek模型配置
    DEEPSEEK_MODELS = {
        "deepseek-chat": {
            "description": "通用对话模型，适合分析、规划、调试任务",
            "max_tokens": 4096,
            "context_window": 32768,
            "strengths": ["规格分析", "测试规划", "调试分析", "质量审查"],
            "recommended_tasks": [
                "spec_analysis", "test_planning", "debug_analysis", 
                "quality_review", "report_generation"
            ]
        },
        "deepseek-coder": {
            "description": "代码专用模型，适合UVM/SystemVerilog代码生成",
            "max_tokens": 8192,
            "context_window": 16384,
            "strengths": ["UVM组件生成", "SVA断言生成", "测试序列生成"],
            "recommended_tasks": [
                "code_generation", "assertion_generation", "sequence_generation",
                "coverage_model_generation"
            ]
        }
    }
    
    # Anthropic Claude 模型配置
    ANTHROPIC_MODELS = {
        "claude-sonnet-4-6": {
            "description": "Claude Sonnet 4.6，平衡性能与成本",
            "max_tokens": 4096, "context_window": 200000,
        },
        "claude-opus-4-8": {
            "description": "Claude Opus 4.8，最强推理能力",
            "max_tokens": 4096, "context_window": 200000,
        },
        "claude-haiku-4-5": {
            "description": "Claude Haiku 4.5，最快速度",
            "max_tokens": 4096, "context_window": 200000,
        },
    }

    # OpenAI模型配置
    OPENAI_MODELS = {
        "gpt-4-turbo": {
            "description": "GPT-4 Turbo，通用高性能模型",
            "max_tokens": 4096,
            "context_window": 128000,
        },
        "gpt-4o": {
            "description": "GPT-4o，最新多模态模型",
            "max_tokens": 4096,
            "context_window": 128000,
        },
        "gpt-3.5-turbo": {
            "description": "GPT-3.5 Turbo，性价比高",
            "max_tokens": 4096,
            "context_window": 16385,
        }
    }
    
    # 任务类型与模型映射
    TASK_MODEL_MAPPING = {
        "spec_analysis": {
            "deepseek": {"model": "deepseek-chat", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "test_planning": {
            "deepseek": {"model": "deepseek-chat", "temperature": 0.1},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.1},
        },
        "architecture_design": {
            "deepseek": {"model": "deepseek-coder", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "code_generation": {
            "deepseek": {"model": "deepseek-coder", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "sequence_generation": {
            "deepseek": {"model": "deepseek-coder", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "assertion_generation": {
            "deepseek": {"model": "deepseek-coder", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "coverage_analysis": {
            "deepseek": {"model": "deepseek-chat", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "regression_management": {
            "deepseek": {"model": "deepseek-chat", "temperature": 0.0},
            "openai": {"model": "gpt-3.5-turbo", "temperature": 0.0},
        },
        "debug_analysis": {
            "deepseek": {"model": "deepseek-chat", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "quality_review": {
            "deepseek": {"model": "deepseek-chat", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "report_generation": {
            "deepseek": {"model": "deepseek-chat", "temperature": 0.0},
            "openai": {"model": "gpt-3.5-turbo", "temperature": 0.0},
        },
        "orchestration": {
            "deepseek": {"model": "deepseek-chat", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
    }
    
    @classmethod
    def create_llm(
        cls,
        settings: Optional[Settings] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        request_timeout: int = 120,
        max_retries: int = 3,
    ) -> BaseChatModel:
        """
        创建LLM实例
        
        参数:
            settings: 配置对象，不提供则使用默认配置
            model: 指定模型，覆盖配置中的模型
            temperature: 指定温度
            max_tokens: 最大token数
            request_timeout: 请求超时时间(秒)
            max_retries: 最大重试次数
        
        返回:
            BaseChatModel实例
        """
        # 测试模式：直接返回注入的替身
        test_llm = cls._get_test_llm()
        if test_llm is not None:
            return test_llm

        if settings is None:
            settings = Settings.get_instance()
        
        llm_config = settings.llm
        
        # 确定参数
        selected_model = model or llm_config.model
        selected_temperature = temperature if temperature is not None else llm_config.temperature
        selected_max_tokens = max_tokens or llm_config.max_tokens
        api_key = llm_config.api_key
        base_url = llm_config.base_url
        
        # 验证API Key
        if not api_key:
            raise ValueError(
                f"LLM API Key未设置！请在.env文件中设置LLM_API_KEY\n"
                f"当前提供商: {llm_config.provider}"
            )
        
        logger.info(
            "创建LLM实例",
            provider=llm_config.provider,
            model=selected_model,
            temperature=selected_temperature,
            max_tokens=selected_max_tokens
        )
        
        # ── 根据提供商创建（支持 fallback） ──
        providers = [llm_config.provider]
        # 添加 fallback 提供商
        fallback = llm_config.fallback_provider if hasattr(llm_config, 'fallback_provider') else None
        if fallback and fallback != llm_config.provider:
            providers.append(fallback)

        last_error = None
        for provider in providers:
            try:
                return cls._create_for_provider(
                    provider=provider,
                    api_key=api_key,
                    model=selected_model,
                    temperature=selected_temperature,
                    max_tokens=selected_max_tokens,
                    request_timeout=request_timeout,
                    max_retries=max_retries,
                    base_url=base_url,
                )
            except Exception as e:
                last_error = e
                logger.warning(f"Provider '{provider}' failed: {e}, trying next...")

        raise ValueError(f"All providers failed. Last error: {last_error}")

    @classmethod
    def _create_for_provider(
        cls, provider: str, api_key: str, model: str,
        temperature: float, max_tokens: int, request_timeout: int,
        max_retries: int, base_url: Optional[str] = None,
    ) -> BaseChatModel:
        """根据提供商名称创建 LLM 实例。"""
        if provider == PROVIDER_DEEPSEEK:
            return cls._create_openai_compat(
                api_key=api_key, model=model,
                temperature=temperature, max_tokens=max_tokens,
                request_timeout=request_timeout, max_retries=max_retries,
                base_url=base_url or "https://api.deepseek.com/v1",
            )
        elif provider == PROVIDER_OPENAI:
            return cls._create_openai_compat(
                api_key=api_key, model=model,
                temperature=temperature, max_tokens=max_tokens,
                request_timeout=request_timeout, max_retries=max_retries,
                base_url=base_url,
            )
        elif provider == PROVIDER_ANTHROPIC:
            return cls._create_anthropic(
                api_key=api_key, model=model,
                temperature=temperature, max_tokens=max_tokens,
                request_timeout=request_timeout, max_retries=max_retries,
            )
        else:  # custom
            if not base_url:
                raise ValueError("自定义 LLM 需要提供 base_url (如 http://localhost:11434/v1 for Ollama)")
            return cls._create_openai_compat(
                api_key=api_key or "not-needed", model=model,
                temperature=temperature, max_tokens=max_tokens,
                request_timeout=request_timeout, max_retries=max_retries,
                base_url=base_url,
            )
    
    @classmethod
    def _create_openai_compat(
        cls, api_key: str, model: str, temperature: float,
        max_tokens: int, request_timeout: int, max_retries: int,
        base_url: Optional[str] = None,
    ) -> ChatOpenAI:
        """创建 OpenAI 兼容 LLM (DeepSeek/OpenAI/vLLM/Ollama)"""
        kwargs = {"model": model, "api_key": api_key, "temperature": temperature,
                  "max_tokens": max_tokens, "request_timeout": request_timeout,
                  "max_retries": max_retries, "callbacks": [LLMTracerCallback()]}
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    @classmethod
    def _create_anthropic(
        cls, api_key: str, model: str, temperature: float,
        max_tokens: int, request_timeout: int, max_retries: int,
    ) -> BaseChatModel:
        """创建 Anthropic Claude 实例"""
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError("pip install langchain-anthropic")
        return ChatAnthropic(model=model, api_key=api_key, temperature=temperature,
                            max_tokens=max_tokens, timeout=request_timeout)
    
    @classmethod
    def create_for_task(
        cls,
        task_type: str,
        settings: Optional[Settings] = None
    ) -> BaseChatModel:
        """
        根据任务类型创建优化的LLM实例
        
        参数:
            task_type: 任务类型
                - spec_analysis: 规格分析
                - test_planning: 测试规划
                - architecture_design: 架构设计
                - code_generation: 代码生成(UVM组件)
                - sequence_generation: 序列生成
                - assertion_generation: 断言生成
                - coverage_analysis: 覆盖率分析
                - regression_management: 回归管理
                - debug_analysis: 调试分析
                - quality_review: 质量审查
                - report_generation: 报告生成
                - orchestration: 编排决策
            settings: 配置对象
        
        返回:
            针对任务优化的LLM实例
        """
        # 测试模式：直接返回注入的替身
        test_llm = cls._get_test_llm()
        if test_llm is not None:
            return test_llm

        # 测试模式
        if settings is None:
            settings = Settings.get_instance()

        test_llm = cls._get_test_llm(task_type)
        if test_llm is not None:
            return test_llm

        provider = settings.llm.provider
        task_config = cls.TASK_MODEL_MAPPING.get(task_type, {})
        provider_config = task_config.get(provider, {})
        
        model = provider_config.get("model", settings.llm.model)
        temperature = provider_config.get("temperature", settings.llm.temperature)
        
        logger.info(
            "为任务创建LLM",
            task_type=task_type,
            model=model,
            temperature=temperature
        )
        
        return cls.create_llm(
            settings=settings,
            model=model,
            temperature=temperature
        )
    
    @classmethod
    def create_for_code_generation(
        cls,
        settings: Optional[Settings] = None
    ) -> BaseChatModel:
        """为代码生成任务创建LLM（自动选择最优模型）"""
        return cls.create_for_task("code_generation", settings)
    
    @classmethod
    def create_for_analysis(
        cls,
        settings: Optional[Settings] = None
    ) -> BaseChatModel:
        """为分析任务创建LLM"""
        return cls.create_for_task("spec_analysis", settings)
    
    @classmethod
    def create_for_planning(
        cls,
        settings: Optional[Settings] = None
    ) -> BaseChatModel:
        """为规划任务创建LLM"""
        return cls.create_for_task("test_planning", settings)
    
    @classmethod
    def get_model_info(cls, model_name: str) -> Dict[str, Any]:
        """获取模型信息"""
        all_models = {**cls.DEEPSEEK_MODELS, **cls.OPENAI_MODELS}
        return all_models.get(model_name, {})
    
    @classmethod
    def list_models(cls, provider: Optional[str] = None) -> Dict[str, Any]:
        """列出可用模型"""
        if provider == "deepseek":
            return cls.DEEPSEEK_MODELS
        elif provider == "openai":
            return cls.OPENAI_MODELS
        return {**cls.DEEPSEEK_MODELS, **cls.OPENAI_MODELS}
    
    @classmethod
    def validate_connection(cls, settings: Optional[Settings] = None) -> bool:
        """
        验证LLM连接是否正常（同步版本，用于快速检查）
        """
        try:
            llm = cls.create_llm(settings, request_timeout=10)
            # 简单测试
            response = llm.invoke("test")
            return True
        except Exception as e:
            logger.error("LLM连接验证失败", error=str(e))
            return False