# 把验证流程搬进 GUI —— 架构调整方案

> 范围：GUI（`src/workbench/`）× 流水线（`src/layers/l2_orchestration/`）的交界。
> 前置阅读：`docs/design/tool_layer_architecture.md`（工具层）、
> `docs/design/full_project_refactoring_plan.md`（编排/证据/治理）。
>
> 约束提醒：CLAUDE.md 禁止 Web 前端。本文的一切界面形态都是 **PySide6 桌面窗口**，
> 不用 SSE / WebSocket / 浏览器。

---

## 实现状态（P1 / P2 已落地）

| 计划项 | 状态 | 落点 |
|---|---|---|
| P1-1 阶段表 | ✅ | `src/layers/l2_orchestration/stages.py`（23 节点 → 显示名/分组/归属/产物） |
| P1-2 运行日志 | ✅ | `src/layers/l2_orchestration/run_journal.py` + `execution.run_closed_loop_streaming` |
| P1-3 仓库读日志 | ✅ | `RunRepository.journal / journal_summary / discover_runs` |
| P1-4 审批通道 | ✅ | `governance/approval.py`（Console/Auto/Callback/EventChannel） |
| P1-5 服务层 | ✅ | `src/layers/l2_orchestration/run_service.py` |
| P1-6 bridge 绑定 | ✅ | `workbench/bridge/catalog.py` 的 8 条 `pipeline.*` |
| P2 三个视图 | ✅ | `modules/vms/{pipeline,runs,evidence}/` + `modules/vms/run_common.py` |
| P2 审批与预设 | ✅ | `PipelineModule.confirm_approval` + 清单 `params.presets` |
| P3-1 Runtime 可重建 | ✅ | `graph.hydrate_runtime`（重入时 `n_init` 不会重跑） |
| P3-2 interrupt 式审批 | ✅ | `Runtime.interrupt_mode` + `_interrupt_approval` |
| P3-3 运行级检查点与重入 | ✅ | `docs/checkpoints.sqlite` + `run.interrupted` / `run.resumed` |
| P3-4 服务层与界面重入 | ✅ | `RunService.resume` + `pipeline.resume` + 审批条 |
| **P3 并行（拆单例）** | ⛔ **未做** | 见文末 |

测试：根 `tests/` 新增 `test_stages.py` / `test_run_journal.py` / `test_run_streaming.py`
/ `test_run_service.py` / `test_run_repository_journal.py` / `test_approval.py`；
工作台新增 `src/workbench/tests/test_pipeline_modules.py`。

### 施工中查出的 4 个既有 bug

都不是新写的代码引入的，是这条路径上**早就存在、只是没人走过**：

1. **`result` 被静默丢弃** —— `PipelineState` 是 `extra="forbid"` 的 pydantic 模型，
   而 LangGraph 对未声明的键**静默丢弃**。`n_finalize` 的 `return {"result": ...}`
   一直没进状态，`run_closed_loop` 于是恒返回 `{}`：CLI 的 run_id / coverage /
   converged 全是 `None` / `0` / `NO`。修法：把 `result` 声明成状态字段，
   并加一条 **AST 静态扫描**测试，禁止任何节点返回未声明的键。

2. **审批拒绝不生效** —— `n_approval` 拿 `ApprovalRecord` 与 `ApprovalDecision`
   枚举比较，dataclass 的 `__eq__` 对非同类返回 `NotImplemented` → 恒为 False。
   于是"用户点拒绝"从来没改变过控制流，`SKIP` / `REVIEW` 两条分支是死代码。
   对一个把"可治理"当卖点的产品，这是最不该有的洞。顺带把审批故障从
   fail-open（静默放行）改成 fail-closed（跳过该动作并记账）。

3. **`vagent runs` 恒为空** —— `make_output_root("output")` 产出的是**前缀式**
   名字（`output_用户_时间戳`），落在 CWD 下当兄弟目录；而 `RunRepository`
   只扫 `output/*/` 的子目录。两边对"output 是父目录还是前缀"的答案不一致。
   读取侧改成两种布局都认（`run_dirs()`）。

4. **同一秒的第二次运行会叠时间戳** —— `_TIMESTAMPED` 正则漏掉了撞车后缀
   `_2`，`make_output_root` 的幂等承诺在改名那一刻失效，目录名会长成
   `output_x_20261002_120000_2_x_20261002_120000`。

另修一处界面坑：**贴回的布局可能让新模块不可见** —— 上次保存时某块窗格是空的
（存成 0 宽），这次装了模块却仍旧 0 宽。修法是贴回**之前**修那组数字
（`PaneLayout.repair_saved_sizes`），而不是贴完之后改几何 —— 窗口还没 show 时
`QSplitter.sizes()` 给的是尚未布局的占位值，读-改-写会把正确的尺寸整个冲掉。

