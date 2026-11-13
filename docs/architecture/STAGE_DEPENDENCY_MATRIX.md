# Stage Dependency Matrix (Architecture 4.0)

> 记号：`A`=Agent Plane，`G`=Generation，`E`=Engine，`I`=IR，`R`=Runtime，
> `L`=legacy layers（l1/l2/l3），`T`=tools，`EDA`=外部工具进程。
> “直接”指模块级 import；“运行期”指通过路径/子进程/字符串调用。

## 1. Stage 执行器

| 模块 | A | G | E | I | R | L | T | EDA | 写入 | LLM |
|---|---|---|---|---|---|---|---|---|---|---|
| `front/main.py` | – | – | – | – | – | 直接 | 直接 | – | 日志 | – |
| `front/vplan/*` | – | – | – | 直接 | – | – | – | – | bootstrap 产物 | – |
| `front/dplan/extract.py` | – | – | – | – | – | – | 直接 | – | dplan/contract | **是** |
| `design/main.py` | – | 直接 | – | – | – | 直接 | 直接 | vlog | RTL | **是** |
| `model/main.py` | – | 直接 | – | – | – | 直接 | 直接 | gcc/vlog | C Model | – |
| `verify/main.py` | – | 直接 | – | 直接 | – | 直接 | 直接 | – | UVM/SVA/case | – |
| `verify/ir_artifacts.py` | – | – | – | 直接 | – | – | – | – | IR 产物 | – |
| `ops/main.py` | – | – | – | – | – | 直接 | 直接 | vlog/vsim/vopt | 回归产物 | – |
| `coverage/main.py` | – | – | – | – | – | 直接 | – | vsim/vcover | 覆盖率产物 | – |
| `audit/main.py` | – | – | – | 直接 | – | 直接 | 直接 | vlog | evidence/signoff | – |
| `debug/main.py` | – | – | – | – | – | 直接 | 直接 | vsim | 修复写回 | **是** |
| `debug/tools/main.py` | – | – | – | – | – | – | 直接 | 只读日志 | – | – |
| `debug/tools/waveform.py` | – | – | – | – | – | – | – | wlf2log/qwaveman | 临时 VCD | – |
| `debug/tools/signal_diagnosis.py` | – | – | – | – | – | – | – | – | – | – |

## 2. 流程编排（原 `engine_plane/agents`）

| 模块 | A | G | E | I | R | L | T | EDA | LLM |
|---|---|---|---|---|---|---|---|---|---|
| `supervisor/graph.py` | – | – | 直接 | – | – | 直接 | – | – | – |
| `supervisor/routing.py` | – | – | – | – | – | – | – | – | – |
| `supervisor/state.py` | – | – | – | – | – | 直接 | – | – | – |
| `runtime_plane/nodes/pure/*` | – | – | – | – | – | 直接 | – | – | – |
| `runtime_plane/nodes/agent_plane/*` | – | 直接 | 直接 | – | – | 直接 | 直接 | 间接 | **可能** |
| `runtime_plane/tool_loop.py` | – | – | – | – | – | – | 直接 | – | **是** |
| `runtime_plane/stage_tools.py` | – | – | – | – | – | 直接 | 直接 | 间接 | – |
| `runtime_plane/guards.py` | – | – | – | – | – | 直接 | – | – | – |
| `design|verify|coverage|debug/{graph,loop}` | – | 直接 | 直接 | – | – | 直接 | 直接 | 间接 | **是** |
| `gates/{audit,human}.py` | – | – | – | 直接 | – | 直接 | – | – | – |
| `registry.py` | – | – | – | – | – | – | – | – | – |
| `stage_policy.py` | – | – | – | – | – | – | – | – | – |

## 3. 目标依赖方向

```text
generation  →  ir, tools            # 不 import engine / agent
engine      →  ir, runtime, tools   # 不 import generation / agent
agent       →  engine, generation, ir, runtime
orchestration(engine) → generation  # 只允许调度 Stage 执行器
```

违反方向的具体点：

1. `design/main.py`、`model/main.py` 在生成文件里直接调 EDA 检查 →
   第二轮把检查函数抽到 `engine_plane/design/`。
2. `verify/main.py`写确定性 IR 关联 → 第二轮抽到 `engine_plane/verify/`。
3. `debug/main.py` 自己找波形并解析 → 改为调用 `engine_plane/diagnostics`。
4. `orchestration_plane/` 允许 import `generation` 的 Stage executor 类（注册表），
   但不得调用其中的 LLM 生成函数。

## 4. 注册与运行期依赖

| 位置 | 依赖 |
|---|---|
| `src/orchestration_plane/l2/execution_helpers.py` | `_EXECUTOR_PATHS` 点路径 → 8 个 Stage 执行器 |
| `src/workbench/cli/commands.py` | `initialize()` 实例化 7 个执行器 |
| `src/orchestration_plane/l2/execution_loop.py` | `engine.orchestration.supervisor.graph.build_closed_loop_graph` |
| `src/orchestration_plane/registry.py` | `KNOWN_STAGES` 静态能力集合（不再扫描目录） |
| `src/workbench` | supervisor graph（只读运行历史） |

## 5. 已有测试覆盖（未执行）

| 域 | 测试 |
|---|---|
| front/VPlan | `tests/test_vplan_*`、`tests/test_dplan_*` |
| design/model | `tests/test_design_loop.py`、`tests/test_model_gate.py` |
| verify | `tests/test_vplan_sva_contract.py`、`tests/test_stages.py` |
| ops | `tests/test_regression*`、`tests/test_staged_regression.py` |
| debug | `tests/test_debug_fake_eda.py`、`src/agent_plane/specialists/debug/test_debug_waveform.py` |
| coverage | `tests/test_coverage*` |
| audit | `tests/test_approval.py`、`tests/test_manual_node_gate.py` |
| orchestration | `tests/test_supervisor_graph.py`、`test_state_contracts.py`、`test_architecture_invariants.py` |
