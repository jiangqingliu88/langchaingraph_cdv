# SignOffAI × LangGraph 重构文档

**文档版本**：v1.0
**分支**：`refactor/langgraph-migration`
**状态**：待评审
**目标读者**：架构师、验证工程师、平台工程师、签核负责人

---

## 目录

1. 背景与目标
2. 设计原则：三条铁律
3. 架构总览
4. 状态模型（VerificationState）
5. 主图编排（LangGraph StateGraph）
6. Agent 子图设计
7. 贯穿层：铁律门控与证据链
8. 决策层：8 动作优先级
9. 提示词链工程
10. HITL 与人机治理
11. 持久化架构
12. 成长层：V2 / V3 / V4
13. 通信层（A2A）
14. 迁移路线图
15. 验收标准
16. 风险与缓解
17. 附：完整主图代码骨架

---

## 1. 背景与目标

### 1.1 背景

IC 验证的核心痛点不是“没人会写 UVM”，而是：

- 覆盖率从 90% 涨到 95% 的时间比 0 到 90% 还多，最后几个点的空洞归因不清
- 改一行 RTL 补覆盖率，可能把已通过的功能改坏
- 三个月后无法回答“当时为什么放宽这个约束”
- 签核时拿不出可审计的证据链，只能给出“覆盖率 96.3%，应该可以吧”

本重构的目标，是把 IC 验证从“手工作坊”改造成**可复现、可审计、可治理、可进化**的工程系统。

### 1.2 重构目标

| 目标 | 衡量标准 |
|---|---|
| 编排层标准化 | LangGraph StateGraph 替代自研调度 |
| 状态持久化标准化 | Postgres Checkpointer + Store |
| HITL 标准化 | `interrupt_on` + 自研签名层 |
| 长期知识标准化 | LangGraph Store 替代自研 sqlite |
| **治理能力不降级** | 铁律、哈希链、8 动作优先级、RBAC、签名全部保留 |
| **可回滚** | 可按 run 切换 LangGraph 版本 tag |
| **可复现** | 任意 LLM 调用可追溯模板版本、seed、输出哈希 |
| **可审计** | 签核报告每个字段可追溯到哈希链某一环 |

### 1.3 非目标

- 不把决策路由交给 LLM（8 动作优先级保持纯函数）
- 不把铁律判断交给框架默认行为（自研 gate 前置）
- 不把证据链存进 Checkpointer（append-only Store namespace 独立）
- 不追求“更 Agentic”，追求“更可审计”

---

## 2. 设计原则：三条铁律

### 铁律一：EDA 是唯一真理

**LLM 生成的任何代码，必须经真实 `vlog` / `vsim` 编译仿真判定 PASS/FAIL，AI 不能自证正确。**

工程实现：`eda_gate` 节点前置强制校验。LLM 产物无工具回执 → 抛 `EDAGateError`；工具回执 `returncode != 0` → 回退空实现（`_neutralize_gap_seq`），不污染环境。

### 铁律二：覆盖率数据库版本固化

**每轮 ucdb 计算 SHA256 并归档。复现时回滚比对。**

工程实现：哈希固化 + 硬链接归档。任何时刻可回答“当时 96% 那个版本，跑的哪版 RTL、哪版环境”。

### 铁律三：LLM 只读降采样文本

**LLM 空洞分析只读 <1KB 的语义降采样汇总，绝不读几十 GB 的 ucdb。**

工程实现：`summarize_coverage_gaps` 工具输出硬上限 1KB，按语义选条目而非截断。既省 token，又避免 LLM 被高维数据带偏。

---

## 3. 架构总览

```
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                       Layer 4 · 人工审批层（Human Decision Layer）                     ║
║  interrupt_on: signoff_verification / exclude_proposal / rtl_refactor                ║
║  决策: approve / edit / reject    审批记录（带签名）→ 证据链哈希                       ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
                                        ▲  interrupt / resume
                                        │
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                    Layer 3 · LangGraph StateGraph 主图（编排层）                      ║
║                                                                                      ║
║   ┌──────────────── 生产者 Producer ────────────────┐                                ║
║   │  design 子图 ──▶ model 子图 ──▶ verify 子图      │                                ║
║   └───────┬───────────────┬───────────────┬─────────┘                                ║
║           ▼               ▼               ▼                                          ║
║   ┌───────────────────────────────────────────────┐                                  ║
║   │   铁律一门控  EDA Gate（LLM 不能自证正确）     │                                  ║
║   └────────────────────────┬──────────────────────┘                                  ║
║                            │  passed                                                 ║
║   ┌──────────────── 执行者 Executor ────────────────┐                                ║
║   │  ops 子图 ◀────▶ coverage 子图                  │                                ║
║   └───────────────────────┬─────────────────────────┘                                ║
║                           ▼                                                          ║
║   ┌──────────────────────────────────────────────┐                                   ║
║   │   Decision Router（纯函数）8 动作严格优先级   │                                   ║
║   └──────────────────────┬───────────────────────┘                                   ║
║                          │                                                           ║
║   ┌──────────────── 守门人 Gatekeepers ──────────────────────┐                       ║
║   │  debug 子图 · golden_guard · exclude_gate · audit 子图   │                       ║
║   └──────────────────────┬───────────────────────────────────┘                       ║
╚══════════════════════════╪═══════════════════════════════════════════════════════════╝
                           ▼
╔══════════════════════════════════════════════════════════════════════════════════════╗
║               Layer 2 · 纵向贯穿层（Cross-cutting Layers）                            ║
║  铁律一 EDA Gate  |  铁律二 ucdb 固化  |  铁律三 <1KB 降采样                          ║
║  证据链: 哈希链 + 五层领域证据（需求→设计→验证→执行→签核）+ 运行清单                 ║
║  A2A 通信: Command(update, goto, metadata.task.reason)                               ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
                           ▼
╔══════════════════════════════════════════════════════════════════════════════════════╗
║               Layer 1 · 持久化层（Checkpointer + Store）                              ║
║  Checkpointer（短期状态）        Store（长期知识）                                    ║
║  · thread-scoped                 · evidence/hash_chain (append-only)                 ║
║  · HITL 中断/恢复                · evidence/domain · evidence/manifest               ║
║  · 容错、时间旅行                · golden/baseline · kg/verification                 ║
║                                  · knowledge/cross_project · policies                ║
║                                  · prompts/templates · prompts/invocations           ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
                           ▼
╔══════════════════════════════════════════════════════════════════════════════════════╗
║               Layer 0 · 确定性工具层（MCP Tool Layer）                                ║
║  vlog 编译 · vsim 仿真 · vcs 回归 · ucdb 覆盖率 · JasperGold 形式验证                ║
║  每个 Tool 独立 schema + 风险分级 + 结构化回执（tool_receipts）                       ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
```

