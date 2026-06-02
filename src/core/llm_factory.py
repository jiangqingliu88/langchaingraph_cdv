"""
LLM工厂 - 支持多种LLM提供商
使用工厂模式创建LLM实例
"""
from typing import Optional, Dict, Any, Literal
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
import structlog

from config.settings import Settings

logger = structlog.get_logger()

class LLMFactory:
    """
    LLM工厂类
    根据配置创建对应的LLM实例
    
    支持的提供商:
    - deepseek: DeepSeek API (兼容OpenAI格式)
    - openai: OpenAI API
    - custom: 自定义兼容OpenAI API的服务
    """
    
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
        
        # 根据提供商创建
        if llm_config.provider == "deepseek":
            return cls._create_deepseek(
                api_key=api_key,
                model=selected_model,
                temperature=selected_temperature,
                max_tokens=selected_max_tokens,
                request_timeout=request_timeout,
                max_retries=max_retries,
                base_url=base_url or "https://api.deepseek.com/v1"
            )
        elif llm_config.provider == "openai":
            return cls._create_openai(
                api_key=api_key,
                model=selected_model,
                temperature=selected_temperature,
                max_tokens=selected_max_tokens,
                request_timeout=request_timeout,
                max_retries=max_retries,
                base_url=base_url
            )
        else:
            return cls._create_custom(
                api_key=api_key,
                model=selected_model,
                temperature=selected_temperature,
                max_tokens=selected_max_tokens,
                request_timeout=request_timeout,
                max_retries=max_retries,
                base_url=base_url
            )
    
    @classmethod
    def _create_deepseek(
        cls,
        api_key: str,
        model: str,
        temperature: float,
        max_tokens: int,
        request_timeout: int,
        max_retries: int,
        base_url: str = "https://api.deepseek.com/v1"
    ) -> ChatOpenAI:
        """创建DeepSeek LLM实例"""
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=request_timeout,
            max_retries=max_retries,
            # DeepSeek不支持所有OpenAI参数，保持简洁
            model_kwargs={}
        )
    
    @classmethod
    def _create_openai(
        cls,
        api_key: str,
        model: str,
        temperature: float,
        max_tokens: int,
        request_timeout: int,
        max_retries: int,
        base_url: Optional[str] = None
    ) -> ChatOpenAI:
        """创建OpenAI LLM实例"""
        kwargs = {
            "model": model,
            "api_key": api_key,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "request_timeout": request_timeout,
            "max_retries": max_retries,
        }
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)
    
    @classmethod
    def _create_custom(
        cls,
        api_key: str,
        model: str,
        temperature: float,
        max_tokens: int,
        request_timeout: int,
        max_retries: int,
        base_url: Optional[str] = None
    ) -> ChatOpenAI:
        """创建自定义LLM实例"""
        if not base_url:
            raise ValueError("自定义LLM需要提供base_url")
        
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=request_timeout,
            max_retries=max_retries,
        )
    
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