"""LLM 候选分析到 Temporal IR 的受控适配点。

不规定模型如何实现抽取，但规定输出形状和证据责任：必须由原文锚点、
显式信号角色和规则参数组成，不能把模型自称认定为 CONFIRMED。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from collections.abc import Callable

from src.ir_plane.interface_timing import TimingContractError, temporal_from_dict


class TemporalCandidateExtractor:
    def __init__(self, analyzer: Callable[[str], dict[str, Any]] | None = None) -> None:
        self._analyzer = analyzer

    def extract(self, excerpt: str) -> dict[str, Any]:
        if self._analyzer is None:
            raise TimingContractError("未配置 analyzer；不会把文本自动猜成已验证时序")
        result = self._analyzer(excerpt)
        if not isinstance(result, dict):
            raise TimingContractError("接口分析结果必须是结构化对象")
        candidate = deepcopy(result)
        candidate["status"] = "DERIVED"
        for signal in candidate.get("signals") or []:
            signal["binding_status"] = "DERIVED"
        for rule in candidate.get("rules") or []:
            if not rule.get("anchor"):
                raise TimingContractError("候选规则缺少 quote/locator/行号/sha256")
            rule["status"] = "DERIVED"
        # 这行只做形状检查；真正的来源一致性、RTL 绑定仍由 Engine 复核。
        temporal_from_dict(candidate)
        return candidate


__all__ = ["TemporalCandidateExtractor"]
