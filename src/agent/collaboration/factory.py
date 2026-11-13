"""Agent Type definitions —— 专业能力定义，不是运行时实例。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from .contract import SubagentContract


@dataclass(frozen=True)
class AgentType:
    name: str
    description: str
    read_scope: Tuple[str, ...]
    write_scope: Tuple[str, ...]
    allowed_tools: Tuple[str, ...]
    constraints: Tuple[str, ...]
    deliverables: Tuple[str, ...]
    acceptance: Tuple[str, ...]
    max_steps: int = 10


_READ = ("read_file", "list_files", "search", "project_map",
         "read_project_file", "search_project", "read_playbook")
_READ_EVIDENCE = _READ + ("collect_evidence", "compare_evidence")
_READ_RESULT = _READ + ("write_file",)  # 工程只读；交付物只写子 Agent 工作区

AGENT_TYPES: Dict[str, AgentType] = {
    "spec_analyst": AgentType(
        "spec_analyst", "理解 spec、接口协议、寄存器、时序和验证意图",
        read_scope=("specs/", "docs/", "data/", "cases/"),
        write_scope=(), allowed_tools=_READ_RESULT,
        constraints=("工程只读分析", "交付物只写本子 Agent 工作区", "结论必须给出文件与行号", "不得宣布验证通过"),
        deliverables=("findings.json",),
        acceptance=("每个结论可追溯到文件/行号", "未知项显式列出"),
    ),
    "rtl_analyst": AgentType(
        "rtl_analyst", "分析 RTL 结构、信号驱动、状态机、资源关系与潜在 Bug",
        read_scope=("specs/", "rtl/", "data/", "sv/"),
        write_scope=(), allowed_tools=_READ_RESULT,
        constraints=("工程只读分析", "不得修改 RTL", "交付物只写本子 Agent 工作区", "每个问题有证据定位"),
        deliverables=("signal_inventory.json", "findings.json"),
        acceptance=("所有接口输出均有分析记录", "每个问题有证据定位"),
    ),
    "verification_designer": AgentType(
        "verification_designer", "设计 Test Plan / Testpoint / SVA / Scoreboard 策略",
        read_scope=("specs/", "data/", "docs/", "cases/", "rtl/"),
        write_scope=(".signoffai/subagents/",),
        allowed_tools=_READ + ("write_file", "str_replace"),
        constraints=("写只落子 Agent 工作区", "SVA 必须可执行、可编译"),
        deliverables=("plan.md", "testpoints.json", "assertions.json"),
        acceptance=("每条规则有信号/检查表达式", "覆盖所有接口组"),
    ),
    "uvm_engineer": AgentType(
        "uvm_engineer", "生成或修改 interface / agent / sequence / env / test",
        read_scope=("specs/", "data/", "sv/", "rtl/"),
        write_scope=(".signoffai/subagents/", ".signoffai/runs/"),
        allowed_tools=_READ + ("write_file", "str_replace", "delete_file",
                               "run_shell", "run_stage", "run_verify"),
        constraints=("只写自己的 staging/run 目录", "生成后必须编译"),
        deliverables=("changed_files.json", "compile.log"),
        acceptance=("vlog exit 0", "改动文件清单完整"),
        max_steps=16,
    ),
    "regression_engineer": AgentType(
        "regression_engineer", "运行编译/仿真/分级回归，分析失败日志",
        read_scope=("specs/", "sv/", "rtl/", "data/"),
        write_scope=(".signoffai/runs/", ".signoffai/subagents/"),
        allowed_tools=_READ_EVIDENCE + ("run_shell", "run_verify",
                                        "job_start", "job_output", "job_kill"),
        constraints=("不修改 RTL/UVM", "失败必须附日志定位", "不得伪造 pass"),
        deliverables=("regression_summary.json", "findings.json"),
        acceptance=("每级回归结果有日志", "失败有归因"),
        max_steps=20,
    ),
    "evidence_auditor": AgentType(
        "evidence_auditor", "核对证据完整性、契约映射、覆盖率与签核资格",
        read_scope=("specs/", "output", ".signoffai/"),
        write_scope=(), allowed_tools=_READ_EVIDENCE + ("write_file",),
        constraints=("工程只读", "交付物只写本子 Agent 工作区", "不能自行宣布 active", "最终裁决由确定性 gate 做"),
        deliverables=("evidence_audit.json",),
        acceptance=("每个 C-* 有证据映射", "缺证据显式列出"),
    ),
}


ROLE_PROMPTS: Dict[str, str] = {
    "spec_analyst": """You are a read-only spec analyst. Extract interfaces,
registers, timing/ordering rules and acceptance criteria from specs/docs.
Every finding must cite file and line. Mark ambiguity as unresolved instead of
guessing. Do not edit project files; write findings only in your own workspace. Do not claim verification passed.""",
    "rtl_analyst": """You are a read-only RTL analyst. Trace drivers, resets,
state machines and interface timing. Report undriven/X outputs, missing resets,
and protocol gaps with file:line evidence. Do not modify project files;
deliverables go to your own workspace. Do not claim a test passed without EDA
evidence.""",
    "verification_designer": """You are a verification designer. Produce a test
plan, testpoints and executable SVA rules (signals, expressions, expected
timing). Prefer rules that can be compiled and simulated; avoid prose-only
obligations. Write artifacts only inside your subagent workspace.""",
    "uvm_engineer": """You are a UVM engineer. Generate/modify interface, agent,
sequence, env or test only inside your assigned workspace/run. Compile after
editing and report the real vlog/vsim exit code. Never edit main/ or contracts;
never claim success without compile/sim evidence.""",
    "regression_engineer": """You are a regression engineer. Run compile,
simulation and staged regression, then read the real logs. Do not edit RTL/UVM.
Attribute each failure to a file/line or a missing dependency. A blocked or
missing EDA stage must be reported as such, not downgraded to pass.""",
    "evidence_auditor": """You are a read-only evidence auditor. Check that each
contract has linked evidence, that regression/coverage artifacts exist and
hashes match. Write the audit artifact only in your own workspace. You may
recommend eligibility but you cannot activate a contract; the deterministic
gate and human review make that decision.""",
}


def build_contract(agent_type: str, objective: str, *,
                   parent_task_id: str = "", task_id: str = "",
                   scope: Dict[str, List[str]] | None = None,
                   deliverables: List[str] | None = None,
                   acceptance: List[str] | None = None,
                   constraints: List[str] | None = None) -> SubagentContract:
    if agent_type not in AGENT_TYPES:
        raise KeyError(f"未知 agent_type: {agent_type}")
    spec = AGENT_TYPES[agent_type]
    return SubagentContract(
        task_id=task_id or f"{agent_type}_{uuid.uuid4().hex[:8]}",
        agent_type=agent_type,
        objective=str(objective),
        parent_task_id=parent_task_id,
        scope=scope or {"read": list(spec.read_scope),
                        "write": list(spec.write_scope)},
        constraints=list(constraints or spec.constraints),
        deliverables=list(deliverables or spec.deliverables),
        acceptance=list(acceptance or spec.acceptance),
    )


__all__ = ["AgentType", "AGENT_TYPES", "ROLE_PROMPTS", "build_contract"]
