"""共享底层 —— `lib/` 的稳定入口（哈希、日志、覆盖率采集、LLM 漏斗等）。"""
from __future__ import annotations

import importlib


def __getattr__(name: str):
    if name == "lib":
        return importlib.import_module("src.tools.common.lib")
    raise AttributeError(name)


__all__ = ["lib"]
