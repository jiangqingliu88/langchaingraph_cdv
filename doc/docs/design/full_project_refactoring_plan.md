# SignOffAI 全项目重构方案

> **配套文档**
> - `AI驱动芯片验证全栈闭环架构设计文档.md` —— 目标架构（To-Be），本文称「架构图」
> - `PROJECT_STATUS.md` —— 进度快照
> - `CLAUDE.md` —— 项目愿景与铁律
>
> **本文定位**：把架构图上的每一根线，逐条对到代码上；**对不上的地方，给出重构路径**。
> 本文所有结论都带 `file:line` 证据，可逐条复核。凡标 ❌ 的，是代码里**不存在**，不是"做得不够好"。

---

## 0. 一句话结论

**架构图描述的是目标态，不是现状。**

现状是：Layer 0/1 的骨架——「EDA 唯一真理」与「ucdb 版本固化」——**真实且可用**，是项目最值钱的资产；但 Layer 2 的**证据链只做了一半**；Layer 3 的「LangGraph StateGraph 主图」**根本不存在**，实际是一个 900 行命令式 async 函数；Layer 4 的人机审批**默认自动放行**；跨 run 成长层（V2/V3/V4）整体是**CLI 孤岛，未接进主循环**。

因此本次重构的主线**不是**"把代码改成架构图"，而是：

> **先把已经真实存在的三个资产（EDA 门控、ucdb 哈希固化、决策规则引擎）从"每个 agent 各自实现一份"收敛成"唯一的工程骨架"，再把编排从命令式函数换成图，最后才谈跨 run 成长。**

顺序不可颠倒。在状态对象还是裸 `dict` 的时候套上 LangGraph，只是给 `dict` 包一层壳，收益为负。

---

## 1. 判定口径

| 标记 | 含义 |
|---|---|
| ✅ | 已实现，且有真实调用点（在产线路径上） |
| ⚠️ | 部分实现 / 实现存在但被旁路 / 默认配置下不生效 |
| ❌ | 声明存在，代码里**没有** |
| 💀 | 有代码但**零调用**（死代码） |

---

## 2. 差距矩阵（先看这个）

| # | 架构图声称 | 代码事实 | 判定 | 证据 |
|---|---|---|---|---|
| 1 | Layer 3 是 **LangGraph StateGraph 主图** | `langgraph` 无依赖、无 import、无 `StateGraph`/`Command`/`add_node`。编排是单个函数 `run_closed_loop` | ❌ | `l2_orchestration/execution.py:251-877` |
| 2 | `Command(update=..., goto=...)` 统一信道 | 无。阶段跳转 = 语句顺序 + `await` 顺序 | ❌ | 同上 |
| 3 | `interrupt_on` 人工审批 | 无 `interrupt`。`ApprovalGate` 存在，但**默认 `auto` = 全部放行**，且调用点被 `except` 吞掉 | ⚠️ | `governance/approval.py:81-100,193`；`cli/commands.py:166`；`execution.py:655-656` |
| 4 | Checkpointer 短期状态 / 时间旅行 | 无 `thread_id`、无 `checkpoint`。`--resume <id>` **打印后丢弃 ID** | ❌ | `cli/commands.py:126-131` |
| 5 | Store 长期知识（命名空间） | 无 `Store` 抽象。实际是 5 个裸 `sqlite3` + 若干 JSON，**且路径基准不一致** | ⚠️ | `.signoffai/*.db`（CWD 相对）vs `execution.py:4236`（output 相对） |
| 6 | **tool_receipts 结构化回执** | 全仓 `receipt/回执` **0 处**。`ToolAuditor` 仅内存，`export_audit_log()` 无落盘调用 | ❌ | `tool_protocol.py:537-582`；`tool_hub.py:331` |
| 7 | 8 动作**严格优先级**，纯函数 | 8 个动作名齐全，决策层确实无 LLM ✅；但优先级是 `if/elif` 控制流，**不是可排序表**；`RETRY_ENV` 有 handler 却**永不被 `decide()` 发出** | ⚠️ | `decision_engine.py:82-195`（分支）/ `:338-347`（表） |
| 8 | 铁律一：EDA 是唯一真理 | 真实且 fail-closed，**但被复制成 4+ 份独立实现**，无统一咽喉；`ToolResult` 无 provenance 字段 | ⚠️ | 见 §5.2 |
| 9 | 铁律二：ucdb 版本固化 | **完整**：分块 SHA256 + 硬链接归档 + `verify_reproducible()` 回滚比对 + git tag | ✅ | `l1_infrastructure/infrastructure.py:290-437` |
| 10 | 铁律三：LLM 只读 <1KB 降采样 | "只读 text 汇总、绝不读 ucdb" 成立 ✅；但 **"<1KB" 上限无任何强制**，无截断逻辑 | ⚠️ | `agents/coverage/main.py:188-200` |
| 11 | Layer 2 五层证据链 L1–L5 | `config/evidence_schema.yaml` 规格完整，**Python 零引用**（无 loader/validator/数据类） | ❌ | `config/evidence_schema.yaml` vs 全仓 grep 无匹配 |
| 12 | 哈希链证据包 | **两条链互不相链**：文件级 `evidence_chain.json`（每 module 一条）与 DB `audit_logs`（全局）；无 HMAC；`file_audit.verify()` **只验内存，不落盘复核** | ⚠️ | `evidence/file_audit.py:53-59,92-104`；`persistence/repository.py:171-281` |
| 13 | golden_guard 回归守卫（<100% 拒绝改设计） | **真实且结构性阻断**（`break` 出主循环，`design_fix` 不执行） | ✅ | `golden_baseline.py:110-138`；`execution.py:731-743` |
| 14 | exclude_gate 允许放弃（人工签名） | **真实**：四步闭环 `proposed→approved`，仅 APPROVED 影响覆盖率，签名写入 SHA256 链 | ✅ | `l4_memory/exclude_registry.py:105-169`；`execution.py:519-523` |
| 15 | V2 知识图谱 | **真实且接线**：design agent 写入，decision engine 读取喂 Observation | ✅ | `l3_decision/knowledge/{graph,persistence}.py`；`agents/design/main.py:111`；`decision_engine.py:390-391` |
| 16 | V3 决策学习（RL Q-learning） | 代码真实，但**极薄**：`.signoffai/rl_policy.json` 只有 **4 条 Q、1 个 state**，等价单臂老虎机 | ⚠️ | `brain/rl_policy.py`；`.signoffai/rl_policy.json` |
| 17 | V4 跨项目知识复用 | 查询有实现（`lookup_cross_project_bugs/fixes`）；但"签核证据包交换" `marketplace.py` **零调用** | ⚠️ | `knowledge/cross_project.py:21,43`；`marketplace.py:31,51,62` 💀 |
| 18 | L5 进化：蒸馏 + 灰度回归后上线 | 蒸馏仅在 **CLI 可达**，`get_live_*()` 在主循环**零调用**；"灰度回归验证失败则回滚"是 docstring 声称，**无回归执行** | ⚠️ | `l5_evolution/distillation.py:187-197,214-234` |