---

## 0. 一句话结论

**流程不该被"搬进"GUI，该被"观测"。**

今天两头是断的：流水线是一个 23 节点的 LangGraph 图，跑完把文件写到 `output/` 就没了下文；
GUI 是一个清单驱动的空壳，`AppContext` 里**根本没有"运行"这个概念**（`context.py:25-40`）。
中间缺的不是一个界面，是**一条运行观测通道**。

所以本方案 80% 的工作量在流水线侧和一层新的服务层，**不在界面代码里**。
GUI 的活是最后 20%：给这条通道画三个视图。

目标形态：

```
  现状                                  目标
  ────                                  ────
  CLI ─asyncio.run─┐                    CLI ──┐
                   ├─> ExecutionService        ├─> RunService ─> ExecutionService
  workbench ─bridge┤        │            workbench ─┘      │            │
             (只到工具)      └─> graph ─> output/           │            └─> graph
                                (看不见)                     │                  │
                                                             │                  ▼
                                                             └──> RunJournal <──┘
                                                                  (docs/run_events.jsonl)
                                                                       ▲
                                                       RunRepository ──┘  ← 历史 run = 磁盘
```

关键：**CLI 与 GUI 走同一条 RunService，读同一份运行日志。**
于是"在终端里启动、在 GUI 里看它跑"是天然成立的 —— 这本身就是差异化
（可复现·可审计）的一个可见证明。

---

## 1. 两头的现状（事实）

### 1.1 流水线这头：一个 23 节点的图，外面看不见

| 事实 | 证据 |
|---|---|
| 图在 `build_closed_loop_graph()` 构建，**23 个节点** | `graph.py:959`、`:973-987` |
| 用 `graph.ainvoke(initial, config)` 调用，**异步** | `execution.py:301` |
| **不接检查点**：`build_closed_loop_graph()` 无参调用，全仓无 `checkpointer=` / `thread_id` | `execution.py:286` |
| `Runtime` 持有非序列化的东西（sqlite 连接、LLM 客户端、agent 实例） | `graph.py:48-75` |
| `PipelineState` **全字段可序列化**（设计如此） | `state.py:22-25`、`:71` |
| 运行结果只落盘：`output/{prefix}_{user}_{时间戳}/docs/{manifest,evidence_chain,file_change_chain}.json` | `output_config.py:17-34`；`graph.py:824-909` |
| `RunRepository` 靠**扫盘**建立 run 索引：`output/*/docs/manifest.json` 存在即算一次 run | `run_repository.py:33-47` |
| 事件总线定义了 `PIPELINE_STARTED / PHASE_COMPLETED / COMPLETED / FAILED`，但**图内一次都没发过**；唯一被调用的是 `publish_observation` | `event_bus.py:50-109`；`graph.py:512` |
| `PipelineExecutionService._runs` 从未被 `run_closed_loop` 填充 → `watch` / `history` 的实时分支是**死的** | `execution.py:65`；`commands.py:1093` |
| CLI `verify` 的阶段表是**跑完之后**才打印的 | `commands.py:227-248` |

**一句话**：今天没有任何"运行中"的可观测面。想看进度只能等它跑完。

### 1.2 GUI 这头：一个清单驱动的壳，没有"运行"概念

| 事实 | 证据 |
|---|---|
| `AppContext` 字段：`manifest / tools / bus / tasks / settings / window / console / modules` —— **没有 current_run / current_project** | `context.py:25-40` |
| `TaskRunner`（QThreadPool + QRunnable + 主线程信号）已建好、已测试，但**零生产调用点** | `tasks.py:52-95`；`modules/` 里 grep 无 `submit(` |
| `TaskRunner` **刻意不支持**取消 / 优先级 / 进度百分比 | `tasks.py:7-8` |
| `EventBus` 有 5 个 topic 常量，`ModuleManager` 会按 YAML 的 `params.subscribe` 订阅，但**没有任何生产代码 publish** | `bus.py:19-27`；`registry.py:117` |
| `ConsolePanel.begin_task/end_task`（任务进度行）已实现，**无调用者** | `console.py:122,126` |
| 没有任何 `QProgressBar`；状态栏只有一行文本 + "模块 N" | `app.py:344-352` |
| ~~四窗格~~ **MDI 中央 + Dock 侧栏** | `ui/workspace.py`；`app.py:_build_central` |
| 三个模块：`debug.sim_log`、`debug.fingerprint`、`vms.casemodel` | `config/workbench.yaml` |

**一句话**：GUI 的所有异步/事件机制都**造好了但没接上**。它现在是一个"调用一次工具、
显示一次结果"的查看器，不是一个"跟着一次运行跑"的工作台。

### 1.3 中间缺的四件东西