### 3.1 读图三层法

1. **从下往上看“谁说了算”**：Layer 0 工具是唯一真理源 → Layer 1 持久化保证可复现 → Layer 2 铁律锁死 LLM 边界 → Layer 3 编排决定“下一步做什么” → Layer 4 人保留最终仲裁。
2. **从左往右看“一次 run 怎么走”**：design → model → verify → EDA Gate → ops → coverage → Decision Router → 8 动作分流 → 守门人 → audit → 证据链。
3. **从外往内看“跨 run 怎么进化”**：V4 只读检索 → V3 提供路由策略 → V2 提供语义坐标 → V1 执行闭环。

---

## 4. 状态模型（VerificationState）

```python
from typing import Annotated, Literal, Optional
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class VerificationState(TypedDict):
    # === 会话与运行标识 ===
    messages: Annotated[list[BaseMessage], add_messages]
    run_id: str
    run_seed: int                        # 用于 LLM 可复现
    project_id: str

    # === 输入资产 ===
    spec_text: str
    rtl_source: str
    rtl_git_tag: Optional[str]
    env_hash: Optional[str]
    verification_plan: Optional[dict]

    # === 生成产物（需经工具验证） ===
    generated_sva: list[dict]            # [{id, content, source, tool_receipt_id}]
    generated_tb: Optional[dict]
    generated_stimulus: list[dict]

    # === 工具回执（确定性证据） ===
    tool_receipts: list[dict]            # [{id, tool, returncode, artifact_hash}]
    compile_result: Optional[dict]
    simulation_result: Optional[dict]
    formal_result: Optional[dict]

    # === 覆盖率（铁律三：只存降采样） ===
    coverage_summary: Optional[str]      # <1KB
    coverage_ucdb_path: Optional[str]
    coverage_ucdb_hash: Optional[str]    # 铁律二
    coverage_total: Optional[int]
    coverage_covered: Optional[int]
    coverage_target: float
    effective_coverage: Optional[float]
    uncovered_bins: list[dict]
    gap_vectors: list[dict]              # [{bin, reason, req_id, signal, transition}]
    current_gap: Optional[dict]

    # === 决策 ===
    current_phase: str
    decision_log: list[dict]             # 每次决策的 action/reason/时间
    retry_count: int
    max_retries: int
    coverage_stall_rounds: int

    # === 证据链 ===
    evidence_chain_head: Optional[str]
    pending_modifications: list[dict]    # 待写入哈希链
    approval_history: list[dict]
    excluded_bins: list[dict]

    # === 黄金基线 ===
    golden_status: Optional[str]         # initializing / passed / rejected
    pending_rtl_change: Optional[dict]
    rejected_refactors: list[dict]

    # === 知识上下文 ===
    retrieved_specs: list[dict]
    kg_context: Optional[str]            # V2 图遍历结果（<512B）
    cross_project_hits: list[dict]       # V4 跨项目检索结果

    # === 错误与审批 ===
    error_log: list[str]
    pending_approval: Optional[dict]
```

**关键约束**：
- `coverage_summary` 硬上限 1KB（铁律三）
- `tool_receipts` 是 LLM 事实性断言的唯一凭据
- `pending_modifications` 只能由 `evidence_chain_node` 消费
- `run_seed` 保证 LLM 调用可复现

---

## 5. 主图编排（LangGraph StateGraph）

### 5.1 主图结构

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

# ===== 持久化 =====
checkpointer = PostgresSaver.from_conn_string(PG_DSN)
store = PostgresStore.from_conn_string(PG_DSN)
checkpointer.setup()

# ===== 主图 =====
builder = StateGraph(VerificationState)

# ---- 生产者子图 ----
builder.add_node("design",   build_design_subgraph())
builder.add_node("model",    build_model_subgraph())
builder.add_node("verify",   build_verify_subgraph())

# ---- 执行者子图 ----
builder.add_node("ops",      build_ops_subgraph())
builder.add_node("coverage", build_coverage_subgraph())

# ---- 守门人子图 ----
builder.add_node("debug",    build_debug_subgraph())
builder.add_node("audit",    build_audit_subgraph())

# ---- 贯穿层节点 ----
builder.add_node("eda_gate",       eda_gate_node)
builder.add_node("evidence_chain", evidence_chain_node)
builder.add_node("golden_guard",   golden_guard_node)
builder.add_node("exclude_gate",   exclude_gate_node)
builder.add_node("human_review",   human_review_node)
builder.add_node("decision_dispatch", decision_dispatch_node)

# ---- 主流程边 ----
builder.add_edge(START, "design")
builder.add_edge("design", "eda_gate")
builder.add_edge("eda_gate", "model")
builder.add_edge("model", "verify")
builder.add_edge("verify", "eda_gate")
builder.add_edge("eda_gate", "ops")
builder.add_edge("ops", "coverage")

# ---- 决策前路由（判断是否需要前置守卫） ----
builder.add_conditional_edges(
    "coverage",
    pre_decision_router,
    {
        "golden_guard": "golden_guard",
        "exclude_gate": "exclude_gate",
        "decide":       "decision_dispatch",
    },
)

# ---- 8 动作分发 ----
builder.add_conditional_edges(
    "decision_dispatch",
    decision_router,
    ACTION_TO_NODE,
)

# ---- 回流 ----
builder.add_edge("golden_guard", "design")
builder.add_edge("exclude_gate", "audit")
builder.add_conditional_edges("debug", decision_router, ACTION_TO_NODE)

