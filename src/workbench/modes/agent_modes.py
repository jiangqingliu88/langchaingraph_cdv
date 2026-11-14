"""GUI 对话的 9 种 Agent 模式 —— 唯一清单。

这些模式是**领域角色**，和底层交互方式（chat / plan / verify）正交：
  · `interaction` 决定走哪条真实后端（agent_turn / 计划审批 / verify router）；
  · `role_prompt` 注入 Harness 的 system prompt，改变专家的关注点；
  · `specialist` 指向 `src/agent_plane/specialists/` 里的专家（空 = 通用 Harness）；
  · `stages` 是该模式实际涉及的阶段执行器；
  · `gap` 是没有专门专家时的诚实说明 —— 不把"没有"伪装成"已实现"。

新增/改名只改这里：GUI 下拉、后端 config、测试都从这一份读，避免
"界面有 9 个模式、后端只认 3 个"的两份真相。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 交互方式必须是 `interaction._mode()` 认得的三个值。
INTERACTIONS = ("chat", "plan", "verify")


@dataclass(frozen=True)
class AgentMode:
    id: str
    label: str
    description: str
    interaction: str
    role_prompt: str = ""
    #: 对应 `src/agent_plane/specialists/<specialist>`（空 = 通用 Harness）。
    specialist: str = ""
    #: 该模式实际会走到的阶段执行器。
    stages: tuple[str, ...] = ()
    #: 没有专门专家时的说明（界面/文档直接展示，不假装已实现）。
    gap: str = ""
    #: GUI 动作入口（空 = 只有对话，没有独立动作按钮）。
    #: mental_ir / formal_plan / unit_test。
    action: str = ""
    action_label: str = ""

    @property
    def agent_label(self) -> str:
        return self.specialist or "harness"


AGENT_MODES: tuple[AgentMode, ...] = (
    AgentMode(
        "agentic_chat",
        "Agentic Chat",
        "General-purpose chat for workspace exploration and code assistance",
        "chat",
        "",
        gap="通用 Harness 对话，不是专家子图",
    ),
    AgentMode(
        "mental_model",
        "Mental Model",
        "Design understanding and analysis mode",
        "chat",
        "你处于 Mental Model 模式：先把设计意图摊开——验证目标、依赖假设、"
        "规格歧义（blocking 要明确）、验证意图与风险。拿不准的写进歧义，"
        "不要编成目标；需要结构化产物时使用「生成 Mental IR」入口。",
        specialist="mental",
        action="mental_ir",
        action_label="生成 Mental IR",
    ),
    AgentMode(
        "formal",
        "Formal",
        "Formal verification agent mode",
        "plan",
        "你处于 Formal 模式：围绕形式化属性、假设、约束与证明边界工作。没有真实证明/工具证据时，不得声称已经证明成立。",
        specialist="formal",
        stages=("verify",),
        gap="v1：生成 Formal IR；未接形式引擎时 engine.ran=false",
        action="formal_plan",
        action_label="生成 Formal 计划",
    ),
    AgentMode(
        "uvm",
        "UVM",
        "UVM testplan, testbench development mode",
        "plan",
        "你处于 UVM 模式：围绕 testplan、UVM 组件、sequence、scoreboard 与覆盖率展开；产物必须可编译、可运行、可判定。",
        specialist="verify",
        stages=("verify",),
    ),
    AgentMode(
        "rtl_designer",
        "RTL Designer",
        "Lint violation Auto-fix",
        "plan",
        "你处于 RTL Designer 模式：先定位 lint 规则与违规证据，再改 RTL；"
        "修复后必须重新跑检查，不得用「看起来对」代替验证结果。",
        specialist="design",
        stages=("front", "design", "model"),
    ),
    AgentMode(
        "unit_testing",
        "Unit Testing Agent",
        "Unit testing and testbench development (SV based, no UVM)",
        "plan",
        "你处于 Unit Testing 模式：为单位模块搭纯 SystemVerilog testbench"
        "（不引入 UVM），关注激励、检查器与可复现的通过/失败判定。",
        specialist="unit_test",
        stages=("verify",),
        gap="v1：生成+编译/运行纯 SV TB；无 EDA 时状态是 GENERATED_ONLY",
        action="unit_test",
        action_label="生成/运行单测",
    ),
    AgentMode(
        "functional_coverage",
        "Functional Coverage (interface-based)",
        "Functional coverage monitor generation (RTL interface-based)",
        "plan",
        "你处于 Functional Coverage 模式：基于 RTL 接口生成功能覆盖率监视器"
        "（covergroup + 采样点），确保 bin 可命中、可解释、能归因到接口。",
        specialist="coverage",
        stages=("coverage",),
    ),
    AgentMode(
        "debug",
        "Debug",
        "DV debug agent mode",
        "plan",
        "你处于 Debug 模式：从仿真日志、波形与失败用例定位根因；区分环境"
        "问题与 DUT 缺陷，修复后必须重跑验证给出真实结果。",
        specialist="debug",
        stages=("ops", "debug"),
    ),
    AgentMode(
        "workflows",
        "Workflows",
        "End-to-end automated workflows",
        "verify",
        "你处于 Workflows 模式：面向端到端流程（front → verify → ops → "
        "coverage → audit），明确每一步的输入、产物与门禁；执行走验证流程。",
        specialist="supervisor",
        stages=("front", "design", "model", "verify", "ops", "coverage",
                "debug", "audit"),
        gap="走编排主图（supervisor），不是 specialists/ 下的单一专家",
    ),
)

_BY_ID: dict[str, AgentMode] = {m.id: m for m in AGENT_MODES}


def get_mode(mode_id: str | None) -> AgentMode:
    """未知 id 退回 Agentic Chat（界面永远有可用默认值）。"""
    return _BY_ID.get(str(mode_id or ""), AGENT_MODES[0])


def mode_ids() -> tuple[str, ...]:
    return tuple(m.id for m in AGENT_MODES)


def specialist_map() -> dict[str, str]:
    """模式 → 专家（文档/界面快速对照用）。"""
    return {m.id: m.agent_label for m in AGENT_MODES}


__all__ = ["AGENT_MODES", "AgentMode", "INTERACTIONS", "get_mode", "mode_ids",
           "specialist_map"]
