"""Staging —— 通用循环的地盘：可写、可跑、可丢弃。"""
from .tools import SandboxTools

__all__ = ["SandboxLoop", "SandboxTools"]


def __getattr__(name):
    # `SandboxLoop` 是 harness 的兼容门面；harness 自身要 import `staging.tools`，
    # 这里不能 eager import loop（否则包初始化成环）。
    if name == "SandboxLoop":
        from .loop import SandboxLoop
        return SandboxLoop
    raise AttributeError(name)