# ---- 签核 ----
builder.add_edge("audit", "evidence_chain")
builder.add_edge("evidence_chain", END)

# ---- 编译 ----
graph = builder.compile(
    checkpointer=checkpointer,
    store=store,
    interrupt_on={
        "signoff_verification": {"allowed_decisions": ["approve", "reject"]},
        "exclude_proposal":     {"allowed_decisions": ["approve", "edit", "reject"]},
        "rtl_refactor":         {"allowed_decisions": ["approve", "edit", "reject"]},
    },
)
```

### 5.2 路由函数

**`pre_decision_router`（确定性，无 LLM）**

```python
def pre_decision_router(state: VerificationState) -> str:
    """决策前置判断：是否需要走守卫节点"""
    if state.get("exclude_candidates"):
        return "exclude_gate"
    if state.get("pending_rtl_change"):
        return "golden_guard"
    return "decide"
```

**`decision_router`（纯函数，8 动作优先级）**

```python
DECISION_PRIORITY = [
    ("COMPILE_RETRY",          lambda s: s.get("compile_failed")),
    ("UPDATE_MODEL",           lambda s: s.get("model_mismatch")),
    ("RETRY_ENV",              lambda s: s.get("test_failed")),
    ("REFACTOR_RTL",           lambda s: has_gap(s, "unreachable")),
    ("RELAX_CONSTRAINT",       lambda s: has_gap(s, "constraint")),
    ("GENERATE_DIRECTED_TEST", lambda s: has_gap(s, "unstimulated")),
    ("EXPAND_SEEDS",           lambda s: s.get("coverage_stall_rounds", 0) >= 3),
    ("CONVERGE",               lambda s: s.get("effective_coverage", 0) >= s["coverage_target"]),
]

ACTION_TO_NODE = {
    "COMPILE_RETRY":          "ops",
    "UPDATE_MODEL":           "model",
    "RETRY_ENV":              "ops",
    "REFACTOR_RTL":           "golden_guard",
    "RELAX_CONSTRAINT":       "verify",
    "GENERATE_DIRECTED_TEST": "verify",
    "EXPAND_SEEDS":           "ops",
    "CONVERGE":               "audit",
    "HUMAN_REVIEW":           "human_review",
}

def decision_router(state: VerificationState) -> str:
    """
    纯函数。不调 LLM。可单元测试。可版本化。
    V3 阶段可注入 DecisionBrain（RL 策略），但仍返回上述动作之一。
    """
    for action, cond in DECISION_PRIORITY:
        if cond(state):
            state.setdefault("decision_log", []).append({
                "action": action,
                "gap_vectors": state.get("gap_vectors", []),
                "timestamp": now_iso(),
            })
            return action
    return "HUMAN_REVIEW"
```

**关键约束**：`decision_router` 完全确定性，不调 LLM。LLM 只在单个动作内部（如 `REFACTOR_RTL` 具体改哪行 RTL）介入。

---

## 6. Agent 子图设计

### 6.1 七 Agent 三类角色

| 类别 | Agent | 职责 | 核心产出 |
|---|---|---|---|
| **生产者** | design | 架构分解 + RTL 生成 | RTL 文件 |
| **生产者** | model | 多语言参考模型 + 版本管理 | 参考模型 |
| **生产者** | verify | UVM 环境 + 测试 + SVA + gap 定向激励 | 验证资产 |
| **执行者** | ops | 编译 + 仿真 + 回归 | 工具回执 |
| **执行者** | coverage | 覆盖率指标 + 语义 gap 向量 | gap 向量 |
| **守门人** | debug | 五阶段根因分析 + 信号级证据矩阵 | 根因假设 |
| **守门人** | audit | 签核判定 + report.json | 签核证据包 |

### 6.2 子图隔离原则

- **state schema 隔离**：生产者子图含 `generated_*`，执行者子图含 `tool_receipts`，守门人子图含 `evidence_*`
- **权限隔离**：生产者不能写证据链，守门人不能改产物
- **调用隔离**：子图通过 `Command` 返回主图，不直接跳转其他子图

### 6.3 子图示例：verify 子图

```python
def build_verify_subgraph() -> StateGraph:
    """verify 子图：生成 → 工具验证 → 回退"""
    sg = StateGraph(VerifyState)

    sg.add_node("gen_sva",        gen_sva_node)
    sg.add_node("gen_tb",         gen_tb_node)
    sg.add_node("gen_stimulus",   gen_stimulus_node)
    sg.add_node("tool_check",     tool_check_node)
    sg.add_node("fallback",       fallback_node)

    sg.add_edge(START, "gen_sva")
    sg.add_edge("gen_sva", "gen_tb")
    sg.add_edge("gen_tb", "gen_stimulus")
    sg.add_edge("gen_stimulus", "tool_check")
    sg.add_conditional_edges(
        "tool_check",
        lambda s: "ok" if s["all_passed"] else "fallback",
        {"ok": END, "fallback": "fallback"},
    )
    sg.add_edge("fallback", END)

    return sg.compile()
```

---

## 7. 贯穿层：铁律门控与证据链

### 7.1 铁律一：EDA Gate

```python
class EDAGateError(Exception):
    """LLM 产物未经 EDA 验证就试图进入下游时抛出"""
    pass


def eda_gate_node(state: VerificationState) -> VerificationState:
    """
    铁律一：LLM 产物必须经 vlog/vsim 判定 PASS/FAIL。
    失败 → 回退空实现（_neutralize_gap_seq），不污染环境。
    """
    artifacts = (
        state.get("generated_sva", [])
        + ([state["generated_tb"]] if state.get("generated_tb") else [])
        + state.get("generated_stimulus", [])
    )

    for art in artifacts:
        if art.get("source") != "llm":
            continue  # 规则生成的无需 gate

        receipt = find_receipt(state["tool_receipts"], art["id"])
        if not receipt:
            raise EDAGateError(f"{art['id']} missing EDA receipt")

        if receipt["returncode"] != 0:
            art["content"] = art.get("neutralized_fallback", "// neutralized")
            art["source"] = "neutralized"
            state["error_log"].append(
                f"{art['id']} failed EDA gate → neutralized"
            )

    return state
