"""Agent capability registry —— 每个专家能做什么、能用什么、能重试几次。

这是工业级 agentic 的“工牌/权限表”：
  · `stages` 决定该 agent 可以调用哪些阶段能力；
  · `tools` 是低层工具白名单（与 ToolHub 的角色映射互为补充）；
  · `max_attempts` / `requires_human_after` 是子图循环的硬上限；
  · `write_scope` 是沙箱写权限的声明，运行期由具体 stage/tool 再校验。

`Executor` 仍然保留为实现类名；agent 侧统一用 `stages`（阶段执行器），
避免和 Claude Code 的 skill 概念混淆。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 能力名（不是目录名）。Stage 执行器已按职责迁到 generation/engine，
#: 因此这里用固定集合校验 AgentCard，不再扫描文件系统。
KNOWN_STAGES = frozenset(
    {
        "front",
        "design",
        "model",
        "verify",
        "ops",
        "coverage",
        "debug",
        "audit",
    }
)


@dataclass(frozen=True)
class AgentCard:
    name: str
    description: str
    stages: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    max_attempts: int = 1
    requires_human_after: int = 0
    write_scope: tuple[str, ...] = ()
    #: 独立专家：走自己的 CLI/服务入口，不在 supervisor 主图的阶段链里。
    standalone: bool = False
    #: 这些 Domain/loop 仅用于角色元数据，不新增架构职责平面。
    domain: str = ""
    loop_protocol: str = "legacy"


AGENT_CARDS: dict[str, AgentCard] = {
    "supervisor": AgentCard(
        "supervisor",
        "只路由，不执行 EDA/LLM",
        max_attempts=24,
    ),
    "design": AgentCard(
        "design",
        "前置分析、设计、参考模型",
        stages=("front", "design", "model"),
        tools=("spec_tools", "read_file", "write_file", "check_static"),
        max_attempts=2,
        write_scope=("rtl/",),
    ),
    "verify": AgentCard(
        "verify",
        "UVM 环境、测试点、约束与覆盖率计划",
        stages=("verify",),
        tools=("find_spec_yaml", "jinja_render", "check_static", "read_file", "write_file"),
        max_attempts=2,
        write_scope=("agents/", "env/", "sv/", "coverage/"),
    ),
    "debug": AgentCard(
        "debug",
        "日志诊断、定位、修复、重跑",
        stages=("ops", "debug"),
        tools=("collect_sim_log", "collect_compile_log", "auto_fix", "rerun_failed_test", "fingerprint_error"),
        max_attempts=5,
        requires_human_after=5,
        write_scope=("rtl/", "tb/", "env/"),
    ),
    "coverage": AgentCard(
        "coverage",
        "覆盖率收集、gap 分析、定向建议",
        stages=("coverage",),
        tools=("read_coverage", "list_coverage_files", "write_note"),
        max_attempts=6,
        write_scope=("coverage/",),
    ),
    # ── 独立专家（不在 supervisor 阶段链里，走自己的 CLI/服务入口）──
    "mental": AgentCard(
        "mental",
        "心智模型 IR：目标/假设/歧义/验证意图/风险",
        max_attempts=1,
        write_scope=("mental_ir/",),
        standalone=True,
    ),
    "formal": AgentCard(
        "formal",
        "形式化验证计划（生成 Formal IR；无引擎时 engine.ran=false）",
        max_attempts=1,
        write_scope=("formal/",),
        standalone=True,
    ),
    "unit_test": AgentCard(
        "unit_test",
        "纯 SV 单测 testbench 生成 + 编译/运行",
        max_attempts=1,
        write_scope=("unit_test/",),
        standalone=True,
    ),
}


def _specialist_cards() -> dict[str, AgentCard]:
    """每个独立角色一张卡；旧专家工厂与新角色元数据共存。"""
    from src.agent_plane.reaction.registry import role_metadata

    cards = {}
    for spec in role_metadata():
        role = spec["role_id"]
        cards[role] = AgentCard(
            name=role,
            description=spec["responsibility"],
            tools=tuple(spec["allowed_tools"]),
            max_attempts=spec["max_steps"],
            requires_human_after=1 if spec["write_allowed"] else 0,
            write_scope=(f"review_bundle/agents/{role}/",) if spec["write_allowed"] else (),
            standalone=True,
            domain=spec["domain"],
            loop_protocol="openai_agents_react",
        )
    return cards


SPECIALIST_CARDS = _specialist_cards()


def card(agent: str) -> AgentCard:
    from src.agent_plane.reaction.registry import canonical_role

    role = canonical_role(agent)
    if role in SPECIALIST_CARDS:
        return SPECIALIST_CARDS[role]
    try:
        return AGENT_CARDS[agent]
    except KeyError as exc:
        raise KeyError(f"未登记的 agent: {agent!r}") from exc


def validate_registry() -> list[str]:
    """校验 agent card 的能力名；返回问题列表（空=通过）。"""
    issues: list[str] = []
    for name, c in dict(AGENT_CARDS, **SPECIALIST_CARDS).items():
        if c.name != name:
            issues.append(f"card key {name!r} != card.name {c.name!r}")
        for stage in c.stages:
            if stage not in KNOWN_STAGES:
                issues.append(f"{name}: 未登记 stage {stage!r}")
        if c.max_attempts <= 0:
            issues.append(f"{name}: max_attempts 必须 > 0")
    return issues


__all__ = ["AgentCard", "AGENT_CARDS", "SPECIALIST_CARDS", "card", "validate_registry"]
