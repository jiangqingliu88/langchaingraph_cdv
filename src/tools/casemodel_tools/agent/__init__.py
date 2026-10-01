"""Agent 接入层 —— 三个面共用 adapters 的实现。

    adapters.py         语义（吃 YAML 文本、吐 dict）
    registry.py         声明式 ToolRegistry + ToolHub 的 ITool
    langchain_tools.py  LangChain @tool 外壳

三面共用同一批工具名与同一份实现，所以不会各给一个答案（有测试固定这点）。
本层是唯一允许同时 import domain / repository / analysis 的地方 ——
它就是那个「把工具能力接到 Agent 框架上」的适配器。
"""
from __future__ import annotations

from .adapters import (RUNNERS, TOOL_GAPS, TOOL_GENERATE, TOOL_NAMES,
                       TOOL_VALIDATE, run_gaps, run_generate, run_validate)

__all__ = [
    "TOOL_VALIDATE", "TOOL_GAPS", "TOOL_GENERATE", "TOOL_NAMES", "RUNNERS",
    "run_validate", "run_gaps", "run_generate",
]
