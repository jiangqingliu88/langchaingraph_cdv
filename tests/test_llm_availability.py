"""LLM 可用性探测 —— 一个布尔值，但判错了两头都疼。

这个探测的**唯一消费者**是"执行器要不要走那条依赖 LLM 的可选增强路径"
（目前只有 debug 的 Phase 6）。所以：

  · 判成 True 而实际不可用 → 走到那儿才炸，或者在无 key 的环境里空转
  · 判成 False 而实际可用   → **静默跳过 LLM 增强**，看起来"这轮没什么要分析的"

第二种更坏：它不是报错，是"少做了一件事而没人知道"。

判据必须与 `LLMFactory.create_llm` 的降级链**同源**（主 provider → fallback），
否则会出现"探测说能，真去建客户端时抛"这种自相矛盾 —— 本文件的重点就是钉住这条。
"""
from __future__ import annotations

import pytest

from src.layers.l2_orchestration.context.llm_factory import LLMFactory


class _Cfg:
    """一个够用的 `settings.llm` 替身（只带 `is_available` 会读的那几个字段）。"""

    def __init__(self, **kw):
        self.provider = kw.get("provider", "deepseek")
        self.api_key = kw.get("api_key", "sk-test")
        self.base_url = kw.get("base_url", "https://api.deepseek.com/v1")
        self.model = "deepseek-flash"
        self.temperature = 0.0
        self.max_tokens = 4096
        if "fallback_provider" in kw:
            self.fallback_provider = kw["fallback_provider"]


class _Settings:
    def __init__(self, **kw):
        self.llm = _Cfg(**kw)


def available(**kw) -> bool:
    return LLMFactory.is_available(settings=_Settings(**kw))


class TestMatchesCreateLlm:
    """探测结果必须与"真去建客户端会不会成功"一致。"""

    def test_a_configured_provider_is_available(self):
        assert available(provider="deepseek", api_key="sk-x") is True

    def test_no_api_key_is_not_available(self):
        """`create_llm` 在进 provider 循环**之前**就查 api_key —— 探测要跟上。"""
        assert available(api_key="") is False

    def test_anthropic_needs_its_extra_package(self):
        """`langchain_anthropic` 没装 → 建客户端必然 ImportError。

        本仓的 requirements 里**没有**它（这是有意的：主链路走 OpenAI 兼容接口）。
        所以选 anthropic 且没有 fallback 时，探测必须说"不可用"，
        而不是"配置里写了 anthropic 就算数"。
        """
        import importlib.util

        installed = importlib.util.find_spec("langchain_anthropic") is not None
        assert available(provider="anthropic") is installed, (
            "anthropic 的可用性没有跟着那个包的实际安装状态走")

    def test_custom_needs_a_base_url(self):
        """`custom` 缺 base_url 时 `_create_for_provider` 直接抛。"""
        assert available(provider="custom", base_url="") is False
        assert available(provider="custom",
                         base_url="http://localhost:11434/v1") is True


class TestFallbackChain:
    """探测读的是**整条降级链**，不是只看主 provider。"""

    def test_a_usable_fallback_makes_it_available(self):
        """主 provider 不可用、fallback 可用 → 整体可用。

        这正是 `create_llm` 的行为：它逐个 try，全失败才抛。探测只看主 provider
        的话，会把"其实能用 fallback"误判成不可用 —— 那就是静默跳过 LLM 增强。
        """
        assert available(provider="anthropic",  # 包没装，主 provider 不可用
                         fallback_provider="deepseek") is True

    def test_fallback_equal_to_main_is_not_double_counted(self):
        assert available(provider="anthropic",
                         fallback_provider="anthropic") is False

    def test_both_unusable_is_unavailable(self):
        assert available(provider="anthropic",
                         fallback_provider="custom", base_url="") is False


class TestItDoesNotBuildAClient:
    """这是这次改动的**全部意义**：判一个布尔不该构造一个客户端。"""

    def test_no_client_is_constructed(self, monkeypatch):
        """探测期间 `ChatOpenAI` 一次都不该被构造。

        改之前是 `self.llm = LLMFactory.create_for_task(...)` —— 每个执行器初始化
        时建一个完整客户端（pydantic 校验 + 取 key + 挂 token 回调），
        而它一次 `invoke` 都不会有（真正的调用全走 `lib/llm_call.call_llm`）。
        """
        import src.layers.l2_orchestration.context.llm_factory as m

        built = []
        monkeypatch.setattr(m.LLMFactory, "_create_openai_compat",
                            lambda **kw: built.append(kw) or object())

        LLMFactory.is_available(settings=_Settings(provider="deepseek"))
        assert built == [], f"探测期间构造了客户端：{built}"

        # 对照组：真去建的时候确实会构造 —— 否则上面那条断言是空的
        # （monkeypatch 生效、`create_llm` 确实会走到这一层，两件事一起验）
        LLMFactory.create_llm(settings=_Settings(provider="deepseek"))
        assert built, "对照组没构造客户端 —— 上面的断言等于没测"