**一句话读法**：18 项里 ✅ 只有 3 项（ucdb 固化、golden guard、exclude gate、KG 算 3.5 项），❌ 5 项，其余 ⚠️。**架构图的"骨架"部分比"智能"部分扎实得多**——这恰好印证了 CLAUDE.md 里"差异化不在 AI 更聪明"的判断。

---

## 3. 现状审计（逐层）

### 3.1 Layer 0 · 工具层 —— 协议存在，但多数工具绕过协议

**存在的**：`ITool` 协议（`tool_protocol.py:273-348`）、`ToolManifest`（含 `input_schema`/`output_schema`/`risk_level`，`:90-176`）、`ToolHub` 单例（`tool_hub.py:36-441`）、`ToolSandbox`、`CLIToolAdapter`。设计质量不差。

**问题清单**：

| 问题 | 事实 | 证据 |
|---|---|---|
| 注册覆盖率低 | `src/tools/` 有 **49** 个 `@tool` 函数，`_load_builtin_tools()` 只注册 **~29**（uvm_tools 9 + agent_tools 20）。assertion/coverage/debug/doc/reuse/spec/cmodel **七个包完全未注册** | `tool_hub.py:410-441` |
| 旁路是系统性的 | **≥33 处** `from src.tools...` 直接 import 成普通函数调用，不经过 `ToolHub.invoke()`；因此**不产生任何审计** | `agents/verify/main.py:142,222`；`agents/coverage/main.py:103`；`agents/design/main.py:52,110,214,326` 等 |
| 甚至绕过公共门面 | CLI 直接 import **私有** helper `_tools_old._run_compile_check` | `cli/commands.py:3161,3191` |
| 两套风险枚举 | `ToolRisk`(enum, `tool_protocol.py:44`) vs `RiskLevel`(string, `tool_system.py:52`)，靠 `_OldToolAdapter` 桥接 | `tool_hub.py:448` |
| 风险分级不生效 | `ToolSandbox.check_permission()` 取到 `perm` 后**只用 `max_timeout_s`，从不因 risk 拒绝**；且 sandbox **默认 None**，包裹调用被 `try/except: pass` | `tool_sandbox.py:110-142`；`tool_hub.py:194`；`tool_protocol.py:370,418-419` |
| `risk_limit` 过滤零调用 | `get_llm_tools(risk_limit=)` 无任何 caller | `tool_hub.py:277-294` |
| `schema.yaml` 无人读 | `uvm_tools/tool_*/schema.yaml` **9 个文件**无 Python 读取方（仅 `agents/base.py:387-399` 读另外 5 个路径，用于校验 **agent 输出**而非 tool 输入） | grep `schema.yaml` |
| 无 MCP | `tool_protocol.py:5` 自述"对标 Claude Code MCP"，即**启发自**，非实现。无 `mcp` 依赖、无 server | — |

