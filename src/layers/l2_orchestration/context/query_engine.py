"""
集中式 LLM Query Engine —— 统一管理 LLM 调用的横切关注点。

借鉴 claw-code 的 query_engine.py：把 LLM 调用从各 Agent 抽离，收敛到一个
引擎里管理 token 预算、响应缓存、超时重试、provider 降级、审计追踪。

IC 验证对 LLM 可靠性的要求比通用写代码高得多——一个仿真跑 10 分钟，LLM
半路超时/换 provider 不该让它白跑。本引擎让"LLM 做完形填空"可预算、可预测。

用法:
    from src.layers.l2_orchestration.context.query_engine import LLMQueryEngine
    qe = LLMQueryEngine.get_instance()
    content = qe.query("code_generation", [{"role": "system", ...}, {"role": "user", ...}])
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


class LLMQueryEngine:
    """集中式 LLM 查询引擎（单例）。"""

    _instance: Optional["LLMQueryEngine"] = None

    def __init__(self, token_budget: int = 200_000, cache_enabled: bool = True):
        self.token_budget = token_budget
        self.tokens_used = 0
        self.cache_enabled = cache_enabled
        self.cache: Dict[str, str] = {}          # prompt_hash → response
        self.audit_log: List[Dict[str, Any]] = []  # 调用审计

    @classmethod
    def get_instance(cls) -> "LLMQueryEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ═══════════════════════════════════════════════════════════
    # 核心查询入口
    # ═══════════════════════════════════════════════════════════

    def query(self, task_type: str, messages: List[Dict[str, str]],
              cache_key: str = "", max_retries: int = 2,
              timeout_s: int = 120) -> str:
        """统一查询：预算检查 → 缓存 → 调用（重试/降级）→ 审计。

        Args:
            task_type: 任务类型（code_generation / debug_analysis / ...）
            messages: 消息列表 [{role, content}]
            cache_key: 缓存键（相同 key 命中缓存，空则用 messages 哈希）
            max_retries: 调用重试次数
            timeout_s: 单次超时

        Returns:
            LLM 返回文本；预算超限或全部失败时返回空字符串。
        """
        prompt_str = json.dumps(messages, ensure_ascii=False, sort_keys=True)
        key = cache_key or self._hash(prompt_str)

        # 1. token 预算检查（合并 LLMTracerCallback 的全局真实用量，覆盖 LangChain 直调路径）
        current_tokens = self._current_tokens()
        if current_tokens >= self.token_budget:
            logger.warning(f"LLM token 预算超限: {current_tokens}/{self.token_budget}，拒绝调用")
            self._audit(task_type, key, "", "budget_exceeded", 0.0)
            return ""

        # 2. 响应缓存
        if self.cache_enabled and key in self.cache:
            self._audit(task_type, key, self.cache[key][:100], "cache_hit", 0.0)
            return self.cache[key]

        # 3. LLM 调用（重试 + provider 降级）
        content, elapsed, tokens = self._invoke_with_fallback(
            task_type, messages, max_retries, timeout_s)

        # 4. 记账 + 缓存 + 审计
        if tokens:
            self.tokens_used += tokens
        if content and self.cache_enabled:
            self.cache[key] = content
        self._audit(task_type, key, content[:100] if content else "", "ok" if content else "failed", elapsed)
        return content

    # ═══════════════════════════════════════════════════════════
    # 内部：调用 + 降级
    # ═══════════════════════════════════════════════════════════

    def _invoke_with_fallback(self, task_type: str, messages: List[Dict[str, str]],
                              max_retries: int, timeout_s: int):
        """调用 LLM，失败时 provider 降级（由 LLMFactory 的 fallback 链兜底）。"""
        from src.layers.l2_orchestration.context.llm_factory import LLMFactory, LLMTracerCallback
        content, tokens = "", 0
        t0 = time.time()
        try:
            llm = LLMFactory.create_for_task(task_type)
            for attempt in range(max_retries + 1):
                try:
                    resp = llm.invoke(messages)
                    content = resp.content if hasattr(resp, "content") else str(resp)
                    tokens = (resp.response_metadata.get("token_usage", {}).get("total_tokens", 0)
                              if hasattr(resp, "response_metadata") else 0)
                    if content:
                        break
                except Exception as e:
                    logger.warning(f"LLM 调用失败(attempt {attempt+1}): {e}")
                    if attempt >= max_retries:
                        break
                    time.sleep(1.0 * (attempt + 1))  # 简单退避
        except Exception as e:
            logger.warning(f"LLM 引擎调用失败: {e}")
        return content, round(time.time() - t0, 2), tokens

    # ═══════════════════════════════════════════════════════════
    # 预算 / 缓存 / 审计
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _hash(s: str) -> str:
        return hashlib.sha256(s.encode()).hexdigest()[:16]

    def _current_tokens(self) -> int:
        """合并全局 token 用量（LLMTracerCallback 追踪所有 LangChain 直调）。"""
        try:
            from src.layers.l2_orchestration.context.llm_factory import LLMTracerCallback
            return max(self.tokens_used, LLMTracerCallback.total_tokens_used)
        except Exception:
            return self.tokens_used

    def _audit(self, task_type: str, key: str, resp_preview: str,
               status: str, elapsed: float):
        self.audit_log.append({
            "task_type": task_type, "cache_key": key,
            "status": status, "elapsed_s": elapsed,
            "resp_preview": resp_preview,
            "tokens_used_so_far": self.tokens_used,
        })
        # 只保留最近 500 条
        if len(self.audit_log) > 500:
            self.audit_log = self.audit_log[-500:]

    def get_budget_status(self) -> dict:
        return {"tokens_used": self.tokens_used, "budget": self.token_budget,
                "remaining": max(0, self.token_budget - self.tokens_used),
                "cache_hits": sum(1 for a in self.audit_log if a["status"] == "cache_hit"),
                "calls": len(self.audit_log)}

    def reset(self):
        """新 run 时重置（缓存保留可跨 run 复用，预算/审计清零）。"""
        self.tokens_used = 0
        self.audit_log = []