```

### 7.2 铁律二：ucdb 版本固化

```python
def archive_ucdb_node(state: VerificationState) -> dict:
    """
    铁律二：每轮 ucdb 计算 SHA256 并归档。
    哈希固化 + 硬链接，任何时刻可回滚比对。
    """
    ucdb_path = state["coverage_ucdb_path"]
    digest = sha256_file(ucdb_path)
    archive = f"/archive/ucdb/{digest}.ucdb"

    if not os.path.exists(archive):
        os.link(ucdb_path, archive)   # 硬链接，省空间

    # 与 run 关联，写入 Store
    store.put(
        ("evidence", "manifest", state["run_id"]),
        key="ucdb",
        value={
            "hash": digest,
            "rtl_git_tag": state["rtl_git_tag"],
            "env_hash": state["env_hash"],
            "timestamp": now_iso(),
        },
    )
    return {"coverage_ucdb_hash": digest}
```

### 7.3 铁律三：<1KB 降采样

```python
@tool
def summarize_coverage_gaps(ucdb_path: str, target_signal: str = None) -> str:
    """
    铁律三：将高维 ucdb 压缩为 <1KB 语义降采样。
    LLM 只读本工具输出，绝不读原始 ucdb。
    按语义选条目，而非截断（避免非法 JSON）。
    """
    raw = coverage_db.query(ucdb_path, target_signal)
    gaps = [
        {
            "bin": b.name,
            "reason": classify_gap_reason(b),   # unreachable/constraint/unstimulated
            "signal": b.signal,
            "req_id": trace_to_requirement(b),  # V2 图遍历
        }
        for b in raw.uncovered_bins
    ]

    # 逐步降采样直到满足 <1KB
    for n in (20, 15, 10, 5, 3):
        text = json.dumps(gaps[:n], ensure_ascii=False)
        if len(text.encode()) <= 1024:
            return text
    return json.dumps(gaps[:1], ensure_ascii=False)
```

### 7.4 证据链节点

```python
def evidence_chain_node(state: VerificationState) -> dict:
    """
    哈希链写入。只在此节点写，Agent 无权直接写。
    每条记录: sha256(file + content_hash + diff + reason + agent + prev_hash)
    """
    head = store.get(NS["hash_chain"], key="latest") or {"hash": "genesis"}

    for mod in state.get("pending_modifications", []):
        payload = (
            mod["file"]
            + sha256_str(mod["content"])
            + mod["diff"]
            + mod["reason"]          # 来自 Command.metadata.task.reason
            + mod["agent"]
            + head["hash"]
        )
        h = sha256_str(payload)
        record = {
            "hash": h,
            "prev": head["hash"],
            "file": mod["file"],
            "reason": mod["reason"],
            "agent": mod["agent"],
            "run_id": state["run_id"],
            "timestamp": now_iso(),
        }
        store.put(NS["hash_chain"], key=h, value=record)
        head = record

    store.put(NS["hash_chain"], key="latest", value=head)
    return {"evidence_chain_head": head["hash"]}
```

### 7.5 五层领域证据

| 层 | 语义 | 关键检查项 |
|---|---|---|
| L1 需求层 | MD → 需求树 | 规格完整性、需求-测试映射 |
| L2 设计层 | 需求树 → RTL 信号 | RTL 信号映射、寄存器映射 |
| L3 验证层 | 需求树 → UVM 用例 | P0/P1/P2/P3 用例覆盖 |
| L4 执行层 | 仿真执行 | scoreboard mismatched==0、SVA failures==0 |
| L5 签核层 | 门限判定 | 覆盖率门限、回归通过率、证据完整性 |

**最终产出**：`manifest + 证据链 + ucdb_hash + git_tag` → 签核证据包。

---

## 8. 决策层：8 动作优先级

### 8.1 优先级表

| 动作 | 触发条件 | 优先级 | 去向 |
|---|---|---|---|
| `COMPILE_RETRY` | 编译失败 | 最高 | ops |
| `UPDATE_MODEL` | 比对失败 | 高 | model |
| `RETRY_ENV` | 测试失败 | 高 | ops |
| `REFACTOR_RTL` | 不可达/死代码 | 高 | golden_guard |
| `RELAX_CONSTRAINT` | 约束型 gap | 高 | verify |
| `GENERATE_DIRECTED_TEST` | 未激励 gap | 高 | verify |
| `EXPAND_SEEDS` | 覆盖率连续 N 轮增长 <1% | 中 | ops |
| `CONVERGE` | 覆盖率 ≥ 目标 | 低 | audit |
| `HUMAN_REVIEW` | 无动作命中 | 兜底 | human_review |

### 8.2 gap 归因分流

覆盖率智能体把高维未覆盖 bin 压缩成**可决策的 gap 向量**，每个 gap 带归因：

```
unreachable    → REFACTOR_RTL           （不是补测能解决的，必须改设计）
constraint     → RELAX_CONSTRAINT       （人为约束限制了取值，放宽即提升）
unstimulated   → GENERATE_DIRECTED_TEST （激励不足，定向补测）
```

**决策层从“看数字”变成“看原因”。** 这是闭环收敛效率质变的根源。

### 8.3 黄金基线与回归守卫

```python
def golden_guard_node(state: VerificationState) -> Command:
    """
    黄金基线回归守卫。
    REFACTOR_RTL 前强制跑 golden 用例集，<100% 通过则拒绝本次修改。
    """
    golden = store.get(NS["golden"], key="latest")

    if not golden:
        # 首次达标 → 打包 golden.tar.gz
        pack_golden(state, path="/golden/golden.tar.gz")
        store.put(NS["golden"], key="latest", value={
            "archive": "/golden/golden.tar.gz",
            "ucdb_hash": state["coverage_ucdb_hash"],
            "rtl_git_tag": state["rtl_git_tag"],
        })
        return Command(goto="design")

    result = run_golden_regression(golden["archive"], state["rtl_source"])
    if result["pass_rate"] < 1.0:
        return Command(
            goto="debug",
            update={
                "error_log": state["error_log"] + [
                    f"golden guard rejected: {result['failures']}"
                ],
                "rejected_refactors": state.get("rejected_refactors", [])
                    + [state["pending_rtl_change"]],
                "pending_rtl_change": None,
            },
        )
    return Command(goto="design", update={"golden_status": "passed"})
