"""Agent capability registry —— 每个专家能做什么、能用什么、能重试几次。

这是工业级 agentic 的“工牌/权限表”：
  · `skills` 决定该 agent 可以调用哪些阶段能力；
  · `tools` 是低层工具白名单（与 ToolHub 的角色映射互为补充）；
  · `max_attempts` / `requires_human_after` 是子图循环的硬上限；
  · `write_scope` 是沙箱写权限的声明，运行期由具体 skill/tool 再校验。

`Executor` 仍然保留为 Skill 的实现类名（见 docs/AGENT_GLOSSARY.md），
但 agent 侧统一用 `skills` 这个词。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

_SKILL_ROOT = Path(__file__).resolve().parent.parent / "skills"


@dataclass(frozen=True)
class AgentCard:
    name: str
    description: str
    skills: Tuple[str, ...] = ()
    tools: Tuple[str, ...] = ()
    max_attempts: int = 1
    requires_human_after: int = 0
    write_scope: Tuple[str, ...] = ()


AGENT_CARDS: Dict[str, AgentCard] = {
    "supervisor": AgentCard(
        "supervisor", "只路由，不执行 EDA/LLM",
        max_attempts=24,
    ),
    "design": AgentCard(
        "design", "前置分析、设计、参考模型",
        skills=("front", "design", "model"),
        tools=("spec_tools", "read_file", "write_file", "check_static"),
        max_attempts=2,
        write_scope=("rtl/",),
    ),
    "verify": AgentCard(
        "verify", "UVM 环境、测试点、约束与覆盖率计划",
        skills=("verify",),
        tools=("find_spec_yaml", "jinja_render", "check_static",
               "read_file", "write_file"),
        max_attempts=2,
        write_scope=("agents/", "env/", "sv/", "coverage/"),
    ),
    "debug": AgentCard(
        "debug", "日志诊断、定位、修复、重跑",
        skills=("ops", "debug"),
        tools=("collect_sim_log", "collect_compile_log", "auto_fix",
               "rerun_failed_test", "fingerprint_error"),
        max_attempts=5,
        requires_human_after=5,
        write_scope=("rtl/", "tb/", "env/"),
    ),
    "coverage": AgentCard(
        "coverage", "覆盖率收集、gap 分析、定向建议",
        skills=("coverage",),
        tools=("read_coverage", "list_coverage_files", "write_note"),
        max_attempts=6,
        write_scope=("coverage/",),
    ),
}


def card(agent: str) -> AgentCard:
    try:
        return AGENT_CARDS[agent]
    except KeyError as exc:
        raise KeyError(f"未登记的 agent: {agent!r}") from exc


def validate_registry() -> list[str]:
    """校验 agent card 与真实 skill 目录一致；返回问题列表（空=通过）。"""
    issues: list[str] = []
    known = {p.name for p in _SKILL_ROOT.iterdir() if p.is_dir()} \
        if _SKILL_ROOT.is_dir() else set()
    for name, c in AGENT_CARDS.items():
        if c.name != name:
            issues.append(f"card key {name!r} != card.name {c.name!r}")
        for skill in c.skills:
            if skill not in known:
                issues.append(f"{name}: 未找到 skill {skill!r}")
        if c.max_attempts <= 0:
            issues.append(f"{name}: max_attempts 必须 > 0")
    return issues


__all__ = ["AgentCard", "AGENT_CARDS", "card", "validate_registry"]
