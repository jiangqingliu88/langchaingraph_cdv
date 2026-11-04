"""检查板块 —— 只读/判定类工具（断言、debug、覆盖率分析、spec 校验）。"""
from __future__ import annotations

import importlib

PACKAGES = ("assertion_tools",
            # Verification OS v3：契约 / 义务 / 事实账本 / 推导（M0 影子模式）
            "verification_os")


def __getattr__(name: str):
    if name in PACKAGES:
        return importlib.import_module(f"src.tools.checking.{name}")
    raise AttributeError(name)


__all__ = list(PACKAGES)
