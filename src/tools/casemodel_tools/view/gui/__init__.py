"""tkinter 分析界面。

为什么是 tkinter 而不是 Web UI：CLAUDE.md 明确禁止 Web 前端开发。
tkinter 是标准库、零新增依赖，符合「个人级 CLI 工具」的定位。

界面本身不含任何分析逻辑 —— 它只是 analysis.AnalysisResult 的一层视图，
所有判断都落在 analysis/ 里，可脱离 GUI 单独测试。
"""
from __future__ import annotations

from .app import CaseModelApp, main

__all__ = ["CaseModelApp", "main"]