### 3.2 Layer 1 · 持久化层 —— 表建全了，但证据表是空的

- 主库 `ic_verification.db`：**33 表 / 36 model**（`l4_memory/persistence/models.py`），迁移 `1.0→2.1` 带 `schema_versions` 校验表 ✅
- **但**：`signoffs=0`、`artifacts=0`、`evidence_links=0`、`verification_bugs=0`（实测行数）。即**证据绑定层 schema 完备但从未被写入**——`create_signoff()`（`repository.py:318`）与 CLI 路径（`commands.py:514-516`）都存在，说明是"接线没走通"，不是"没写"。
- **5 个旁路 DB**（裸 `sqlite3`，不走 ORM）：`debug_experience` / `coverage_experience` / `exclude_registry` / `ip_registry` / `testcase_registry`，全在 `.signoffai/`。
- **路径基准不一致**（真 bug）：5 个 store 用 `Path(".signoffai")`（**CWD 相对**），而 `execution.py:4236` 用 `Path(output_dir)/".signoffai"/"exclude_registry.db"`（**output 相对**）——同一个逻辑 store，两个物理路径，换目录跑就分裂。
- `ArtifactRegistry.prev_hash`（`artifacts.py:41`）声明了却从不读写 → 💀 死字段，容易误导人以为有链。
- `verify_audit_chain()`（`repository.py:228-281`，实现质量不错，查索引连续性 + 前后哈希 + 自哈希）**全仓零调用** 💀。

### 3.3 Layer 2 · 纵向贯穿层 —— 三铁律两条半真实

**铁律一（EDA 唯一真理）**：方向正确，但**没有唯一咽喉**，同一件事被写了 4+ 遍：

| 实现 | 位置 | 问题 |
|---|---|---|
| 权威实现 | `regression_tools/.../regression_runner.py:66` | `status = "PASS" if errors==0 and returncode==0 else "FAIL"` ✅ |
| 复制品 1 | `tools/lib/compile.py:15-55` | 与复制品 2 **逐字节重复**（同 filelist、同 top name、同 PASS 判据、同日志路径、同 score 公式） |
| 复制品 2 | `tools/uvm_tools/_tools_old.py:1041-1075` | CLI 用的是**这一份私有实现** |
| 复制品 3 | `tools/lib/loopback.py:188-215` | 自己拼 `vsim` 命令行 + 3 次 autofix 重试，不过 `RegressionRunner` |
| 复制品 4 | `tools/debug_tools/main.py:803-818` | `subprocess.run(["bash", ...])`，**判 PASS 时忽略 `returncode`**（只看 UVM_FATAL/ERROR），与权威判据**不一致** |

另有 `coverage_tools/main.py:29` 直接 `subprocess.run([vcover, ...])` 绕过 `coverage_backend.py`。
**后果**：LLM 生成的 RTL / gap sequence 确实被 `vlog` 挡在门外（`agents/verify/main.py:211-216` → `_neutralize_gap_seq()` 物理覆写为空类；`agents/design/main.py:81-83` 编译失败即丢弃）✅ ——但**这个门控是"每个 agent 各自记得做"**，不是结构保证。`ToolHub.invoke()` 层**完全没有 EDA 前置条件**，`ToolResult`（`tool_protocol.py:179-188`）也没有 `verified_by` 字段，所以"纯 LLM 推理的 `success=True`"和"EDA 验证过的 `success=True`"**在类型上不可区分**。

**铁律二（ucdb 固化）**：✅ 完整且设计对（分块读、`os.link` 硬链接失败回落 `copy2`）。唯一瑕疵：coverage agent 另有一份 `Path(ucdb_path).read_bytes()`（`agents/coverage/main.py:195`）——**一次性读进内存**，几十 GB ucdb 会炸，与 L1 的分块实现不一致。

**铁律三（LLM 只读降采样）**：机制方向对（产出 `coverage_summary.txt` 供 LLM 读），但"<1KB"是**文档承诺，代码无强制**。

**证据链**：两条链，各干各的。

| | 文件级链 | DB 级链 |
|---|---|---|
| 位置 | `<output_root>/docs/evidence_chain.json` | `ic_verification.db` `audit_logs` |
| 哈希 | `sha256(json{file,reason,agent,diff,content_hash} + prev_hash)` | `sha256(f"{chain_index}\|{id}\|{user}\|...\|prev_hash}")` |
| 强度 | 弱：`verify()` 只验内存，不回读磁盘；无索引连续性检查（**删掉尾部记录不可检测**） | 强：查索引连续性 + 前后哈希 + 自哈希 |
| 范围 | **每 module 一条链**（非全局） | 全局 |
| 调用 | `execution.py:770-788` 写入 | 142 行真实数据 |
| 交叉引用 | ❌ 无 | ❌ 无 |

**无 HMAC / 无签名**：整文件重写 + 重算链，两条链都发现不了。