| # | 缺什么 | 谁该提供 |
|---|---|---|
| 1 | **运行观测通道** —— 阶段开始/结束/失败、轮次、决策、覆盖率变化 | 流水线（L2） |
| 2 | **运行身份** —— 一次运行是个有 id、有状态、能查、能列的对象 | L2 + 已有 `RunRepository` |
| 3 | **人工审批通道** —— GUI 里没有 stdin，而 `ApprovalGate.ask()` 就是 `input()` | 治理层（L2） |
| 4 | **Qt ↔ asyncio 的唯一交界处** —— 图是 async，Qt 是同步事件循环 | 新服务层 |

---

## 2. 判定：清单驱动的是「视图」，不是「流程」

很容易顺手把流程写进 `config/workbench.yaml`：

```yaml
# ✗ 不要这样
stages:
  - {id: ops, title: 编译仿真, module: vms.ops}
  - {id: coverage, title: 覆盖率, module: vms.coverage}
```

这样做的后果是**流程有了第二份真相**：图里有 23 个节点，YAML 里再描述一遍，
两边迟早对不上（本仓库已经栽过一次同类跟头 —— `casemodel_tools/schema.yaml`
的注释指向已删除的 `agent/registry.py`，见工具层文档 §2.3d）。

正确的切分：

| 概念 | 属于谁 | 形态 |
|---|---|---|
| **流程**（有哪些阶段、谁是谁的前驱、谁能回到谁） | 领域（L2） | Python 代码：`graph.py` + 一张 `StageSpec` 表 |
| **视图**（显示哪几个面板、绑哪个运行目录、轮询多快） | GUI 清单 | YAML `params` |
| **预设**（快跑 / 全跑 / 仅覆盖率收敛） | 领域 + 清单都可声明 | 参数集合，不是控制流 |

清单里只多这么一段：

```yaml
modules:
  - id: vms.pipeline
    title: 验证流程
    group: vms
    factory: "src.workbench.modules.vms.pipeline.module:PipelineModule"
    area: center
    tool: {name: pipeline.start, kind: json}
    params:
      run_root: output          # 去哪找运行
      poll_ms: 500              # 日志轮询周期
      follow_latest: true       # 启动时自动跟随最新一次运行
  - id: vms.runs
    title: 运行历史
    group: vms
    area: left                  # 挂在左窗格（导航列）
    params: {run_root: output}
  - id: vms.evidence
    title: 证据 / 产物
    group: vms
    area: right
    params: {run_root: output, subscribe: run.selected}
```

**流程的权威定义仍在 `graph.py`，GUI 只是它的一个渲染器。**

---

## 3. 目标架构

### 3.1 新增两层：`StageSpec`（领域数据）与 `RunJournal`（运行日志）

**(a) `src/layers/l2_orchestration/stages.py` —— 阶段表**

今天阶段名是散落在图里的字面量（`"planning"`、`f"ops_r{n}"`、`"governor"`、
`"golden_baseline"`…），CLI 的阶段表是**另写一份**。抽一张表：

```python
@dataclass(frozen=True)
class StageSpec:
    id: str              # 与图节点名对齐，如 "ops"
    title: str           # 中文显示名，如 "编译与仿真"
    group: str           # 分组：设计 / 验证 / 执行 / 收敛 / 签核
    agent: str           # 归属 agent role（design/model/verify/ops/coverage/debug/audit）
    outputs: tuple[str, ...]   # 产出哪些 state 字段 / 磁盘产物
    round_scoped: bool   # 是否每轮重复出现（ops_r{n}）
```

`PHASE_OWNERS`（`state.py:165-181`）已经是"阶段 → 属主"的半张表，
`StageSpec` 把它补全成"阶段 → 显示名 + 分组 + 产物"。

**收益**：CLI 的阶段表、GUI 的时间线、**manifest 的 phases 字段**三处共用一份定义；
"加一个节点"从此是一处改动。

**(b) `RunJournal` —— 追加式运行日志**

```
output/{run}/docs/run_events.jsonl
```

每行一条 JSON 记录：

```json
{"seq":1,"ts":"2026-10-02T09:31:00.123","run_id":"output_ljq_20261002_093100",
 "kind":"run.started","round":0,"stage":null,"agent":null,
 "payload":{"spec":"npu_top","target":95.0,"max_rounds":5}}
{"seq":2,"ts":"...","kind":"stage.started","round":0,"stage":"design","agent":"design"}
{"seq":9,"ts":"...","kind":"stage.finished","round":0,"stage":"design","agent":"design",
 "payload":{"status":"ok","duration_s":41.2}}
{"seq":10,"ts":"...","kind":"coverage.updated","round":1,"stage":"coverage",
 "payload":{"total":0.83,"functional":0.71}}
{"seq":11,"ts":"...","kind":"approval.requested","round":1,"stage":"approval",
 "payload":{"action":"REFACTOR_RTL","risk":"high","reason":"...","token":"ap-7f3a"}}
{"seq":12,"ts":"...","kind":"approval.decided","round":1,"stage":"approval",
 "payload":{"token":"ap-7f3a","decision":"approve","by":"gui"}}
{"seq":31,"ts":"...","kind":"run.finished","round":4,
 "payload":{"verdict":"pass","final_coverage":0.96,"converged":true}}
```

