"""Agent Registry 1.0 — 角色、职责、授权任务、预算。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    tasks: Tuple[str, ...]
    modules: Tuple[str, ...] = ()
    max_attempts: int = 2
    can_write: bool = False


AGENTS: Dict[str, AgentSpec] = {
    "requirement": AgentSpec(
        "requirement", "理解 spec/RTL，产出 Verification Intent",
        ("requirement_extraction",), ("spec",), 2),
    "architecture": AgentSpec(
        "architecture", "分析模块/接口/资源，产出 Design IR",
        ("architecture_analysis",), ("spec",), 2),
    "planning": AgentSpec(
        "planning", "制定验证策略，产出 objectives/scenarios",
        ("planning",), ("vplan",), 2),
    "uvm": AgentSpec(
        "uvm", "生成 UVM agent/env/sequence/scoreboard",
        ("uvm_generation",), ("uvm",), 3, can_write=True),
    "formal": AgentSpec(
        "formal", "生成 SVA/formal properties",
        ("formal_generation",), ("sva",), 2, can_write=True),
    "regression": AgentSpec(
        "regression", "构建、执行、调度回归",
        ("regression",), ("regression",), 2),
    "debug": AgentSpec(
        "debug", "失败归因、定位、修复建议",
        ("debug",), ("debug",), 5),
    "coverage": AgentSpec(
        "coverage", "覆盖缺口分析、补测策略",
        ("coverage_analysis",), ("coverage",), 6),
    "repair": AgentSpec(
        "repair", "提出代码/测试修复 patch proposal",
        ("repair",), ("repair",), 3, can_write=True),
    "signoff": AgentSpec(
        "signoff", "整理签核材料，提交 deterministic gate",
        ("signoff",), ("audit",), 1),
}


def get_agent(name: str) -> AgentSpec:
    if name not in AGENTS:
        raise KeyError(f"unknown agent: {name!r}")
    return AGENTS[name]