```

### 8.4 允许放弃：四步闭环

```python
def exclude_gate_node(state: VerificationState) -> Command:
    """
    允许放弃的审计门控。
    ① 自动发现 → ② 归因分类 → ③ 审计门控（工程师签名）→ ④ 动态调规
    只有"多次重构仍 0%"的 unreachable 点才自动提议。
    """
    candidates = []
    for b in state.get("uncovered_bins", []):
        if b["reason"] == "unreachable" and b["refactor_attempts"] >= 3:
            candidates.append({
                "bin_id": b["name"],
                "reason": "unreachable",
                "auto_discovered": True,
                "approver": None,
                "audit_hash": None,
            })

    if not candidates:
        return Command(goto="audit")

    decision = interrupt({
        "type": "exclude_proposal",
        "candidates": candidates,
        "message": "多次重构仍 0%，建议排除。需工程师签名。",
    })

    approved = []
    for cand, sig in zip(candidates, decision["signatures"]):
        if sig["approved"] and rbac.check(sig["engineer"], "verification_lead"):
            cand["approver"] = sig["engineer"]
            cand["audit_hash"] = store.get(NS["hash_chain"], "latest")["hash"]
            approved.append(cand)

    # 动态调规：有效覆盖率 = coverage / (total - excluded)
    total = state["coverage_total"]
    excluded = len(state.get("excluded_bins", [])) + len(approved)
    effective = state["coverage_covered"] / (total - excluded)

    return Command(
        goto="audit",
        update={
            "excluded_bins": state.get("excluded_bins", []) + approved,
            "effective_coverage": effective,
        },
    )
```

---

## 9. 提示词链工程

### 9.1 设计原则

**提示词不是“写得好不好的问题”，是“可复现、可审计、可回退的工程资产”。**

三条约束：
1. LLM 只做完形填空（骨架由模板渲染）
2. 输出必须绑工具回执（铁律一）
3. 每次调用进哈希链（可追溯模板版本、seed、输出哈希）

### 9.2 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: Prompt Executor（执行层）                          │
│  调用 LLM · 结构化解析 · 工具回执绑定 · 回退链               │
└─────────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: Prompt Compiler（编译层）                          │
│  模板渲染 · Token 预算控制 · 降采样 · 版本注入               │
└─────────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Prompt Template（模板层）                          │
│  Jinja2 骨架 · 槽位定义 · 版本化 · 哈希化                    │
└─────────────────────────────────────────────────────────────┘
```

### 9.3 Layer 1：模板层

**模板是“骨架 + 槽位”，不是自由文本：**

```jinja
{# templates/verify/gap_directed_test.j2 #}
{# version: v3.2.1  hash: a7f3c... #}

class {{ gap_seq_class_name }} extends base_gap_seq;
    `uvm_object_utils({{ gap_seq_class_name }})

    virtual task body();
        // === LLM_FILL_START ===
        // 目标: 制造 {{ target_signal }} 的 {{ target_transition }}
        // 归因: {{ gap_reason }}
        // 需求: {{ req_id }}
        // 约束: 只使用已声明的 input 信号
        {{ llm_body }}
        // === LLM_FILL_END ===
    endtask
endclass
```

**模板注册表：**

```python
PROMPT_REGISTRY = {
    "verify/gap_directed_test": PromptTemplate(
        path="templates/verify/gap_directed_test.j2",
        version="v3.2.1",
        output_schema=GapDirectedBodySchema,
        token_budget=800,
        fallback="neutralize",
    ),
    "debug/root_cause_hypothesis": PromptTemplate(
        path="templates/debug/root_cause.j2",
        version="v2.1.0",
        output_schema=RootCauseSchema,
        token_budget=1500,
        fallback="escalate_human",
    ),
    "coverage/gap_classification": PromptTemplate(
        path="templates/coverage/gap_classify.j2",
        version="v1.4.2",
        output_schema=GapClassificationSchema,
        token_budget=1024,
        fallback="rule_based",
    ),
}
```

### 9.4 Layer 2：编译层

```python
class PromptCompiler:
    def compile(self, template_key: str, state: VerificationState) -> CompiledPrompt:
        tpl = PROMPT_REGISTRY[template_key]

        # 1. 提取槽位（严格降采样）
        slots = self._extract_slots(template_key, state)

        # 2. Token 预算检查
        rendered = tpl.render(**slots)
        token_count = count_tokens(rendered)
        if token_count > tpl.token_budget:
            slots = self._downsample(slots, tpl.token_budget)
            rendered = tpl.render(**slots)
            token_count = count_tokens(rendered)

        # 3. 注入版本元数据
        return CompiledPrompt(
            text=rendered,
            template_key=template_key,
            template_version=tpl.version,
            template_hash=tpl.hash,
            token_count=token_count,
            slots_hash=sha256(json.dumps(slots, sort_keys=True)),
        )
```

**铁律三的工程化——按语义选，不按长度截：**

```python
def _extract_slots(self, template_key, state):
    if template_key == "coverage/gap_classification":
        gaps = state["gap_vectors"][:10]
        summary = [{"bin": g["bin"], "reason_hint": g["reason"],
                    "req_id": g["req_id"], "signal": g["signal"]} for g in gaps]
        text = json.dumps(summary, ensure_ascii=False)
        if len(text.encode()) > 1024:
            summary = summary[:5]
        return {"gap_summary": json.dumps(summary, ensure_ascii=False)}