四条设计约束：

1. **只追加，不修改** —— 崩溃时日志天然是完整的（最后一行可能截断，解析器跳过即可）。
2. **`seq` 单调** —— 重放顺序确定；哈希链可以后接（对齐 `file_audit.py` 的做法）。
3. **每条自带 `round` / `stage` / `agent`** —— 前端不必自己维护状态机，过滤即视图。
4. **不含 `Runtime` 里的任何对象** —— 只有可 JSON 化的东西，与 `PipelineState`
   的"可序列化"纪律一致（`state.py:22-25`）。

### 3.2 五条通道

| 通道 | 方向 | 实现 | 归属 |
|---|---|---|---|
| **启动** | GUI → 流水线 | `RunService.start(request) -> run_id` | L2 新服务 |
| **观测** | 流水线 → 世界 | 图 `astream` → `RunJournal`（JSONL） | L2 |
| **审批** | 流水线 ⇄ 人 | `ApprovalChannel` 协议；GUI 实现用跨线程 `Event` | L2 governance |
| **取消** | GUI → 流水线 | `RunService.cancel(run_id)`，协作式（`threading.Event` + 图内检查点） | L2 |
| **历史** | 磁盘 → GUI | `RunRepository`（已有）+ `read_journal(run_id)` | L2 |

### 3.3 三处必须动，一处不该动

**必须动：**

1. **`graph.py` 的调用方式** —— 从 `ainvoke` 增加一条 `astream` 路径（§4 GADR-1）。
   **节点函数体一行不改。**
2. **`approval.py`** —— `ask()` 里那句阻塞的 `input()` 抽成 `ApprovalChannel`。
   `ConsoleChannel` 保持今天的行为**逐字节不变**（`y/n/s/d/r/q` 的提示文案都一样），
   新增 `GuiChannel`。
3. **`execution.py`** —— `run_closed_loop` 增加 `on_event` 参数与 `run_id` 注册，
   并让 `_runs` 真正被填充（顺带救活 `watch` / `history`）。

**不该动：**

> ⚠️ **2026-10-04 已反转**：外壳改成了 **QMdiArea 中央子窗口 + QDockWidget 侧栏**（可浮动 / 拖停 / 平铺 / 层叠，center 模块可多开）。当时的理由「dock 是 IDE 形状、不像 Verdi」被用户明确推翻 —— 要的就是 IDE 形状。实现见 [`agent_gui_business_architecture.md`](agent_gui_business_architecture.md) 与 `src/workbench/ui/workspace.py`（旧的 `panes.py` 已删除）。**下面这几处「不改平台 / 不新造窗格 / 不用 QDockWidget」的表述已过时，保留只为留痕。**
>
- ~~**`workbench/` 的核心**（`app.py` / `panes.py` / `registry.py` / `manifest.py`）——
  它已经是对的。新增能力以**模块**形式进来，不改平台。~~这正是"模块失败不影响平台"
  那条纪律（`registry.py:11-15`）的兑现。
- **`TaskRunner` 的定位** —— 它服务"短、一次性、可丢弃"的工具调用，不服务运行（§4 GADR-6）。

---

## 4. 关键设计决策

### GADR-1：观测走 LangGraph 原生 `astream`，不打扮节点

**不要**在每个节点里插 `journal.append(...)` —— 23 个节点、23 处改动、
以后加节点必忘。LangGraph 自带这个能力，实测：

```console
$ python -c "…compiled.astream({'x':0}, stream_mode=['updates','custom'])"
chunks: [('updates', {'a': {'x': 1}}), ('updates', {'b': {'x': 2}})]
```

- `stream_mode="updates"` → 每个节点执行完推一次 `{节点名: 状态增量}`，
  **阶段边界白送**，且节点名就是 `StageSpec.id`。
- `stream_mode="custom"` → 节点内可以用 `get_stream_writer()` 推细粒度进度
  （`langgraph.config.get_stream_writer` 在本环境可用）。
  只有**真正需要**的少数节点（ops 跑回归、coverage 收集）再加，不是全都要。

落地形态：

