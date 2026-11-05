"""工具注册表启动期护栏 —— 空映射 = 声明不用，**不是**忘配。"""
from __future__ import annotations

import pytest

from src.layers.l2_orchestration.communication.tool_hub import (
    ToolHub,
    ToolRegistryError,
)


def test_current_registry_is_valid_and_covers_all_executors():
    summary = ToolHub.validate_registry()
    assert set(summary) == {"front", "design", "model", "verify",
                            "ops", "coverage", "debug", "audit"}
    assert summary["verify"] == ("uvm", "assert")
    assert summary["front"] == ()
    assert ToolHub.EXECUTORS_WITHOUT_HUB_TOOLS == {"front", "model", "audit"}


def test_summary_is_one_stderr_friendly_line():
    line = ToolHub.format_registry_summary()
    assert line.startswith("[tool-registry] ")
    assert "front=none" in line
    assert "verify=uvm+assert" in line
    assert line.count("=") == 8


def test_empty_mapping_not_declared_is_a_startup_error(monkeypatch):
    monkeypatch.setattr(ToolHub, "EXECUTOR_TOOL_MODULES", {
        "front": (), "design": ("spec",), "model": (), "verify": ("uvm",),
        "ops": ("ops",), "coverage": (), "debug": ("debug",), "audit": (),
    })
    with pytest.raises(ToolRegistryError, match="coverage"):
        ToolHub.validate_registry()


def test_missing_executor_role_is_a_startup_error(monkeypatch):
    monkeypatch.setattr(ToolHub, "EXECUTOR_TOOL_MODULES", {
        "front": (), "design": ("spec",), "model": (), "verify": ("uvm",),
        "ops": ("ops",), "debug": ("debug",), "audit": (),
    })
    with pytest.raises(ToolRegistryError, match="缺少 executor 角色"):
        ToolHub.validate_registry()


def test_declared_no_tool_roles_are_allowed(monkeypatch):
    monkeypatch.setattr(ToolHub, "EXECUTOR_TOOL_MODULES", {
        "front": (), "design": ("spec",), "model": (), "verify": ("uvm",),
        "ops": ("ops",), "coverage": ("coverage",), "debug": ("debug",),
        "audit": (),
    })
    summary = ToolHub.validate_registry()
    assert summary["front"] == () and summary["audit"] == ()
