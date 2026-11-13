"""Agent 的规格分析适配器：提取/发现歧义，但只能返回候选。

由现有 Agent/LLM 注入 analyzer callable；本模块自己不声明新的 Agent 类型，
也不把其文本推断当成正式 CONFIRMED 规范。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from src.ir_plane.specification_compiler import SpecSchemaError, SpecStatus


class SpecificationAnalyst:
    def __init__(self, analyzer: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> None:
        self._analyzer = analyzer

    def analyze(self, document: dict[str, Any]) -> dict[str, Any]:
        if self._analyzer is None:
            raise SpecSchemaError("未配置现有 Agent/LLM analyzer；不会自动编造规格事实")
        result = self._analyzer(deepcopy(document))
        if not isinstance(result, dict):
            raise SpecSchemaError("Agent 规格分析必须返回结构化对象")
        requirements = []
        for index, item in enumerate(result.get("requirements") or []):
            if not isinstance(item, dict):
                raise SpecSchemaError("Agent requirement 必须是对象")
            value = deepcopy(item)
            value["status"] = SpecStatus.DERIVED.value
            value.setdefault("requirement_id", f"CAND-{index + 1}")
            value.setdefault("rationale", "Agent 提取/推导，等待确定性检查或人工确认")
            requirements.append(value)
        return {
            "requirements": requirements,
            "gaps": deepcopy(result.get("gaps") or []),
            "conflicts": deepcopy(result.get("conflicts") or []),
            "producer": "agent_analysis",
            "normative": False,
        }


__all__ = ["SpecificationAnalyst"]