```python
# execution.py —— 新增一条，不动既有 ainvoke 路径
async def run_closed_loop_streaming(..., on_event: Callable[[RunEvent], None]):
    graph, rt = _build(...)
    journal = RunJournal(output_root)
    async for mode, chunk in graph.astream(init, config,
                                           stream_mode=["updates", "custom"]):
        if mode == "updates":
            for node, delta in chunk.items():
                journal.record_stage(node, delta)          # 节点名 = 阶段 id
        else:
            journal.record_custom(chunk)
        if cancel_event.is_set():
            journal.record("run.cancelled")
            break
    return await _finalize(...)
```

`on_event` 是**可选**的：CLI 不传时行为与今天一致（`ainvoke` 那条路径原样保留）。
这保证了"改造不改变既有行为"这个前提。

> **实现顺序的坑**：先只在 `output/` 落 JSONL、界面用轮询 tail（GADR-2），
> 确认整条链路通了，**再**考虑加进程内信号做低延迟快路径。
> 反过来做的话，会同时调试"图有没有推事件"和"Qt 有没有收到信号"两件事。

### GADR-2：运行日志落盘，实时视图与历史视图读同一份

这是本方案**最重要的一条**。

| 做法 | 实时看 | 历史看 | 崩溃后 | 终端启动 GUI 看 | 代码 |
|---|---|---|---|---|---|
| 只有进程内 Qt 信号 | ✅ | ❌ | ❌ | ❌ | 两套渲染器 |
| JSONL 日志 + tail | ✅（延迟 = 轮询周期） | ✅ | ✅ | ✅ | **一套渲染器** |

选后者。界面上：

- `QTimer(poll_ms)` → 读文件尾部的**新增字节**（记住上次偏移，不重读整个文件）。
- 解析出的记录喂给同一套"阶段时间线"渲染器。
- 打开一次**历史运行**走的是同一条渲染器，只是数据源是完整文件而不是尾部。

500ms 的延迟对一个跑几分钟的验证流程**完全无感**，换来的是"关掉窗口再打开，
这次运行还在那里，而且能接着看"。

**顺带解决的问题**：`RunRepository` 已经是磁盘扫描（`run_repository.py:33-47`），
加一个 `journal(run_id)` 方法就够了 —— 运行列表与运行详情是同一个数据源，不会出现
"列表里有、点进去没有"。

### GADR-3：流程是领域数据，不是 GUI 配置

见 §2。补充一点：**预设**是允许写进清单的，因为它只是参数集合：

```yaml
params:
  presets:
    - {id: smoke,  title: 冒烟,   max_rounds: 1, target: 60.0, approval: auto}
    - {id: full,   title: 全流程, max_rounds: 5, target: 95.0, approval: threshold}
    - {id: cover,  title: 只收敛, max_rounds: 8, target: 95.0, bypass_design_model: true}
```

预设展开成 `run_closed_loop` 的实参 —— **不展开成控制流**。

### GADR-4：Qt 与 asyncio 只在一个地方交界

现状：workbench 全是同步 worker 线程（`tasks.py`），流水线全是 async（`ainvoke`）。
**绝对不要**在 GUI 线程里 `asyncio.run()` —— 那会冻结界面。

新服务 `src/layers/l2_orchestration/run_service.py`：

```python
class RunService:
    """一次一个运行；Qt 无关；唯一的 async 入口。"""

    def __init__(self, ...):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def start(self, request: RunRequest) -> str:
        """非阻塞。返回 run_id；进度写进 RunJournal。"""

    def cancel(self, run_id: str) -> bool: ...
    def list_runs(self, limit: int = 50) -> list[RunSummary]: ...   # 委托 RunRepository
    def journal(self, run_id: str, after_seq: int = 0) -> list[RunEvent]: ...
```

三条纪律：

1. **Qt 不在这个文件里出现**（`grep PySide6 src/layers/` 必须为空）。GUI 通过
   `workbench/bridge/catalog.py` 里的 `ToolBinding` 绑定到它，与其它工具一视同仁。
2. **一次一个 run**（§6.2 说明为什么），多余的进队列。
3. 服务层只**搬**事件，不**解释**事件 —— 解释（哪些阶段算一组、什么算收敛）
   属于视图，或者更好：属于 `StageSpec`。

### GADR-5：人工审批做成 `ApprovalChannel`，P1 用事件、P3 用 interrupt

**问题（今天是 bug）**：`ApprovalGate.ask()` 是同步阻塞的 `input()`
（`approval.py:90-153`），而它被 `async def n_approval` 调用（`graph.py:567-591`）。
**阻塞 `input()` 会卡死整个事件循环。** 在 CLI 里因为只有一个任务所以没暴露；
一旦进了服务层就是灾难。

P1 方案 —— 抽协议，不引入新依赖：

