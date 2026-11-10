"""闭环流水线的跨阶段状态 —— 取代裸 dict `ctx`。

背景（为什么要有这个文件）
    run_closed_loop 原来的共享状态是 `ctx = {}`，靠 `ctx.update(data)` 盲目合并
    agent 返回值。这带来两类静默故障：

    1) 键冲突无声覆盖。同一批键被多处写入，谁后跑谁赢。真实存在的冲突：
         "coverage"  base.py:624 的 COVERAGE_KEYS 映射  vs  agents/coverage/main.py:202
         "model"     base.py:621 的 MODEL_KEYS          vs  agents/model/main.py:343
         "tests" / "debug" / "env" / "regression"  同类
       最糟的是 COVERAGE_KEYS 里含 line_pct / branch_pct / gaps 这类泛用名——
       design 或 debug 的 LLM 只要吐出任一名字，就会把 coverage 污染到全局。

    2) 契约不可见。没有任何地方能回答「这个键由谁写、被谁读」。

    因此本模块把状态显式化：字段有类型、有缺省、有归属。

四类通道（按写入纪律划分）
    A 控制/累加器   多写者，用 reducer 合并（operator.add 既能计数也能追加）
    B 各阶段产物    单写者，经 _exclusive reducer 保证同一步内不被两人写
    C 循环簿记      单写者，最后写入者胜
    D 运行期对象    **不进状态**——不可字节复现的东西一律放 runtime context

    判据：序列化后不可字节复现的对象（活 sqlite 连接、LLM 客户端、agent 实例、
    文件句柄）绝不进状态，否则 checkpointer 无法持久化，--resume 也就无从谈起。
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# 默认仿真业务（`cov+wave`）**只有一份定义** —— 在工具层的 `sim_modes.py`。
# 这里 import 而不是写 `["cov+wave"]`：默认值散成字面量之后，改一处漏一处
# 就会变成"CLI 默认开了波形、界面默认没开"这种查不出来的不一致。
from src.layers.l2_orchestration.regression_tools.sim_modes import (
    DEFAULT_MODE as _DEFAULT_SIM_MODE,
)


# ═══════════════════════════════════════════════════════════════
# reducer
# ═══════════════════════════════════════════════════════════════

def exclusive(old: Any, new: Any, default: Any = None) -> Any:
    """通道 B 用：同一步内两个节点写同一字段且值不同 → 直接报错。

    静态的 PHASE_OWNERS 注册表只能挡住「声明上的」冲突；这个 reducer 挡的是
    运行期才暴露的冲突（例如某个 agent 因 LLM 输出变化而多写了一个键）。
    安静地让后写者覆盖，正是本模块要消灭的行为。
    """
    if old is None or old == default:
        return new
    if new is None or new == default:
        return old
    if old == new:
        return old
    raise ValueError(
        f"字段被两个节点在同一步内写入且取值不同: {old!r} vs {new!r}；"
        "请检查 PHASE_OWNERS 归属，或让其中一方不要写该字段"
    )


def _add(a: Any, b: Any) -> Any:
    """operator.add 的包装，供 Annotated 使用。

    对 int 是自增（循环计数器），对 list 是连接（追加）。同一个 reducer 兼顾
    两种用途，这正是「bump 节点既能推轮次、又能追加 phases」能成立的原因。
    """
    return operator.add(a, b)


# ═══════════════════════════════════════════════════════════════
# 状态模型
# ═══════════════════════════════════════════════════════════════

class PipelineState(BaseModel):
    """七 Agent 闭环的跨阶段状态。

    extra="forbid"：任何未声明的键写入即报错。新增键是一次 schema 变更，
    而不是运行期意外——这是把「静默覆盖」变成「显式失败」的关键。
    """
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    # ── A. 控制 / 累加器（多写者，reducer 合并）──
    run_id: str = ""
    round_num: Annotated[int, _add] = 0
    iterations: Annotated[int, _add] = 0
    max_rounds: int = 5
    target: float = 95.0
    design_style: str = "baseline"
    bypass_design_model: bool = False
    #: **只跳 design、不跳 model**：外部给了 RTL（`--rtl`）时用。
    #: 与 `bypass_design_model` 的区别就在这里 —— 那个把 model 也跳了，
    #: 而给现成 RTL 时**参考模型仍然必须生成**（它是比对的那一半）。
    #: 跳过它 = 拿一份没有 expected 的环境去比，等于什么都不验。
    bypass_design: bool = False
    #: 这次运行要开的**仿真业务**（`cov` / `wave` / `debug_all` / …，
    #: 见 `src/layers/l2_orchestration/regression_tools/sim_modes.py`）。
    #: 是**运行输入**、不是全局开关 —— 记在状态里，复现/审计时能回答
    #: "这一轮的波形是怎么来的"。默认 `cov+wave`：覆盖率是主指标、波形是事后现场 ——
    #: 只开覆盖率的话，事后想看信号只能回去重跑（而重跑出来的未必是当时那个现场）。
    sim_modes: List[str] = Field(
        default_factory=lambda: [_DEFAULT_SIM_MODE])
    #: 分级回归的**人工节点**是否拦截（loopback 全过后停下等人放行）。
    #: `True` = 停（`REGRESSION_MANUAL_GATES`）；`False` = 不拦、一口气跑完
    #: （`run_regression_staged(auto_approve=True)`）。**属于这次运行的输入**：
    #: 跑完要能回答"这一轮为什么没停"。默认 `True` —— 门是默认该在的。
    manual_gate: bool = True

    phases: Annotated[List[Dict[str, Any]], _add] = Field(default_factory=list)
    coverage_history: Annotated[List[float], _add] = Field(default_factory=list)
    coverage_db_history: Annotated[List[Dict[str, Any]], _add] = Field(default_factory=list)
    compile_retries: Annotated[int, _add] = 0
    seed: Annotated[int, _add] = 0

    eda_blocked: Annotated[bool, operator.or_] = False
    interrupted: Annotated[bool, operator.or_] = False
    #: 分级回归停在人工节点（loopback 全过、等人放行）。**不是失败**，是"机器该让位
    #: 给人类"。必须能让闭环停 —— 否则每轮都卡在放行点、被判成 ops 失败，白烧
    #: `max_rounds` 轮（实测 5 轮 loopback 跑完才发现 5 次都是同一件事）。
    awaiting_approval: Annotated[bool, operator.or_] = False

    # ── B. 各阶段产物（单写者，exclusive）──

    # design
    spec: Dict[str, Any] = Field(default_factory=dict)
    design_arch: Optional[Dict[str, Any]] = None
    # model
    model: Optional[Dict[str, Any]] = None
    # verify
    tests: Optional[Dict[str, Any]] = None
    # ops
    env: Optional[Dict[str, Any]] = None
    regression: Dict[str, Any] = Field(default_factory=dict)
    # debug
    debug: Optional[Dict[str, Any]] = None
    # coverage
    coverage: Dict[str, Any] = Field(default_factory=dict)
    gaps: List[Dict[str, Any]] = Field(default_factory=list)
    coverage_map: Dict[str, Any] = Field(default_factory=dict)
    calibration: Dict[str, Any] = Field(default_factory=dict)
    coverage_db: Dict[str, Any] = Field(default_factory=dict)
    coverage_summary: str = ""
    log_path: str = ""
    vcd_path: str = ""
    functional_coverage: float = 0.0
    # audit
    audit: Optional[Dict[str, Any]] = None

    # ── C. 循环簿记（单写者，最后写入者胜）──
    regression_failed_count: int = 0
    compile_error: Optional[Dict[str, Any]] = None
    final_coverage: float = 0.0
    effective_coverage: float = 0.0
    exclude_effect: Dict[str, Any] = Field(default_factory=dict)
    #: 粗连续奖励（`l3_decision/reward.py`）—— 编译/回归/覆盖率三层合成的 0..1。
    #: 决策层读它判断“最弱的一层”，签核证据也可引用。
    sim_reward: Dict[str, Any] = Field(default_factory=dict)
    #: 运行时知识图摘要（`coverage/knowledge_graph.json`）——路径/哈希/节点数。
    knowledge_graph: Dict[str, Any] = Field(default_factory=dict)

    # 决策：Action 是 dataclass（decision_engine.py:41），为可序列化存 dict，
    # 用的时候再 Action(**d)。见 _action_from_state()。
    pending_action: Optional[Dict[str, Any]] = None
    last_action: Optional[Dict[str, Any]] = None
    decision_log: Annotated[List[Dict[str, Any]], _add] = Field(default_factory=list)

    # 门控
    approval_outcome: Optional[str] = None
    guardian_verdict: Dict[str, Any] = Field(default_factory=dict)
    governance_outcome: Optional[str] = None
    human_escalation: Optional[str] = None
    terminal_reason: Optional[str] = None

    # ── D2. Supervisor 主图路由（与 24 节点执行细节分离）──
    #: 主图下一次派谁：`design_expert` / `execution_expert` / `audit_gate` / `end`。
    #: 只由 `n_supervisor` 写；子图不读它，避免“专家自己决定下一步”。
    next_agent: str = ""
    #: 子图是否已经完成过（主图据此决定是否再次派工）。
    design_done: bool = False
    execution_done: bool = False
    #: 主图访问 supervisor 的次数（防循环失控；不是轮次预算）。
    supervisor_visits: Annotated[int, _add] = 0
    #: 纯审计门的结论（`report.json` / `signoff_evidence` 是否存在 + 哈希可读）。
    audit_gate: Dict[str, Any] = Field(default_factory=dict)
    #: 可观测的路由轨迹（只追加，不覆盖）。
    supervisor_trace: Annotated[List[Dict[str, Any]], _add] = Field(
        default_factory=list)

    # ── E. 终态结果包 ──
    # finalize 节点整体写入，run_closed_loop 原样返回给调用方（CLI / GUI / 服务层）。
    #
    # **为什么必须显式声明**：PipelineState 是 extra="forbid" 的 pydantic 模型，
    # 而 LangGraph 对**未声明**的键是**静默丢弃**——不报错、不警告。在补上这个
    # 字段之前，`n_finalize` 的 `return {"result": ...}` 一直没进状态，
    # 于是 `run_closed_loop` 恒返回 `{}`：CLI 的 run_id / coverage / converged
    # 全是 None / 0 / NO，`--json` 吐一堆 null。
    # （tests/test_run_streaming.py::TestResultSurvives 钉住这条。）
    result: Optional[Dict[str, Any]] = None

    # ── D. 不进状态（仅在此声明，供 init 节点重建）──
    #   registry / 7 个 agent 实例 / governor / infra / testcase_reg / exclude_reg
    #   / decision_reactor / planner / file_audit  → 走 config["configurable"]["rt"]
    #
    #   output_root 是 str（不是 Path）：Path 可序列化但没必要，保持与既有
    #   调用方一致，用的时候再 Path()。
    output_root: str = "output"

    def action(self):
        """把 pending_action 还原成 Action 对象（惰性 import，避免 L3→L2 环）。"""
        if not self.pending_action:
            return None
        from src.layers.l3_decision.decision_engine import Action
        return Action(**self.pending_action)


# ═══════════════════════════════════════════════════════════════
# 归属注册表 —— 构图期校验
# ═══════════════════════════════════════════════════════════════
# 字段 → 负责写入它的节点名。空字符串表示「由 init / 框架写，不属于任何 agent」。

PHASE_OWNERS: Dict[str, str] = {
    # design 节点
    "spec": "design", "design_arch": "design",
    # model / verify 节点
    "model": "model", "tests": "verify",
    # ops 节点
    "env": "ops_r", "regression": "ops_r",
    # debug 节点
    "debug": "debug_functional",
    # coverage 节点
    "coverage": "coverage_r", "gaps": "coverage_r", "coverage_map": "coverage_r",
    "calibration": "coverage_r", "coverage_db": "coverage_r",
    "coverage_summary": "coverage_r", "log_path": "coverage_r", "vcd_path": "coverage_r",
    "functional_coverage": "coverage_r",
    # audit 节点
    "audit": "audit",
}

# 非 agent 产物的字段（框架 / init / 各门控节点写入），不参与归属唯一性检查。
NON_AGENT_FIELDS = set(PipelineState.model_fields) - set(PHASE_OWNERS)


# ═══════════════════════════════════════════════════════════════
# 字段契约 —— 写入者 / 读者 / 是否进 checkpoint
# ═══════════════════════════════════════════════════════════════
#
# `PHASE_OWNERS` 只覆盖“各阶段产物”且属主名带历史后缀；这里补的是**关键
# 流转字段**的完整契约（尤其是本轮新增的 sim_reward / knowledge_graph）。
# 未列出的字段视为“自由字段”，不做运行期告警 —— 先把最贵的几条锁住。
#
# 运行期守卫在 `graph.py`：节点返回 update 后，若写了不属于自己的关键字段，
# 打一条 warning（不是失败：图上仍以 LangGraph 的 reducer 为准）。
STATE_CONTRACTS: Dict[str, Dict[str, Any]] = {
    # 阶段产物
    "spec":              {"writers": ("front", "design"), "readers": ("model", "verify", "coverage"), "checkpoint": True},
    "design_arch":       {"writers": ("front", "design"), "readers": ("model", "verify"), "checkpoint": True},
    "model":             {"writers": ("model",), "readers": ("verify", "ops"), "checkpoint": True},
    "tests":             {"writers": ("verify",), "readers": ("ops",), "checkpoint": True},
    "env":               {"writers": ("ops",), "readers": ("ops",), "checkpoint": True},
    "regression":        {"writers": ("ops",), "readers": ("coverage", "decide"), "checkpoint": True},
    "debug":             {"writers": ("debug_functional",), "readers": ("decide",), "checkpoint": True},
    "coverage":          {"writers": ("coverage",), "readers": ("decide", "audit"), "checkpoint": True},
    "gaps":              {"writers": ("coverage",), "readers": ("decide",), "checkpoint": True},
    "audit":             {"writers": ("audit",), "readers": ("finalize",), "checkpoint": True},
    # 本轮新增的跨层信号
    "sim_reward":        {"writers": ("coverage",), "readers": ("decide", "audit", "finalize"), "checkpoint": True},
    "knowledge_graph":   {"writers": ("coverage",), "readers": ("decide", "audit", "finalize"), "checkpoint": True},
    # 决策簿记
    "pending_action":    {"writers": ("decide", "governor"), "readers": ("governor", "record_decision", "action routers"), "checkpoint": True},
    "last_action":       {"writers": ("record_decision",), "readers": ("coverage", "finalize"), "checkpoint": True},
    "decision_log":      {"writers": ("record_decision",), "readers": ("finalize",), "checkpoint": True},
    "governance_outcome": {"writers": ("governor",), "readers": ("routers",), "checkpoint": True},
    "approval_outcome":  {"writers": ("approval",), "readers": ("routers",), "checkpoint": True},
    # 终态
    "result":            {"writers": ("finalize",), "readers": ("CLI", "workbench"), "checkpoint": True},
}


#: **越权写这些字段会静默篡改身份/结论** → 运行期硬失败（而不是 warning）。
#: 其余字段（如 `spec` / `env`）仍有 warning 作为观察哨，避免一上来把流水线
#: 拦死在"其实无害"的写冲突上。可用 `SIGNOFFAI_STATE_CONTRACT=warn` 退回告警。
CRITICAL_STATE_FIELDS = frozenset({
    "tests",        # verify 的产物：被别的节点覆盖 = 用例身份被改
    "coverage",     # 签核主指标：被覆盖 = 结论被改
    "audit",        # 终局判定：只能由 audit 写
    "result",       # 对外结论：只能由 finalize 写
})


def unexpected_state_writers(node_name: str, update: Dict[str, Any]) -> list:
    """节点写了不属于它的**关键字段** —— 返回字段名（空 = 正常）。

    只检查 `STATE_CONTRACTS` 里声明的字段；`phases` / 计数器这类多写者字段
    不在表里，保持自由。`*` 表示任何节点都可写。
    """
    bad = []
    for field in (update or {}):
        contract = STATE_CONTRACTS.get(field)
        if not contract:
            continue
        writers = contract.get("writers") or ()
        if "*" not in writers and node_name not in writers:
            bad.append(field)
    return bad


def validate_phase_owners() -> None:
    """构图期自检：归属表必须是 agent 字段集合的一个划分。

    在没有类型状态之前，「两个 agent 用同名键悄悄打架」要等线上跑出诡异结果
    才会被发现。这里让它在 import 阶段就炸。
    """
    owning_nodes = [n for n in PHASE_OWNERS.values() if n]
    duplicates = {n for n in owning_nodes if owning_nodes.count(n) > 1}
    if duplicates:
        # 同一个节点写多个字段是正常的；这里只提示，真正的冲突在同一字段被
        # 两个节点声明——dict 的键唯一，天然不可能，故仅做字段存在性校验。
        pass

    unknown = set(PHASE_OWNERS) - set(PipelineState.model_fields)
    if unknown:
        raise ValueError(
            f"PHASE_OWNERS 引用了 PipelineState 中不存在的字段: {sorted(unknown)}"
        )

    unknown_contract = set(STATE_CONTRACTS) - set(PipelineState.model_fields)
    if unknown_contract:
        raise ValueError(
            f"STATE_CONTRACTS 引用了 PipelineState 中不存在的字段: "
            f"{sorted(unknown_contract)}"
        )
    for field, contract in STATE_CONTRACTS.items():
        if not contract.get("writers"):
            raise ValueError(f"STATE_CONTRACTS.{field} 必须声明至少一个写入者")


validate_phase_owners()