**通信**：A2A / JSON-RPC 2.0 库**写得很完整**（`communication/jsonrpc.py`：`AgentCard`/`Task`/`tasks/send`/`discover`），但**唯一消费者是 `cli/repl.py:51-52`**——只用来**读 `AGENT_CARDS` 做展示**。`run_closed_loop` 从不构造 `A2ADispatcher`。即：A2A 是个未接线的成品。

### 3.4 Layer 3 · 编排层 —— 900 行命令式函数，图执行器在旁边闲置

**实际形态**（`l2_orchestration/execution.py`）：

```
run_closed_loop()                                   # :251-877，约 626 行
├── ctx = {}                                        # :283  ← 裸 dict 作共享状态
├── design → model → verify → env_arch_check        # :387,397,398（硬编码顺序）
└── for round_num in range(max_rounds):             # :450  ← 这就是"主图"
    ├── _run("ops_r{n}")                            # :452
    ├── 门控分支                                    # :490-500
    ├── _run("coverage_r{n}")                       # :500
    ├── engine.decide(obs) → action                 # :609/611/613
    ├── governor.before_action() / approval_gate    # :616-656
    └── if/elif action.action_type: ...             # :669-765
└── _run("audit")                                   # :768
```

| 架构图声称 | 实际 |
|---|---|
| StateGraph 节点 + 条件边 | **无图对象**。拓扑由语句顺序表达 |
| 携带 state 的边 | `ctx.update(data)` —— agent 返回的整个 dict **原地合并**，无 schema、无校验，**agent 之间可静默覆盖键** |
| 图的状态类型 | 无。`ctx: dict`。`AgentResult(BaseModel)` 只是单次调用信封，不是跨阶段状态 |
| 条件路由 | `if/elif` 十连 |
| Checkpoint | 无 |

**旁边闲置的两个现成零件**（重构时直接用，别重写）：
- `PipelineScheduler.run_dag()`（`pipeline_scheduler.py:120`）—— **已实现 Kahn 拓扑排序执行器** + `Stage` 数据类，但**主循环从不调用它**（只用了 `waterfall()` 跑多模块）。
- `ContextStore` + `_CONSUMES_TOPOLOGY`（`context/context.py:24-54`）—— 设计好的"配置/状态/数据"三层通道，**主路径不用**。

**决策层本身是干净的** ✅：`CoverageDrivenDecisionEngine.decide()` 是 `Observation → Action` 的**同步纯函数**，全目录无 LLM 客户端 import、无网络 IO。这是架构图里"无 LLM"那一条**完全属实**的部分。

但同一份决策被**两套动作词汇表**切开：

| | 动作集 | 位置 |
|---|---|---|
| 规则引擎 | 8 个（`COMPILE_RETRY`/`UPDATE_MODEL`/`GENERATE_DIRECTED_TEST`/`EXPAND_SEEDS`/`REFACTOR_RTL`/`RETRY_ENV`/`RELAX_CONSTRAINT`/`CONVERGE`） | `decision_engine.py:338-347` |
| RL 策略 | 4 个 `SOFT_ACTIONS`（不含 `CONVERGE`） | `brain/rl_policy.py:35-36` |

且 `DecisionBrain` 在 `has_experience()` 为真时**用 RL 结果整体覆盖规则结果**（`brain/decision_brain.py:86-93`）→ **RL 可以在优先级条件全不满足时发出 `RELAX_CONSTRAINT`/`REFACTOR_RTL`**，绕过 §2 表格里那张"严格优先级"。这与"8 动作严格优先级，无 LLM"的目标态直接冲突。

次要问题：`decide()` 的 docstring（`decision_engine.py:44`）只列 5 个动作，与代码的 8 个不一致；`rl_policy.py` 模块 docstring 说 5 个（含 `CONVERGE`），代码注释说排除 `CONVERGE`——**两份文档都比代码旧**。

### 3.5 Layer 4 · 人工审批层 —— 通道有四条，默认全开

| 通道 | 机制 | 默认行为 |
|---|---|---|
| `ApprovalGate` | `APPROVE/REJECT/SKIP/REVIEW`，**只对 `REFACTOR_RTL` + `UPDATE_MODEL` 两个动作生效** | ⚠️ `--approval` 默认 **`auto`** → `requires_approval()` 恒 False → `ask()` 合成 APPROVE 记录。**等于没有人工** |
| `Governor` 升级 | `EscalationConsole`，返回 `retry`/`abort` | 异常时 fail-closed 到 `abort` ✅ |
| 手动覆盖 | `Intervention("output")` 写 `override_action`，CLI `vagent govern override <ACTION>` | 主动使用才生效 |
| 落盘记录 | `vagent approve/reject` → `approval.json`；`vagent signoff *` | 存在 |

两个削弱点：审批的 `except` 只记日志（`execution.py:655-656`）；`ApprovalDecision.REVIEW`（`approval.py:32`）**声明了但 `ask()` 永不产生**。

**注意区分**：`agents/audit/main.py:99-123` 输出的 `APPROVED`/`CONDITIONAL` **是分数推出的静态判定，不是人的决定**。签核文档若把它当"人工签核"，是概念混淆。

