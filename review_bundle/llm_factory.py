"""
LLM 工厂 — 多提供商抽象层

支持的提供商:
  - deepseek:  DeepSeek API (OpenAI 兼容)
  - openai:    OpenAI API
  - anthropic: Anthropic Claude API
  - custom:    自定义 OpenAI 兼容 API (vLLM / Ollama / local)

设计原则:
  1. 所有 Agent 通过 create_llm() / create_for_task() 获取 LLM
  2. 禁止硬编码 API URL（如 testbench_orchestrator 的 _call_llm）
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
    """LangChain callback that logs LLM calls to ExecutionTracer + tracks token usage."""

    # Token budget tracking (shared across all LLM instances)
    total_tokens_used = 0
    call_count = 0

    def on_llm_start(self, serialized, prompts, **kwargs):
        self._start_time = time.time()
        self._prompts = prompts
        LLMTracerCallback.call_count += 1

    def on_llm_end(self, response: LLMResult, **kwargs):
        elapsed = time.time() - self._start_time
        try:
            from src.layers.l2_orchestration.middleware.debug_logger import tracer
            prompt_text = self._prompts[0][:200] if self._prompts else ""
            resp_text = str(response.generations[0][0].text)[:200] if response.generations else ""
            tokens = response.llm_output.get("token_usage", {}).get("total_tokens", 0) if response.llm_output else 0
            if tokens:
                LLMTracerCallback.total_tokens_used += tokens
            tracer.llm_call("langchain", prompt_text, resp_text, tokens, elapsed, True)
        except Exception:
            pass

    @classmethod
    def reset_budget(cls):
        cls.total_tokens_used = 0
        cls.call_count = 0


class LLMFactory:
    """
    LLM 工厂 — 提供商抽象 + 任务路由 + fallback

    用法:
      # 按任务类型
      llm = LLMFactory.create_for_task("code_generation")

      # 直接指定
      llm = LLMFactory.create_llm(model="claude-sonnet-4-6")

    """

    # DeepSeek模型配置
    #
    # 这里列的是**端点真的提供的**模型 —— 2026-10 从 `GET {base_url}/models`
    # 拉回来的就这两个。此前写的 deepseek-chat / deepseek-coder 已经下架，
    # 留着只会让人照着抄一个调不通的名字（那张清单的全部用处就是"能调什么"）。
    DEEPSEEK_MODELS = {
        "deepseek-flash": {
            "description": "DeepSeek-V4.1-Flash，快、上下文 1M，全流程默认模型",
            "max_tokens": 393216,
            "context_window": 1048576,
            "strengths": ["规格分析", "测试规划", "代码生成", "调试分析", "质量审查"],
        },
        "deepseek-v4-pro": {
            "description": "DeepSeek-V4-Pro，同上下文，推理更强、更慢更贵",
            "max_tokens": 393216,
            "context_window": 1048576,
            "strengths": ["复杂架构设计", "疑难调试", "多轮收敛决策"],
        },
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
            "deepseek": {"model": "deepseek-flash", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "test_planning": {
            "deepseek": {"model": "deepseek-flash", "temperature": 0.1},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.1},
        },
        "architecture_design": {
            "deepseek": {"model": "deepseek-flash", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "code_generation": {
            "deepseek": {"model": "deepseek-flash", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "sequence_generation": {
            "deepseek": {"model": "deepseek-flash", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "assertion_generation": {
            "deepseek": {"model": "deepseek-flash", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "coverage_analysis": {
            "deepseek": {"model": "deepseek-flash", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "regression_management": {
            "deepseek": {"model": "deepseek-flash", "temperature": 0.0},
            "openai": {"model": "gpt-3.5-turbo", "temperature": 0.0},
        },
        "debug_analysis": {
            "deepseek": {"model": "deepseek-flash", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "quality_review": {
            "deepseek": {"model": "deepseek-flash", "temperature": 0.0},
            "openai": {"model": "gpt-4-turbo", "temperature": 0.0},
        },
        "report_generation": {
            "deepseek": {"model": "deepseek-flash", "temperature": 0.0},
            "openai": {"model": "gpt-3.5-turbo", "temperature": 0.0},
        },
        "orchestration": {
            "deepseek": {"model": "deepseek-flash", "temperature": 0.0},
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
    def is_available(cls, settings: Optional[Settings] = None) -> bool:
        """配置里有没有一个**能用**的 provider —— **不构造客户端**。

        给"要不要走那条依赖 LLM 的可选路径"这种判断用（目前只有 debug 的
        Phase 6）。判据与 `create_llm` 的降级链**同源**（主 provider → fallback），
        但只做静态检查：

          · `api_key` 有没有 —— `create_llm` 在进 provider 循环**之前**就查它
          · `custom` 有没有 `base_url` —— `_create_for_provider` 里它缺就抛
          · `anthropic` 那个额外包装没装 —— 没装的话必然 ImportError

        **别改成"试着建一个客户端"** —— 那正是这次要替掉的东西：为了判一个布尔值，
        构造了一个完整的 `ChatOpenAI`（pydantic 校验 + 取 key + 挂 token 回调），
        而它一次 `invoke` 都不会有（真正的调用全走 `lib/llm_call.call_llm`）。
        """
        import importlib.util

        cfg = (settings or Settings.get_instance()).llm
        if not cfg.api_key:
            return False

        providers = [cfg.provider]
        fallback = getattr(cfg, "fallback_provider", None)
        if fallback and fallback != cfg.provider:
            providers.append(fallback)

        for provider in providers:
            if provider in (PROVIDER_DEEPSEEK, PROVIDER_OPENAI):
                return True
            if provider == PROVIDER_ANTHROPIC:
                try:
                    if importlib.util.find_spec("langchain_anthropic") is not None:
                        return True
                except (ImportError, ValueError):
                    pass                      # 包不存在 —— find_spec 也可能抛
            if provider == PROVIDER_CUSTOM and cfg.base_url:
                return True
        return False

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
        if settings is None:
            settings = Settings.get_instance()

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