```

### 9.5 Layer 3：执行层

```python
class PromptExecutor:
    def execute(self, template_key: str, state: VerificationState) -> PromptResult:
        # 1. 编译
        cp = self.compiler.compile(template_key, state)

        # 2. 调用 LLM（确定性优先）
        raw = self.llm.invoke(
            cp.text,
            temperature=0.0,
            seed=state["run_seed"],
        )

        # 3. 结构化解析（强制 schema）
        tpl = PROMPT_REGISTRY[template_key]
        try:
            parsed = tpl.output_schema.parse_raw(raw.content)
        except ValidationError as e:
            return self._fallback(template_key, state, reason=f"schema_error: {e}")

        # 4. 工具回执绑定（铁律一）
        receipt = self._bind_tool_receipt(template_key, parsed, state)
        if not receipt:
            return self._fallback(template_key, state, reason="no_tool_receipt")

        # 5. 记录调用
        invocation = {
            "template_key": template_key,
            "compiled_receipt": compiled_prompt_receipt(cp),
            "model": self.llm.model_name,
            "temperature": 0.0,
            "seed": state["run_seed"],
            "output_hash": sha256(raw.content),
            "tool_receipt_id": receipt["id"],
            "timestamp": now_iso(),
        }
        self.store.put(("prompts", "invocations"), key=invocation_id(), value=invocation)

        return PromptResult(parsed=parsed, receipt=receipt, invocation=invocation)
```

### 9.6 结构化输出：Schema 是硬约束

```python
class GapDirectedBodySchema(BaseModel):
    input_drives: list[InputDrive] = Field(..., min_items=1, max_items=10)
    expected_output_transition: str
    reasoning: str = Field(..., max_length=200)