### 3.6 跨 run 成长层

- **V2 KG** ✅ 真实接线。
- **V3 RL** ⚠️ 真实但只有 4 条 Q、1 个 state（`cov:below_80|reason:none|sugg:none`），实际是单臂老虎机。有 `random.Random(seed=0)` 可复现 ✅。
- **V4 跨项目** ⚠️ 查询实现可用；`marketplace.py` 的导出/导入/合并**零调用** 💀。
- **L5 蒸馏** ⚠️ **只在 CLI 可达**（`commands.py:4105,4127,4149`），`get_live_templates/policy_bins/weights` 在主循环零调用；`_grayscale_apply()` 只写注册表，**docstring 声称的"回归验证失败则回滚"没有实现**（`distillation.py:187-197`）。
- **注意**：`policies/` 目录**不是学习状态**，是 3 个静态 YAML 配置（`baseline`/`low_power`/`pipeline`）。

### 3.7 分层纪律

`l1_infrastructure/`（1,387 行）**不是**独立实现层，而是 `src/tools/` 的薄门面——且**依赖方向倒置**：L1 向上 import `src/tools/` **6 处**（`eda_backend.py:64,74,77`；`coverage_backend.py:112,116`；`infrastructure.py:140,152,161-177`）。

后果：**部分 agent 走 L1（`agents/design/main.py:237-250`），部分 agent 直接 import `src/tools/*` 跳过 L1（verify/debug/coverage/cli）**。架构图的 "Layer 0 ← Layer 1 ← Layer 2" 是**靠约定维持的，不是结构保证的**。

另有魔法路径重复：`f:/questasim64_2024.1/win64` 硬编码在 **≥3 个模块**（`compile_healer.py:355-356`、`cmodel_tools/dpi_compile.py:34-35`、`coverage_tools/main.py:23`）。

---

## 4. 目标架构与关键取舍（ADR）

架构图本身方向没问题。以下 6 个决策需要在动手前定死。

### ADR-1：LangGraph 引入 or 自研 StateGraph

**现状**：`langgraph` 不在 `pyproject.toml` / `requirements.txt`，全仓无 import。

**收益**（若引入）：白拿 checkpointer（sqlite 短期状态）、`interrupt()`（真 HITL）、`Store`（长期记忆命名空间）、时间旅行——**架构图 Layer 1/3/4 的三样东西一次性到位**。

**成本与风险**：
1. **依赖冲突（需实测确认）**：当前锁 `langchain==0.1.20` / `langchain-core==0.1.52`（2024 年初版本）。现代 langgraph 要求更高的 `langchain-core`。引入 langgraph **极可能连带升级 langchain 全家桶**，属破坏性变更——项目里 `agents/base.py:12-14,255-256` 用了 `AgentExecutor`，`tool_protocol.py:379` 有 `to_langchain_tool()`，升级会影响这些。**动手前必须单独跑一次 `pip install --dry-run langgraph` 确认解析结果**（本次审计未联网验证，不做断言）。
2. **收益前提不成立**：LangGraph 的 reducer/checkpointer 作用在**有类型的 state** 上。当前 `ctx` 是裸 dict 且 `ctx.update()` 原地合并——此时上图，等于**给 dict 包壳**，可复现性与可审计性都不会改善。
3. 项目定位是**个人级 CLI**（CLAUDE.md），引入重框架与"三件事：CLI 体验 / Agent 管道稳定性 / Tool 工具链集成"的精力分配冲突。

**建议（分两步，降低不可逆风险）**：
- **P2a 先自研最小 StateGraph**：直接复用**已经在仓库里、已被测试覆盖、但从未接线**的 `PipelineScheduler.run_dag()`（Kahn 拓扑执行器，`pipeline_scheduler.py:120`）+ 新的 `PipelineState`。改动量小，无新依赖，可回退。
- **P2b 再评估切 LangGraph**：若 P2a 后仍需要时间旅行/HITL 中断恢复，再迁移。此时状态已定型，迁移是"换执行器"，不是"改架构"。

**若最终上 LangGraph，映射关系**（避免二次设计）：

| 架构图概念 | 本项目对应物 |
|---|---|
| 节点 Node | 7 个 agent 的 `_run(role, label)` 调用（`execution.py:325-357`） |
| 条件边 | `engine.decide()` → `action.action_type` |
| State + reducer | 新建 `PipelineState`（pydantic），reducer = 显式字段合并 |
| `interrupt_on` | 现有 `ApprovalGate` 的 2 个动作 + 补齐 `REVIEW` |
| Checkpointer | 现有 `ic_verification.db`（复用 sqlite，不新建） |
| `Store` | 现有 5 个 `.signoffai/*.db` + `audit_logs`，统一路径基准 |

### ADR-2：状态对象定型（P1 必做）

新建 `src/layers/l2_orchestration/state.py`：

