"""五个 Agent Domain 的权威注册表。

Agent Plane 按 `design_understanding / design_verification / verification /
design_signoff / design_generation` 组织，本模块把它们与
`runtime_plane.artifacts.project_layout` 的**固定产物子目录**（R-020）钉在一起：

    design_understanding   mental_model_agent
    design_verification    simulation_agent
    verification           test_plan_agent / formal_agent /
                           functional_coverage_agent / uvm_agent / dv_debug
    design_signoff         lint_autofix
    design_generation      rtl_generation / rtl_early_estimation_agent

任何 GUI、CLI、编排节点想知道「这个 agent 的产物应该落在哪、属于哪个域」，
只查这里；不要再在各处手写目录名或 domain 字符串。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from src.runtime_plane.artifacts.project_layout import (
    ARTIFACT_DIRS_SPEC,
    agent_artifact_dir,
    safe_name,
)


@dataclass(frozen=True)
class AgentSpec:
    """一个 agent 角色在目录架构里的身份。"""

    agent_id: str
    domain: str
    title: str
    artifact_dir: str
    entrypoint: str = ""
    stage: str = ""
    aliases: Tuple[str, ...] = ()
    writes_rtl: bool = False
    cli_name: str = ""
    tui_mode: str = ""
    inputs: str = ""

    @property
    def writable_artifacts(self) -> bool:
        return self.writes_rtl

    def to_dict(self) -> Dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "domain": self.domain,
            "title": self.title,
            "artifact_dir": self.artifact_dir,
            "entrypoint": self.entrypoint,
            "stage": self.stage,
            "aliases": list(self.aliases),
            "writes_rtl": self.writes_rtl,
            "cli_name": self.cli_name,
            "tui_mode": self.tui_mode,
            "inputs": self.inputs,
        }


@dataclass(frozen=True)
class DomainSpec:
    """一个 Agent Domain（代码目录）及其 agent 清单。"""

    id: str
    title: str
    package: str
    description: str
    agents: Tuple[str, ...]

    def specs(self) -> List[AgentSpec]:
        return [AGENTS[agent_id] for agent_id in self.agents]

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "package": self.package,
            "description": self.description,
            "agents": [spec.to_dict() for spec in self.specs()],
        }


def _spec(agent_id: str, domain: str, title: str, *, artifact: str = "",
          entrypoint: str = "", stage: str = "", aliases: Iterable[str] = (),
          writes_rtl: bool = False, cli_name: str = "", tui_mode: str = "",
          inputs: str = "") -> AgentSpec:
    return AgentSpec(
        agent_id=agent_id,
        domain=domain,
        title=title,
        artifact_dir=artifact or agent_artifact_dir(agent_id),
        entrypoint=entrypoint,
        stage=stage,
        aliases=tuple(aliases),
        writes_rtl=writes_rtl,
        cli_name=cli_name,
        tui_mode=tui_mode,
        inputs=inputs,
    )


# ════════════════════════════════════════════════════════════════
# 五个域（顺序即 GUI 与文档里的顺序）
# ════════════════════════════════════════════════════════════════

DOMAINS: Dict[str, DomainSpec] = {
    "design_understanding": DomainSpec(
        id="design_understanding",
        title="设计理解",
        package="src.agent_plane.design_understanding",
        description="把 spec/RTL 变成可复核的共享心智模型，保留锚点与未知项。",
        agents=("mental_model_agent",),
    ),
    "design_verification": DomainSpec(
        id="design_verification",
        title="设计验证执行",
        package="src.agent_plane.design_verification",
        description="运行/采集仿真事实；不把未执行的仿真写成证据。",
        agents=("simulation_agent",),
    ),
    "verification": DomainSpec(
        id="verification",
        title="验证构建",
        package="src.agent_plane.verification",
        description="测试计划、形式、功能覆盖率、UVM 构建与失败调试。",
        agents=(
            "test_plan_agent",
            "formal_agent",
            "functional_coverage_agent",
            "uvm_coding_agent",
            "dv_debug_agent",
        ),
    ),
    "design_signoff": DomainSpec(
        id="design_signoff",
        title="设计签核",
        package="src.agent_plane.design_signoff",
        description="Lint 诊断与受控修复建议；未跑 lint 不宣称已清理。",
        agents=("lint_autofix",),
    ),
    "design_generation": DomainSpec(
        id="design_generation",
        title="设计生成",
        package="src.agent_plane.design_generation",
        description="RTL 早期估算与升级；修改 RTL 前必须留 backup。",
        agents=("rtl_early_estimation_agent", "rtl_upgrade_agent"),
    ),
}

AGENTS: Dict[str, AgentSpec] = {
    "mental_model_agent": _spec(
        "mental_model_agent", "design_understanding", "Mental Model Agent",
        entrypoint="src.agent_plane.design_understanding.mental_model_agent.agent:MentalModelAgent",
        stage="understand", cli_name="mental-model", tui_mode="mental_model",
        inputs="RTL + Spec",
    ),
    "simulation_agent": _spec(
        "simulation_agent", "design_verification", "Unit Testing (simulation-agent)",
        entrypoint="src.agent_plane.design_verification.simulation_agent.agent:SimulationAgent",
        stage="verify", cli_name="simulation-agent", tui_mode="unit_testing",
        inputs="RTL + Spec",
    ),
    "test_plan_agent": _spec(
        "test_plan_agent", "verification", "Test Plan Agent",
        entrypoint="src.agent_plane.verification.test_plan_agent.agent:TestPlanAgent",
        stage="plan", cli_name="uvm-agentic-flow", tui_mode="uvm",
        inputs="Spec (required)",
    ),
    "formal_agent": _spec(
        "formal_agent", "verification", "Formal Agent",
        entrypoint="src.agent_plane.verification.formal_agent.agent:FormalAgent",
        stage="verify", cli_name="formal-agent", tui_mode="formal",
        inputs="RTL (+ Spec)",
    ),
    "functional_coverage_agent": _spec(
        "functional_coverage_agent", "verification", "Functional Coverage Agent",
        entrypoint="src.agent_plane.verification.functional_coverage_agent.agent:FunctionalCoverageAgent",
        stage="coverage", cli_name="functional-coverage-agent", tui_mode="functional_coverage",
        inputs="RTL (+ Spec)",
    ),
    "uvm_coding_agent": _spec(
        "uvm_coding_agent", "verification", "UVM Coding Agent",
        artifact="uvm_agent",
        entrypoint="src.agent_plane.verification.uvm_coding_agent.agent:UVMCodingAgent",
        stage="build", cli_name="uvm-agentic-flow", tui_mode="uvm",
        aliases=("uvm_agent",), writes_rtl=True, inputs="UVM TB (can create)",
    ),
    "dv_debug_agent": _spec(
        "dv_debug_agent", "verification", "DV Debug Agent",
        artifact="dv_debug",
        entrypoint="src.agent_plane.verification.dv_debug_agent.agent:DVDebugAgent",
        stage="debug", cli_name="dv-debug-agent", tui_mode="debug",
        aliases=("dv_debug",), inputs="xcelium failure DB",
    ),
    "lint_autofix": _spec(
        "lint_autofix", "design_signoff", "Lint AutoFix",
        entrypoint="src.agent_plane.design_signoff.lint_autofix.agent:LintAutoFixAgent",
        stage="signoff", cli_name="lint-autofix-agent",
        writes_rtl=True, inputs="RTL + Spec",
    ),
    "rtl_early_estimation_agent": _spec(
        "rtl_early_estimation_agent", "design_generation", "RTL Early Estimation Agent",
        entrypoint="src.agent_plane.design_generation.rtl_early_estimation_agent.agent:RTLEarlyEstimationAgent",
        stage="plan", cli_name="rtl-early-estimation", inputs="RTL",
    ),
    "rtl_upgrade_agent": _spec(
        "rtl_upgrade_agent", "design_generation", "RTL Upgrade Agent",
        artifact="rtl_generation",
        entrypoint="src.agent_plane.design_generation.rtl_upgrade_agent.agent:RTLUpgradeAgent",
        stage="generate", cli_name="rtl-generation", tui_mode="rtl_designer",
        writes_rtl=True, inputs="RTL + Change Request",
    ),
}

#: 别名 → 权威 agent id
ALIASES: Dict[str, str] = {
    alias: spec.agent_id
    for spec in AGENTS.values()
    for alias in (spec.agent_id, *spec.aliases)
}


# ════════════════════════════════════════════════════════════════
# 查询
# ════════════════════════════════════════════════════════════════

def resolve_agent(agent_id: str) -> Optional[AgentSpec]:
    """接受 agent id 或别名；未知返回 None（不抛）。"""
    key = str(agent_id or "").strip()
    resolved = ALIASES.get(key)
    return AGENTS.get(resolved) if resolved else None


def agent_spec(agent_id: str) -> AgentSpec:
    spec = resolve_agent(agent_id)
    if spec is None:
        raise KeyError(f"未登记的 agent：{agent_id!r}")
    return spec


def domain_of(agent_id: str) -> str:
    spec = resolve_agent(agent_id)
    return spec.domain if spec else ""


def artifact_dir(agent_id: str) -> str:
    spec = resolve_agent(agent_id)
    return spec.artifact_dir if spec else agent_artifact_dir(safe_name(agent_id, default="agent"))


def agents_for(domain_id: str) -> List[AgentSpec]:
    domain = DOMAINS.get(domain_id)
    return domain.specs() if domain else []


def all_agents() -> List[AgentSpec]:
    return list(AGENTS.values())


def all_domains() -> List[DomainSpec]:
    return list(DOMAINS.values())


def expected_artifact_dirs() -> List[str]:
    """五个域会产出的目录（去重，保持稳定顺序）。"""
    seen: List[str] = []
    for spec in AGENTS.values():
        if spec.artifact_dir not in seen:
            seen.append(spec.artifact_dir)
    return seen


def missing_contract_dirs() -> List[str]:
    """R-020 的九目录里，没有被任何 agent 映射到的那些。"""
    mapped = set(expected_artifact_dirs())
    return [name for name in ARTIFACT_DIRS_SPEC if name not in mapped]


def create_agent(agent_id: str, **kwargs):
    """按注册表实例化 agent（entrypoint 为空的 agent 视为 artifact-only）。"""
    spec = agent_spec(agent_id)
    if not spec.entrypoint:
        raise NotImplementedError(f"{agent_id} 只有产物目录，没有 agent 实现")
    module_name, _, class_name = spec.entrypoint.partition(":")
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, class_name)(**kwargs)


def layout_rows(run=None) -> List[Dict[str, object]]:
    """GUI / CLI 的 agent 产物表：每个 agent 一行（目录存在与否 + status.json）。"""
    rows: List[Dict[str, object]] = []
    for spec in AGENTS.values():
        path = run.agent_dir(spec.agent_id) if run is not None else None
        status = ""
        reason = ""
        if path is not None and (path / "status.json").is_file():
            try:
                import json

                doc = json.loads((path / "status.json").read_text(encoding="utf-8"))
                status = str(doc.get("status") or "")
                reason = str(doc.get("reason") or "")
            except (OSError, ValueError):
                status = "UNREADABLE"
        rows.append({
            **spec.to_dict(),
            "path": str(path) if path is not None else "",
            "exists": bool(path is not None and path.is_dir()),
            "status": status,
            "reason": reason,
        })
    return rows


__all__ = [
    "AgentSpec",
    "DomainSpec",
    "DOMAINS",
    "AGENTS",
    "ALIASES",
    "resolve_agent",
    "agent_spec",
    "domain_of",
    "artifact_dir",
    "agents_for",
    "all_agents",
    "all_domains",
    "expected_artifact_dirs",
    "missing_contract_dirs",
    "create_agent",
    "layout_rows",
]
