"""Deterministic Engine facade (Architecture 4.0).

Engine 本身不 import Interfaces；facade 用惰性属性转发，避免形成静态依赖。
"""
from __future__ import annotations

import importlib

_LAZY = {
    "run_soc_project": ("src.workbench.api.soc_service", "run_soc_project"),
    "run_verify": ("src.workbench.api.verify_service", "run_verify"),
    "run_verify_async": ("src.workbench.api.verify_service", "run_verify_async"),
    "run_goal": ("src.workbench.modes.verify_mode", "run_goal"),
    "load_project": ("src.ir_plane.vplan", "load_project"),
    "evaluate": ("src.ir_plane.vplan", "evaluate"),
    "link_run": ("src.ir_plane.vplan", "link_run"),
    "apply_active": ("src.ir_plane.vplan", "apply_active"),
}

__all__ = list(_LAZY)


def __getattr__(name: str):
    if name in _LAZY:
        module, attr = _LAZY[name]
        return getattr(importlib.import_module(module), attr)
    raise AttributeError(name)