```python
class PipelineState(BaseModel):
    run_id: str
    round_num: int
    design: DesignArtifacts | None = None
    coverage: CoverageState | None = None
    gaps: list[Gap] = []
    history: list[RoundMetric] = []
    decisions: list[DecisionRecord] = []   # 每次 decide() 的输入+输出，进证据链
    ...
```

替换 `ctx: dict` + `ctx.update(data)`。**理由**：没有这一层，`ctx.update()` 的静默覆盖**无法在测试里被发现**（两个 agent 用同名键就悄悄打架），这直接违反"可复现"。这是 P1 的最高优先级。

### ADR-3：工具回执与统一出口

- `ToolResult` 增字段：`verified_by: Literal["eda","none"] | None`、`evidence_ref`（指向 manifest/日志）
- `ToolAuditor.record()` 落盘为 `<output_root>/docs/tool_receipts.jsonl`（当前只在内存，进程退出即失）
- **收敛旁路**：33 处直接 import 改为经 `ToolHub.invoke()`，或至少经统一 facade 记 receipt。可分步：先给 7 个未注册包补注册，再逐个迁移调用点（用 `deprecated` 警告过渡）

### ADR-4：证据链合一 + 可落盘复核

- 文件级链补 **索引连续性检查**（对齐 DB 链的强度）
- `file_audit.verify()` 增 `verify(path)` 从磁盘回读复核（当前只验内存，等于**自己验自己**）
- 两条链**交叉引用**：文件链的 `hash` 写进 `audit_logs.detail`，DB 链的 `chain_hash` 写进 `evidence_chain.json` 头部
- 可选（若对外交付签核包）：`hmac(secret, record)` 替代裸 SHA256，防整文件重写

### ADR-5：审批默认档改为"拦截"

`--approval` 默认从 `auto` 改为 `threshold`（仅高危动作 `REFACTOR_RTL`/`UPDATE_MODEL`/`exclude_proposal` 询问）。若担心 CI 无人值守，用**显式** `--approval auto` 表达"我知道我在无人值守地放行"，而不是让默认值静默放行。补齐 `REVIEW` 的产生路径。

### ADR-6：L1/L2 依赖倒置收敛

`l1_infrastructure` 只应依赖 `src/tools` 的**稳定接口**（`EdaBackend` / `CoverageBackend`），把 6 处向上 import 收敛到 `eda_backend.py` 一处；`regression_framwork` 的 6 处内部 import（`infrastructure.py:161-177`）改经 adapter。同时把 `f:/questasim64_2024.1/win64` 收敛为单一配置项（`config/settings.py`）。

---

## 5. 分阶段重构

排序原则：**先止血 → 再硬化骨架 → 再图化 → 再补证据与治理 → 最后接成长**。

### P0 · 止血（0.5–1 天，纯删除/修正，无行为变更风险）

| # | 动作 | 文件 | 验收 |
|---|---|---|---|
| P0-1 | 修 dangling import：`src.tools.testcase_tools` **目录不存在**但被 import | `agents/base.py:397`；`agents/verify/main.py:123` | `python -c "import src.agents.verify.main"` 通过 |
| P0-2 | `RETRY_ENV` 死分支：决定"补 `decide()` 分支"还是"从 `ACTION_HANDLERS` 删除" | `decision_engine.py:301-304,344` | 二者取一，且有注释说明为何 |
| P0-3 | 统一风险枚举：`RiskLevel`(str) → `ToolRisk`(enum) | `tool_system.py:52`；`tool_hub.py:448` | 单一枚举，adapter 可删 |
| P0-4 | 修 `--resume`/`--continue` 丢弃 ID | `cli/commands.py:126-131` | 要么真实现，要么明确报"未实现"并退出非 0 |
| P0-5 | 死字段/死代码标注或删除：`ArtifactRegistry.prev_hash`、`_grayscale_apply` 的虚假 docstring | `artifacts.py:41`；`distillation.py:187-197` | 无"看起来有其实没有"的字段/注释 |
| P0-6 | 同步过时 docstring：`decision_engine.py:44`（列 5 个动作）、`rl_policy.py:7-8`（说 5 个含 CONVERGE） | 同名文件 | docstring 与代码一致 |
| P0-7 | 统一 `.signoffai` 路径基准 | `execution.py:4236` vs 5 个 store | 单一 `resolve_state_dir(output_dir)` |

**回滚**：逐条独立，`git revert` 单条即可。

### P1 · 骨架硬化（3–5 天，本次重构的核心收益）