```python
class ApprovalChannel(Protocol):
    def ask(self, req: ApprovalRequest) -> ApprovalDecision | None: ...

class ConsoleChannel:          # 今天的行为，逐字节保留
    def ask(self, req): return input(f"…y/n/s/d/r/q…")

class AutoChannel:             # --approval auto
    def ask(self, req): return ApprovalDecision.APPROVE

class EventChannel:            # GUI 用：跨线程等待
    def __init__(self): self._event = threading.Event(); self._answer = None
    def ask(self, req):
        self.requested.emit(req)        # 主线程弹对话框
        self._event.wait(timeout=req.timeout_s)   # 工作线程阻塞，**不是 GUI 线程**
        return self._answer or ApprovalDecision.SKIP
    def answer(self, decision):         # 主线程调用
        self._answer = decision; self._event.set()
```

要点：**阻塞的是运行线程，不是 GUI 线程**。运行线程挂着等，界面照样能滚日志、看别的运行。
超时默认走 `SKIP` 并且 journal 记账（`approval.timeout`）—— 静默变 `proceed` 是不能接受的。

P3 可选 —— 换成 LangGraph 原生：

```python
from langgraph.types import interrupt, Command     # ✓ 本环境可用
```

`interrupt()` + checkpointer 能让审批**跨进程存活**（关掉 GUI 明天再批）。
依赖已经在 `pyproject.toml:16` 里了（`langgraph-checkpoint-sqlite==3.1.1`）——
**装了但没用**。这不是 P1 该做的事（要先接检查点，等于动图的生命周期），
但值得写进路线图。

### GADR-6：运行不走 `TaskRunner`

`TaskRunner` 的定位（`tasks.py:7-8`）是"短、一次性、可丢弃，刻意不提供取消/进度"。
一次验证运行完全相反：长、有身份、必须能取消、必须能在切标签页后继续存在。

所以：

- **运行** → `RunService`（自己的线程 + 自己的 loop）。
- **`TaskRunner`** → 保持现状，但补两处**本来就该有的接线**（10 行以内）：
  `started/finished/failed` → `ConsolePanel.begin_task/end_task` + 状态栏。
  这两个钩子早就写好了（`console.py:122,126`），只是没人调。

别为了"统一"把运行塞进 `TaskRunner` —— 那会把取消/进度/身份三件事硬塞进一个
刻意不要它们的抽象里。

---

## 5. 界面怎么摆（映射到现有四窗格）

**总原则：~~不新造窗格。~~**（已反转，见本节顶部注记） 现有四窗格（左导航/中工作区/右详情/底控制台）正好够，
而且左窗格的 `NavPane`（`app.py:159`）本来就是一个树。

```
┌──────────────┬────────────────────────────────────┬───────────────┐
│ 运行 / 导航   │  验证流程  ×  运行历史  ×           │ 证据 / 产物    │
│              │  ┌──────────────────────────────┐  │               │
│ ▾ 本次运行    │  │ 轮次 1  ▸ 设计 ▸ 建模 ▸ 验证  │  │ ▾ docs/       │
│   ● design   │  │         ▸ 编译仿真 ✓ 8.2s     │  │   manifest.json│
│   ● model    │  │         ▸ 覆盖率  83%         │  │   run_events   │
│   ✓ verify   │  │ 轮次 2  ▸ 决策: RELAX         │  │ ▾ sim/        │
│   ✓ ops      │  │         ⏸ 待审批 [批准][拒绝]  │  │ ▾ rtl/        │
│   ● coverage │  └──────────────────────────────┘  │               │
│ ▾ 历史运行    │  ┌── 阶段详情 ───┬── 实时日志 ──┐  │  覆盖率趋势    │
│   093100 ✓   │  │ agent: ops    │ [info] vlog… │  │  ▁▃▅▆▇ 96%   │
│   084512 ✗   │  │ 产物: sim/*.log│ [warn] …    │  │               │
└──────────────┴────────────────────────────────────┴───────────────┘
│ 控制台：✓ 编译仿真   ● 覆盖率收集中…           运行 output_ljq_093100 │
└─────────────────────────────────────────────────────────────────────┘
```

对应到具体模块：

| 窗格 | 模块 | 内容 | 数据源 |
|---|---|---|---|
| 左 | `vms.runs` | 运行列表 + 阶段树；选中即发布 `run.selected` | `RunRepository.list_runs()` |
| 中 | `vms.pipeline` | 阶段时间线（按轮次分组）+ 阶段详情 + 实时日志 | `read_journal(run_id)` 尾部 |
| 右 | `vms.evidence` | 本次运行的产物树 + 覆盖率趋势 | `output/{run}/` 目录 + journal |
| 底 | （已有 `ConsolePanel`） | 平台级日志 + `begin_task/end_task` 进度行 | `ctx.log` + `TaskRunner` 信号 |

