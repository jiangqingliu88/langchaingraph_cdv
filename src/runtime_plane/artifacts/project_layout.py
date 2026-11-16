"""兼容入口：ChipStack 工程目录契约（实现位于 `runtime_plane.core.project_layout`）。

放在 core 的原因：`runtime_plane/infrastructure/output_config.py`（L1）需要把
默认输出根路由到 L4；架构 Guard 只允许 L1 → core，不允许 L1 → runtime。
本文件保留既有的 `runtime_plane.artifacts.project_layout` import 路径，
常量（`COMPILE_CONFIG_NAME` 等）通过 PEP 562 `__getattr__` 透传。
"""
from __future__ import annotations

from typing import Any

from src.runtime_plane.core import project_layout as _impl
from src.runtime_plane.core.project_layout import *  # noqa: F401,F403

__all__ = list(_impl.__all__)


def __getattr__(name: str) -> Any:
    return getattr(_impl, name)