| # | 动作 | 验收 |
|---|---|---|
| P1-1 | 新建 `PipelineState`(pydantic)，替换 `ctx: dict` + `ctx.update(data)` | 有测试证明"两 agent 写同名字段"会**报错**而非静默覆盖 |
| P1-2 | **统一 EDA 门控**：`lib/compile.py` 与 `_tools_old.py` 的重复实现合并为一份；`lib/loopback.py`/`debug_tools` 改走 `RegressionRunner`；`debug_tools/main.py:803` 的 PASS 判据补 `returncode` | 全仓 `vlog`/`vsim` subprocess 调用点从 **≥5** 收敛到 **1**（`regression_runner.py`），有 grep 断言测试 |
| P1-3 | `ToolResult` 增 `verified_by` / `evidence_ref`；`ToolAuditor` 落盘 `tool_receipts.jsonl` | 跑一次 pipeline，`tool_receipts.jsonl` 存在且每条含 provenance |
| P1-4 | `coverage/main.py:195` 的 `read_bytes()` 改分块 SHA256（复用 `infrastructure._sha256`） | 大 ucdb 不再整文件入内存 |
| P1-5 | 铁律三加**实际约束**：summary 截断到上限并记录原始长度 | 有测试断言 summary ≤ 上限 |
| P1-6 | 消除 `f:/questasim64_2024.1/win64` 硬编码（≥3 处） | 单一配置项 |
| P1-7 | 7 个未注册工具包补注册进 `ToolHub` | `_load_builtin_tools()` 覆盖 `src/tools/` 全部包 |

**风险**：P1-2 会动到 CLI 的编译路径（`commands.py:3161,3191` 用私有实现），必须先跑通 `examples/apb` + `examples/cmdsched` 端到端再合并。
**回滚**：P1-1 与 P1-2 各自独立分支，可单独 revert。

### P2 · 图化编排（5–8 天）

- **P2a**：用 `PipelineScheduler.run_dag()`（已存在）+ `PipelineState` 把 `run_closed_loop` 改写成显式节点图。节点 = 7 agent；边 = `decide()` 输出。目标：`run_closed_loop` 从 626 行降到 <150 行编排骨架，行为**逐位等价**（用现有 e2e 与 manifest diff 验证）。
- **P2b**：评估是否切 LangGraph（见 ADR-1，先跑依赖解析）。
- **P2c**：把 A2A/JSON-RPC 从"display-only"接成真实信道（或明确删掉，别留半成品）。

**验收**：同一份 YAML + 同一 seed，P2 前后 `manifest.json` 的 `field_snapshots` 除时间戳外完全一致（项目已有 `EvidencePackager.diff()` 可直接用，`manifest.py:570-614`）。

### P3 · 证据与治理闭环（3–5 天）

| # | 动作 | 验收 |
|---|---|---|
| P3-1 | **五层证据落地**：写 `config/evidence_schema.yaml` 的 loader + validator + 数据类，接进 manifest 生成 | L1–L5 每层有字段快照进 `manifest.json` |
| P3-2 | 链合一：索引连续性 + `verify(path)` 回读复核 + 双向交叉引用 | `verify` 能发现"删尾部记录"；两链可互查 |
| P3-3 | 审批默认改 `threshold`；补齐 `REVIEW` 产生路径 | 默认配置下 `REFACTOR_RTL` 会真的问人 |
| P3-4 | 让证据表不再空转：`signoffs`/`artifacts`/`evidence_links` 写入打通 | 跑完一次签核，三表行数 > 0 |
| P3-5 | `verify_audit_chain()` 接进 `vagent signoff verify` | 命令能报链完整性 |

### P4 · 跨 run 成长接线（3–5 天）

| # | 动作 | 验收 |
|---|---|---|
| P4-1 | 蒸馏结果接回主循环：`get_live_templates/policy_bins/weights` 被 `run_closed_loop` 读取 | 造一条 distillation，主循环行为改变 |
| P4-2 | 补 `_grayscale_apply()` 的真实灰度回归（或删掉 docstring 里的承诺） | 二选一，不留虚假承诺 |
| P4-3 | `marketplace.py` 接 CLI 或删除（当前 💀） | 零调用代码归零 |
| P4-4 | RL：`SOFT_ACTIONS` 与 `ACTION_HANDLERS` 统一为单一动作枚举；RL 覆盖规则时**记入证据链**（`decisions[]`） | 动作集单一来源；决策可追溯 |

---

## 6. 风险登记

| 风险 | 等级 | 缓解 |
|---|---|---|
| 引入 LangGraph 触发 langchain 全家桶破坏性升级 | **高**（未验证） | 先 `pip install --dry-run langgraph`；P2a 自研方案可完全规避 |
| P1-2 统一 EDA 门控时改坏 CLU/回归路径 | **高** | 先补 e2e 断言（`scripts/e2e_check.py:104-108` 已有骨架），再重构 |
| P2 图化后行为漂移 | 中 | 用 `EvidencePackager.diff()` 做前后 manifest 对拍 |
| 33 处旁路迁移引发连锁 import 错误 | 中 | 分批 + `DeprecationWarning` 过渡，不一次性切 |
| 状态定型暴露隐藏的键冲突 bug | 中（**这其实是收益**） | 预期会红一批测试，属正常发现 |
| 项目精力分散到框架而非 CLI 体验 | 中 | P2a 优先于 P2b；LangGraph 只在有明确需求时引入 |

---

## 7. 验收与度量

重构是否成功，用这 6 个数说话（当前值来自本次审计）：