**三个具体的界面件**（都是现成 Qt 类，不需要自绘）：

1. **阶段时间线** —— `QTreeWidget`，一级是轮次、二级是阶段；每项带状态图标 +
   耗时 + 一行摘要。状态图标复用已有的 `ui/icons.py`。
2. **审批提示** —— 中窗格顶部一条 `Banner`（已有类，`base.py:127`）+
   主线程 `QMessageBox` 模态框。审批 **是**弹模态的场景，因为流程真的停在那里等。
3. **覆盖率趋势** —— 直接用现有的 `ui/coverage_view.py`（已经在盘上），
   喂 `coverage_history` 即可。

**一个必须有的东西**：状态栏右侧那个 "模块 N" 旁边加 **"运行 xxx ●"**。
今天的 `stat_modules`（`app.py:344-352`）已经是 permanent widget 的位置，
加一个同级的运行指示器是零成本。

---

## 6. 三个必须诚实面对的硬约束

### 6.1 没有检查点 → 运行不能暂停/重入

`build_closed_loop_graph()` 不传 checkpointer（`execution.py:286`），全仓没有
`thread_id`。含义：

- 一次运行只能**从头跑到尾**，或被杀掉重来。
- GUI 里**不要**画"暂停/继续"按钮 —— 做不到就是做不到，画出来是撒谎。
- 能提供的只有 **取消**（协作式：图内检查 `cancel_event`，在轮次边界退出），
  并且取消后 `run_events.jsonl` 会留下 `run.cancelled` —— **半途而废的运行也是可审计的**，
  这比"能暂停"更贴合本项目的定位。

要做真正的暂停/重入，需要接 `langgraph-checkpoint-sqlite`（依赖已在
`pyproject.toml:16`）+ 给 `astream` 传 `thread_id`。那是 P3。

### 6.2 `Runtime` 非线程安全 + `PipelineExecutionService` 是单例 → 一次一个 run

`Runtime` 持有 sqlite 连接、LLM 客户端、agent 实例（`graph.py:48-75`）；
`PipelineExecutionService` 是单例（`execution.py:56-71`），且 `_runs` 是个裸 dict。

多开两个运行 = 连接互踩 + `_runs` 互相覆盖。所以：

- `RunService` **串行化**运行（队列）。考虑到 EDA 工具是资源独占的，这本来也合理。
- 界面上"启动"按钮在运行期间置灰，并明确写"当前有一个运行在跑"。
- 如果将来真要并行，正确的做法是**每个 run 一个 `Runtime` 实例**并把单例拆掉 ——
  那是独立一轮的事，别在 GUI 这轮顺手做。

### 6.3 今天的 `ApprovalGate` 会卡死事件循环

见 GADR-5。这条在 CLI 单任务下不暴露，**一进服务层就是 P0**。
顺带：`n_approval` 的 `except Exception` 是 fail-open（`graph.py:588-591`），
审批出故障时静默 `proceed`。GUI 场景下必须改成 fail-closed 或至少 journal 记账 ——
"审批系统挂了就全放行"和"可治理"是矛盾的。

---

## 7. 迁移路线

每一步都能独立验收，且**不改变既有 CLI 行为**。

### P1 · 让运行变得可见（3–5 天）

| # | 做什么 | 验收 |
|---|---|---|
| 1 | `stages.py`：抽 `StageSpec` 表；CLI 的阶段表与 manifest 的 phases 改成读它 | 既有 CLI 输出逐字节不变；`grep -rn '"planning"' src/layers` 只剩 stages.py |
| 2 | `RunJournal` + `read_journal()`；`run_closed_loop_streaming(..., on_event)` | 跑一次 `vagent verify`，`output/{run}/docs/run_events.jsonl` 的 `seq` 连续、每条有 `round/stage` |
| 3 | `RunRepository.journal(run_id)` | 对历史运行也能读出同样结构 |
| 4 | `ApprovalChannel` 抽象；`ConsoleChannel` 复刻今天行为 | 现有审批测试全绿；`grep -n "input(" approval.py` 只在 `ConsoleChannel` 里 |
| 5 | `RunService`（loop 线程 + 串行队列 + `start/cancel/list/journal`） | 一个 pytest：`start()` 后轮询 `journal()` 能看到 `run.started → stage.* → run.finished` |
| 6 | bridge 绑定 `pipeline.start` / `pipeline.cancel` / `pipeline.runs` / `pipeline.journal` | `tests/test_bridge.py` 加四条，与现有 `casemodel.*` 同形 |

> P1 结束时**还没有界面**，但"运行"第一次成为一个可观测、可查询的对象。

### P2 · 三个视图（3–5 天）