class InputDrive(BaseModel):
    signal: str = Field(..., regex=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    value: str
    at_cycle: int = Field(..., ge=0)

    @validator("signal")
    def signal_must_exist(cls, v):
        if v not in declared_inputs:
            raise ValueError(f"undeclared signal: {v}")
        return v
```

**关键**：`signal_must_exist` 把“LLM 幻觉信号”挡在 schema 层，LLM 不可能生成不存在的信号。

### 9.7 回退链

```
LLM 调用
  ↓
Schema 解析失败 → 规则回退
  ↓
Schema 成功但工具回执失败 → 空实现回退（neutralize）
  ↓
工具回执成功 → 采纳
```

每种模板的回退策略在注册表声明：

| 模板 | Schema 失败 | 工具失败 | 最终回退 |
|---|---|---|---|
| `verify/gap_directed_test` | 规则生成基础激励 | neutralize | 空 sequence |
| `debug/root_cause_hypothesis` | 规则分类 | escalate_human | 人工 |
| `coverage/gap_classification` | 规则归因 | 规则归因 | 规则归因 |
| `model/reference_model` | 模板渲染 | 模板渲染 | 模板渲染 |

### 9.8 变异重试

失败后**不重复相同 prompt**，而是注入错误信息 + 变异：

```python
def retry(self, template_key, state, previous_result, error):
    state["retry_context"] = {
        "attempt": state["retry_count"] + 1,
        "previous_output": previous_result.raw,
        "error": error,
    }
    cp = self.compiler.compile(template_key, state)
    return self.execute_compiled(cp, state)
```

模板对应增加重试槽位：

```jinja
{% if retry_context %}
// === RETRY CONTEXT ===
// 上次输出: {{ retry_context.previous_output }}
// 失败原因: {{ retry_context.error }}
// 请基于失败原因修正，不要重复相同错误。
{% endif %}
```

重试有次数上限（`max_retries`），超限后走最终回退。

### 9.9 与证据链的绑定

每次 LLM 调用产生一条 `invocation`，进 `("prompts", "invocations")` namespace。与哈希链关联：

```
哈希链记录 → tool_receipt_id → invocation → template_hash → 模板版本
```

**任意一次 LLM 调用，都可追溯到模板版本、模型、温度、seed、输出哈希、工具回执。** 这是“可复现”的根。

---

## 10. HITL 与人机治理

### 10.1 审批门控配置

```python
graph = builder.compile(
    checkpointer=checkpointer,
    interrupt_on={
        "signoff_verification": {"allowed_decisions": ["approve", "reject"]},
        "exclude_proposal":     {"allowed_decisions": ["approve", "edit", "reject"]},
        "rtl_refactor":         {"allowed_decisions": ["approve", "edit", "reject"]},
    },
)
```

### 10.2 审批节点（带签名与 RBAC）

```python
def human_review_node(state: VerificationState) -> dict:
    from langgraph.types import interrupt

    request = {
        "phase": state["current_phase"],
        "artifact": pick_artifact_for_review(state),
        "tool_receipts": state["tool_receipts"],
        "risk_level": assess_risk(state),
        "required_role": role_for_phase(state["current_phase"]),
    }

    decision = interrupt(request)   # 挂起，等外部 API 恢复

    # RBAC + 签名校验
    if not rbac.check(decision["user"], request["required_role"]):
        raise PermissionError(f"{decision['user']} lacks role")

    signature = sign(decision["user"], request, decision["action"])

    state["approval_history"].append({
        "user": decision["user"],
        "role": request["required_role"],
        "action": decision["action"],
        "signature": signature,
        "timestamp": now_iso(),
    })

    if decision["action"] == "approve":
        return {"pending_approval": None}
    if decision["action"] == "edit":
        return {"generated_sva": decision["edited"], "pending_approval": None}
    return {
        "error_log": state["error_log"] + [f"rejected: {decision.get('feedback')}"],
        "retry_count": state["retry_count"] + 1,
        "pending_approval": None,
    }
```

### 10.3 人工门控点

| 门控点 | 触发条件 | 权限 |
|---|---|---|
| 签核判定 | `CONVERGE` 或人工升级 | verification_lead |
| 排除覆盖点 | `unreachable` 且 ≥3 次重构仍 0% | verification_lead |
| RTL 重构 | `REFACTOR_RTL` 且 golden guard 通过 | design_lead |
| 根因确认 | debug 子图提出根因假设 | design_lead / verification_lead |

---

## 11. 持久化架构

### 11.1 Checkpointer vs. Store

| 维度 | Checkpointer | Store |
|---|---|---|
| 持久化内容 | 图状态快照 | 应用定义的键值数据 |
| 作用域 | 单个线程 | 跨线程 |
| 记忆类型 | 短期、线程作用域 | 长期、跨线程 |
| 用途 | 对话连续性、HITL、时间旅行、容错 | 用户偏好、证据链、知识图谱 |
| 访问方式 | graph config 中传 thread_id | 节点或应用代码读写 |

### 11.2 Store Namespace 规划

```python
NS = {
    "hash_chain":      ("evidence", "hash_chain"),                    # append-only
    "domain_evidence": ("evidence", "domain", "{run_id}"),
    "manifest":        ("evidence", "manifest", "{run_id}"),
    "golden":          ("golden", "baseline"),
    "kg":              ("kg", "verification"),                        # V2
    "cross_project":   ("knowledge", "cross_project", "{project_id}"),# V4
    "policies":        ("policies",),                                 # V3
    "experience":      ("experience", "debug"),
    "coverage_exp":    ("experience", "coverage"),
    "prompt_templates":("prompts", "templates"),
    "prompt_invocations":("prompts", "invocations"),
}
```

### 11.3 生产配置

```python
checkpointer = PostgresSaver.from_conn_string(PG_DSN)
checkpointer.setup()   # 创建带索引的表

store = PostgresStore.from_conn_string(PG_DSN)

graph = builder.compile(checkpointer=checkpointer, store=store)
```

**注意事项**：
- `thread_id` 长度 <255 字符，使用 UUID 或哈希
- 长对话设置检查点保留策略，定期清理
- `MemorySaver` 仅用于开发
- Store 定期归档冷数据，hash_chain append-only 但可冷存储

---

## 12. 成长层：V2 / V3 / V4

### 12.1 V2：验证知识图谱（KG）

**把「需求→功能→RTL 模块→信号→覆盖率 bin→测试→bug→fix」显式建模成可遍历的图。**

```python
class VerificationKG:
    NS = ("kg", "verification")

    def trace_uncovered(self, bin_id: str) -> dict:
        """BFS 从 bin 溯源到需求/测试/bug"""
        return bfs_trace(store, self.NS, start=f"bin:{bin_id}", max_depth=6)


@tool
def trace_uncovered(bin_id: str) -> dict:
    return KG.trace_uncovered(bin_id)
```

**价值**：决策层从“看覆盖率数字”进化到“看语义坐标”。

```
coverage agent 发现: acc_value[15] toggle missing
    ↓ trace_uncovered
REQ_GEMM_001 ← GEMM_MAC ← mac_array ← acc_value[15] ← overflow_corner ← gemm_overflow_test
    ↓
决策: RELAX_CONSTRAINT（已有测试但约束过紧，不是没测）
```

### 12.2 V3：决策学习层

**硬失败走 Rule Engine，软决策走 RL Policy。**

```python
class DecisionBrain:
    def __init__(self, policy_path: str = None):
        self.rule = RuleEngine()
        self.rl = load_q_table(policy_path) if policy_path else None
        self.rl_weight = 0.0   # 冷启动为 0，样本足够后增加

    def decide(self, state) -> str:
        hard = self.rule.check_hard(state)   # 编译错/比对错
        if hard:
            return hard
        rule_action = self.rule.decide_soft(state)
        if self.rl and self.rl_weight > 0:
            rl_action = self.rl.predict(state)
            return self._blend(rule_action, rl_action, self.rl_weight)
        return rule_action
```

**奖励信号**：覆盖率 delta 当 reward。**先跑通轻量 Q-learning，验证“学习有用”，再升级 DQN。**

### 12.3 V4：跨项目知识复用

```python
def cross_project_lookup(bug_category: str, project_id: str) -> list:
    """
    按 category 查其它项目的同类 bug + 修复。
    用 KG 的节点/边做语义检索，而非字符串匹配。
    """
    hits = []
    for ns in store.list_namespaces(prefix=("knowledge", "cross_project")):
        if ns[-1] == project_id:
            continue
        hits.extend(store.search(ns, query={"category": bug_category}, limit=3))
    return hits
```

**项目 B 遇到 `model_mismatch` → 复用项目 A 的 saturate 修复。**

---

## 13. 通信层（A2A）

### 13.1 保留外层 JSON-RPC

跨进程、跨语言、EDA 工具适配器的边界不变：

```python
class A2AClient:
    def send(self, task: dict) -> dict:
        """tasks/send，task.reason 为必填字段"""
        assert "reason" in task, "task.reason is mandatory for audit"
        return rpc_call("tasks/send", task)
```

### 13.2 LangGraph `Command` 与 A2A 的映射

```python
def verify_subgraph_node(state):
    result = a2a.send({
        "agent": "verify",
        "action": "generate_gap_test",
        "gap_vectors": state["gap_vectors"],
        "reason": "coverage gap: unstimulated toggle",
    })
    return Command(
        update={"generated_stimulus": result["artifacts"]},
        metadata={"task": {"reason": result["reason"], "agent": "verify"}},
    )
```

**关键**：`Command.metadata.task.reason` 和 RPC 的 `task.reason` 是同一语义字段，在 `evidence_chain_node` 里统一写入哈希链。

---

## 14. 迁移路线图

### Phase 0：准备（1 周）

- 搭建 Postgres Checkpointer + Store
- 定义 `VerificationState` schema
- 建立分支 `refactor/langgraph-migration`
- 删除旧编排层代码，git commit 记录删除

### Phase 1：主图骨架（2 周）

- 实现 StateGraph 主图 + 空节点
- 实现 `eda_gate` / `evidence_chain` / `decision_router`
- 单元测试：8 动作优先级、铁律门控、哈希链

### Phase 2：子图迁移（3 周）

- design / model / verify / ops / coverage 逐个迁移为子图
- 每个子图迁完即跑 golden 用例对比
- 差异记录到 `MIGRATION_LOG.md`

### Phase 3：守门人 + HITL（2 周）

- debug / audit 子图迁移
- `golden_guard` / `exclude_gate` / `human_review` 接入
- RBAC + 签名层对接

### Phase 4：V2/V3/V4 叠加（2 周）

- KG 建图 + `trace_uncovered`
- DecisionBrain 接入 `decision_dispatch`
- 跨项目 Store namespace 迁移

### Phase 5：切换与演练（1 周）

- Shadow 模式跑同一 IP，对比参考实现
- 演练回滚：切回上一个稳定 LangGraph 版本 tag

### Phase 6：旧代码退役（1 周）

- 旧编排层已删除，确认无残留引用
- `abandoned/`（7.6M）git 删除并 commit
- 文档更新

**总周期**：约 11 周

---

## 15. 验收标准

### 15.1 功能验收

- [ ] 签核报告字段与参考实现一致
- [ ] 证据链哈希链可校验，任一环篡改可检测
- [ ] 8 动作优先级单元测试 100% 通过
- [ ] 铁律一：所有 LLM 产物有 EDA receipt，无 receipt 抛异常
- [ ] 铁律二：ucdb 哈希归档可回滚比对
- [ ] 铁律三：LLM 上下文 token 数 < 2KB/次覆盖率分析
- [ ] HITL：审批记录带签名，RBAC 校验生效
- [ ] 黄金基线：`REFACTOR_RTL` 前强制跑，<100% 拒绝
- [ ] 提示词链：每次 LLM 调用可追溯模板版本、seed、输出哈希

### 15.2 非功能验收

- [ ] 单 run 时长不超过参考实现 1.2 倍
- [ ] Checkpointer 恢复成功率 100%
- [ ] 哈希链写入延迟 < 50ms/条
- [ ] 回滚演练成功，切换时间 < 5 分钟
- [ ] `test_same_seed_same_output` 通过

### 15.3 治理验收

- [ ] 任意签核报告可追溯到：需求→设计→验证→执行→签核五层证据
- [ ] 任意文件修改可追溯到：`task.reason` + agent + 前一哈希
- [ ] 任意排除项可追溯到：工程师签名 + 审计哈希
- [ ] 任意决策可追溯到：动作 + gap 向量 + 时间戳
- [ ] 任意 LLM 调用可追溯到：模板版本 + 模型 + seed + 工具回执

---

## 16. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| LangGraph 版本升级破坏 API | 编排层不可用 | 锁定版本，`pyproject.toml` pin |
| Checkpointer 存 Postgres 性能 | 大规模 run 慢 | 定期清理旧 checkpoint，保留最近 N 轮 |
| `interrupt` 挂起期间进程重启 | HITL 丢失 | Checkpointer 持久化，恢复后自动 resume |
| 子图 state schema 不兼容 | 迁移期数据错乱 | 每子图独立 schema，主图做转换 |
| `Command.metadata` 被覆盖 | `task.reason` 丢失 | 证据链节点从 RPC 日志二次校验 |
| Store 膨胀 | 存储成本 | hash_chain 定期归档冷存储 |
| RL 策略输出非法动作 | 路由失败 | DecisionBrain 输出强制校验在 8 动作集合内 |
| 跨项目检索污染当前项目 | 错误修复建议 | namespace 隔离 + 相似度阈值门控 |
| 提示词模板变更破坏旧 run 回放 | 不可复现 | 模板版本化存 Store，回放时拉对应版本 |
| LLM 输出非法 JSON | 解析失败 | Pydantic schema + 回退链 |

---

## 17. 附：完整主图代码骨架

```python
# ===== 导入 =====
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore
from langgraph.types import Command, interrupt

# ===== 持久化 =====
checkpointer = PostgresSaver.from_conn_string(PG_DSN)
checkpointer.setup()
store = PostgresStore.from_conn_string(PG_DSN)

# ===== 主图 =====
builder = StateGraph(VerificationState)

# ---- 生产者 ----
builder.add_node("design", build_design_subgraph())
builder.add_node("model",  build_model_subgraph())
builder.add_node("verify", build_verify_subgraph())

# ---- 执行者 ----
builder.add_node("ops",      build_ops_subgraph())
builder.add_node("coverage", build_coverage_subgraph())

# ---- 守门人 ----
builder.add_node("debug", build_debug_subgraph())
builder.add_node("audit", build_audit_subgraph())

# ---- 贯穿层 ----
builder.add_node("eda_gate",          eda_gate_node)
builder.add_node("evidence_chain",    evidence_chain_node)
builder.add_node("golden_guard",      golden_guard_node)
builder.add_node("exclude_gate",      exclude_gate_node)
builder.add_node("human_review",      human_review_node)
builder.add_node("decision_dispatch", decision_dispatch_node)

# ---- 边 ----
builder.add_edge(START, "design")
builder.add_edge("design", "eda_gate")
builder.add_edge("eda_gate", "model")
builder.add_edge("model", "verify")
builder.add_edge("verify", "eda_gate")
builder.add_edge("eda_gate", "ops")
builder.add_edge("ops", "coverage")

builder.add_conditional_edges(
    "coverage",
    pre_decision_router,
    {"golden_guard": "golden_guard",
     "exclude_gate": "exclude_gate",
     "decide":       "decision_dispatch"},
)

builder.add_conditional_edges(
    "decision_dispatch",
    decision_router,
    ACTION_TO_NODE,
)

builder.add_edge("golden_guard", "design")
builder.add_edge("exclude_gate", "audit")
builder.add_conditional_edges("debug", decision_router, ACTION_TO_NODE)

builder.add_edge("audit", "evidence_chain")
builder.add_edge("evidence_chain", END)

# ---- 编译 ----
graph = builder.compile(
    checkpointer=checkpointer,
    store=store,
    interrupt_on={
        "signoff_verification": {"allowed_decisions": ["approve", "reject"]},
        "exclude_proposal":     {"allowed_decisions": ["approve", "edit", "reject"]},
        "rtl_refactor":         {"allowed_decisions": ["approve", "edit", "reject"]},
    },
)
```

---

## 18. 一句话总结

**LangGraph 替换的是“编排引擎 + 状态持久化 + HITL 挂起机制”，不替换“铁律、证据链、决策优先级、RBAC、签名、提示词版本化”。**

迁移的成败标准不是“用了 LangGraph”，而是“签核报告的每一个字段，仍然可追溯到哈希链里的某一环；每一次 LLM 调用，仍可追溯到模板版本、seed 和工具回执”。

**骨架由 LangGraph 提供，治理由 SignOffAI 自研保留。LLM 仍然只做骨架内的完形填空。**