| 指标 | 当前 | 目标 |
|---|---|---|
| `run_closed_loop` 行数 | 626（`execution.py:251-877`） | < 150 |
| `vlog`/`vsim` subprocess 调用点 | ≥ 5 处独立实现 | 1（`regression_runner.py`） |
| 工具调用产生落盘回执的比例 | 0%（`ToolAuditor` 仅内存，33 处旁路零审计） | 100% |
| 有类型检查的跨阶段状态字段 | 0（裸 dict） | 100% |
| 五层证据覆盖 | 0/5（仅 YAML 规格） | 5/5 |
| 零调用公共 API / 死代码 | ≥ 6 处 | 0 |

**行为等价性**：每个阶段结束，用同一 YAML 跑 `examples/apb`，`manifest.json` 除时间戳外与重构前一致。

---

## 8. 附录

### A. 死代码 / 零调用清单 💀

| 对象 | 位置 | 备注 |
|---|---|---|
| `marketplace.py` 全部导出/导入/合并 | `l3_decision/knowledge/marketplace.py:31,51,62` | 被 `__init__.py` 导出但无 caller |
| `verify_audit_chain()` | `l4_memory/persistence/repository.py:228-281` | 实现不错，零调用 |
| `export_audit_log()` | `tool_hub.py:331` | 返回 JSONL 字符串，无落盘 |
| `ArtifactRegistry.prev_hash` | `l2_orchestration/artifacts.py:41` | 声明后从不读写 |
| `PipelineScheduler.run_dag()` | `l2_orchestration/pipeline_scheduler.py:120` | Kahn 拓扑执行器，主循环不调用 |
| `ContextStore` / `_CONSUMES_TOPOLOGY` | `context/context.py:24-54` | 主路径不用 |
| `A2ADispatcher` 的 `handle()` | `communication/jsonrpc.py:106` | 唯一消费者是 repl 显示 |
| `uvm_tools/tool_*/schema.yaml` ×9 | `src/tools/uvm_tools/tool_*/schema.yaml` | 无 Python 读取方 |
| `get_llm_tools(risk_limit=)` | `tool_hub.py:277-294` | 无 caller 传参 |
| `ApprovalDecision.REVIEW` | `governance/approval.py:32` | 声明但 `ask()` 不产生 |
| `VcsEdaBackend` / `VcsCoverageBackend` | `eda_backend.py:83-104`；`coverage_backend.py:120-150` | 两个半成品 VCS 骨架，TODO 命令链还不一致 |

### B. 重复实现清单

| 重复项 | 两份（或多份）位置 | 严重度 |
|---|---|---|
| `run_compile_check` / `_run_compile_check` | `tools/lib/compile.py:15-55` ＋ `tools/uvm_tools/_tools_old.py:1041-1075` | **逐字节重复**，且 CLI 用的是后者 |
| `vsim` 直调链 | `regression_runner.py` / `lib/loopback.py:188-215` / `lib/collect_real_coverage.py`（5 处） / `debug_tools/main.py:803` | 判据不一致（debug 忽略 returncode） |
| `vcover` 调用 | `lib/collect_real_coverage.py:386` ＋ `coverage_tools/main.py:29` | 后者绕过前者 |
| ucdb SHA256 | `infrastructure._sha256`（分块）＋ `coverage/main.py:195`（整读） | 大文件会炸 |
| golden 概念 | `l1_infrastructure/golden_baseline.py` ＋ `tools/lib/golden_library.py` | 两个"golden" |
| QuestaSim 路径 | `compile_healer.py:355-356`、`dpi_compile.py:34-35`、`coverage_tools/main.py:23` | ≥3 处硬编码 |
| 风险分级枚举 | `tool_protocol.ToolRisk` ＋ `tool_system.RiskLevel` | 两套 |

### C. Dangling / 失效引用

| 引用 | 位置 | 事实 |
|---|---|---|
| `src.tools.testcase_tools` | `agents/base.py:397`；`agents/verify/main.py:123` | **目录不存在** |
| `src/core/file_audit.py`、`src/core/evidence.py` | `AI驱动芯片验证全栈闭环架构设计文档.md:55` | 路径已失效；真实位置在 `l2_orchestration/evidence/` |
| `--resume <id>` | `cli/commands.py:129-131` | ID 被丢弃 |
| `.signoffai/` 中 4 个 DB | `debug_experience.py:34` 等 | 盘上只有 `rl_policy.json`，其余未生成 |

### D. 本次审计未验证项（不要当结论用）

1. `langgraph` 与 `langchain==0.1.20` 的实际依赖解析结果（**未联网实测**）。ADR-1 的风险判断据此，请先跑 `pip install --dry-run`。
2. Iron rule 3 的 "<1KB" 上限：**未找到任何截断代码**，但也未确认是否有其它路径实现。
3. 各重复实现之间在**所有**边界条件上是否等价（只比对了主判据，未逐分支比对）。

---

*本文基于 2026-09-12 工作区代码快照。所有 `file:line` 可直接跳转复核。*