| # | 做什么 |
|---|---|
| 7 | `vms.runs` 模块（左窗格）：运行列表 + 阶段树；发布 `run.selected` |
| 8 | `vms.pipeline` 模块（中窗格）：阶段时间线 + `QTimer` 轮询 tail + 阶段详情 |
| 9 | `vms.evidence` 模块（右窗格）：产物树 + 覆盖率趋势（复用 `coverage_view.py`） |
| 10 | 接线三处早该接的：`TaskRunner` 信号 → `ConsolePanel.begin_task/end_task`、状态栏、`bus.publish` 的输入变更 |
| 11 | `EventChannel` 审批：运行线程等待、主线程模态框；超时走 `SKIP` 并记账 |
| 12 | `config/workbench.yaml`：加三个模块 + 预设 |

验收：启动一次运行，界面上能看到阶段一个个亮起来、弹出的审批点"拒绝"能让流程
走 `reject` 分支、关掉窗口再打开能看到这次运行的历史。

### P3 · 可暂停与并行（可选，独立一轮）

- 接 `langgraph-checkpoint-sqlite` + `thread_id` → `interrupt()` 审批 → 跨进程重入。
- 拆 `PipelineExecutionService` 单例，每 run 一个 `Runtime` → 真并行。

---

## 8. 不做

- **不做 Web / SSE / 浏览器**（CLAUDE.md 明令）。桌面窗口 + 文件轮询足够。
- **不在 GUI 里编辑流程拓扑**。23 个节点是产品资产，不是用户配置项。
  可配的是**参数与预设**（§GADR-3）。
- **不让 GUI 直接 `import` `graph.py` / `execution.py`**。GUI 只能经
  `bridge/catalog.py` 的 `ToolBinding` 白名单到达 L2 —— 与它今天访问工具的方式一致，
  这样"GUI 能碰什么"永远是一份可审计的清单。
- **不做运行进度百分比**。图是轮次循环结构，"总进度"没有诚实的定义。
  显示**当前阶段 + 第几轮 / 共几轮**就足够了 —— `round_num` / `max_rounds`
  本来就在 `PipelineState` 里（`state.py:79-95`）。
- **不把 `TaskRunner` 改造成运行引擎**（§GADR-6）。

---

## P3 落地后的口径

**暂停/重入已经是真的了。** 高风险动作（`REFACTOR_RTL` / `UPDATE_MODEL`）的审批
从"阻塞等答案"换成了 `interrupt()`：这次 `astream` 结束，状态落在
`output/{run}/docs/checkpoints.sqlite`，人什么时候答都行 —— **换一个进程、
换一天都可以**（`tests/test_checkpoint.py::TestResume::test_resume_works_in_a_fresh_service`
钉住的就是这条，只测同进程重入等于没测）。

四条实现约束值得记住：

1. **检查点的开合必须留在 async 里**。`AsyncSqliteSaver` 底下是 aiosqlite，连接绑在
   创建它的那条 loop 上 —— 想"另开一个 loop 把它推起来"塞进同步 `try/finally`，
   连接一跨 loop 就**静默**失效。所以 `_checkpointer` 是 `async with` 的。
2. **重入时 `n_init` 不会重跑**。它建的那些东西（`engine` / `planner` / `infra` /
   `governor` / 两个注册表 / 审计链）后面每个节点都要用，少了不是"退化"而是
   `AttributeError`。所以抽出 `hydrate_runtime(rt, state)`，两处调用一份实现。
3. **日志的 `seq` 跨重入要继续编号**。一次运行分几次写同一个文件，每次开头归零的话，
   按 `after_seq` 轮询的界面会认为"这些我都看过了"而把后半段整段丢掉 ——
   表现为"重入了但时间线不动"（这个 bug 真的出现了，见 `RunJournal.__init__`）。
4. **"等人"是一档独立状态**（`waiting`），既不是 `running` 也不是 `completed`。
   归进 `running` 的话，一次暂停的运行看起来就像卡住了。

界面上的审批做成**非模态的条**而不是弹框：检查点模式下根本没有谁被挂住，
弹模态等于假装它在等，顺手还把界面锁了 —— 而"先去干别的、想好了再来批"
正是接检查点换来的东西。三个按钮同时服务两种模式（检查点=重入 / 通道=回话），
对用户是同一件事。

### 还没做的：并行

拆掉 `PipelineExecutionService` 单例、让每个 run 一个 `Runtime` 实例，仍未做。
今天串行是**如实**的约束（`Runtime` 里握着 sqlite 连接与 agent 实例），
硬拆会引入一类很难复现的并发 bug。所以现在的口径是：**能暂停、能取消，
但一次只跑一个运行**。

`run_events.jsonl` 里取消会留下 `run.cancelled`、暂停会留下 `run.interrupted` ——
半途而废与中途等人的运行同样可审计，这比画一个做不到的按钮更贴合定位。
