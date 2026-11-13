# Engine Stage Ownership (Architecture 4.0)

> 审计对象（迁移前）：`src/engine_plane/stages/` 的 8 个 Stage 与 `src/engine_plane/agents/` 的流程代码。
> 审计方式：静态 import/调用分析（`ast` + grep），未执行 pytest。
> 每个文件只分配**一个主归属**；混合职责在“备注”里标出，第二轮再拆。

## 0. 归属原则

| 归属 | 判据 |
|---|---|
| `generation_plane/` | 产出候选设计/验证工件；可以调用 LLM；产物必须可追溯 |
| `engine_plane/` | 确定性解析、检查、执行、诊断、覆盖率、证据与裁决；**不得调用 LLM** |
| `agent_plane/` | 推理、规划、根因分析、修复建议；LLM 驱动 |
| `ir_plane/` | 机器可检查的语义模型与契约 |

Stage 是**工作流节点**，不是代码责任边界。一个 Stage 可以调用
`generation_plane/`、`engine_plane/`、`agent_plane/` 中的模块，但这些模块不因此搬进 Stage。

## 1. Stage 顶层归属

| 原 Stage | 主要职责 | 主归属 | 说明 |
|---|---|---|---|
| `front` | 项目/规格解析、VPlan bootstrap | `engine_plane/front` | `dplan/extract.py` 调 LLM，拆到 `generation_plane/planning` |
| `design` | RTL 生成 | `generation_plane/design/rtl` | 文件内混有 vlog 检查，标为债务 |
| `model` | C Model 生成 | `generation_plane/design/cmodel` | `_verify_model()` 属确定性检查，后续拆到 `engine_plane/design/cmodel` |
| `verify` | UVM / SVA / testcase 生成与 IR 组装 | `generation_plane/verification` | `ir_artifacts/steps_dag/dut_checker` 属确定性建模，拆到 `engine_plane/verify` |
| `ops` | 编译/仿真/回归执行 | `engine_plane/ops` | 纯确定性 EDA |
| `coverage` | 覆盖率收集/统计/闭环 | `engine_plane/coverage` | 纯确定性 EDA |
| `audit` | 证据、校验、签核裁决 | `engine_plane/audit` | 纯确定性 |
| `debug` | 失败分析（LLM）+ 日志/波形解析（确定性） | 拆分 | `main.py` → `agent_plane/specialists/debug`；`tools/` → `engine_plane/diagnostics` |

## 2. 文件级归属

### 2.1 `front`

| 文件 | 主归属 | 备注 |
|---|---|---|
| `front/__init__.py` | `engine_plane/front` | re-export |
| `front/main.py` | `engine_plane/front` | 项目加载、RTL/spec 解析编排；无 LLM |
| `front/vplan/__init__.py` | `engine_plane/front/vplan` | |
| `front/vplan/extract.py` | `engine_plane/front/vplan` | 确定性 bootstrap 表/资产 |
| `front/vplan/validate.py` | `engine_plane/front/vplan` | 格式校验 |
| `front/vplan/dplan_csv.py` | `engine_plane/front/vplan` | CSV 读写 |
| `front/dplan/__init__.py` | `generation_plane/planning/dplan` | |
| `front/dplan/extract.py` | `generation_plane/planning/dplan` | **LLM** 抽 dplan/contract |

### 2.2 `design`

| 文件 | 主归属 | 备注 |
|---|---|---|
| `design/__init__.py` | `generation_plane/design/rtl` | |
| `design/main.py` | `generation_plane/design/rtl` | `_llm_write_ip/_llm_write_top/_generate_rtl` 为生成；`_is_valid_rtl/_verify_ip_rtl` 为确定性检查（债务） |

### 2.3 `model`

| 文件 | 主归属 | 备注 |
|---|---|---|
| `model/__init__.py` | `generation_plane/design/cmodel` | |
| `model/main.py` | `generation_plane/design/cmodel` | `_verify_model()` 属 `engine_plane/design/cmodel`（债务） |

### 2.4 `verify`

| 文件 | 主归属 | 备注 |
|---|---|---|
| `verify/__init__.py` | `generation_plane/verification` | |
| `verify/main.py` | `generation_plane/verification` | UVM/SVA/testcase 编排 |
| `verify/steps/*` | `generation_plane/verification/steps` | 生成 TP/case/env/constraint/SVA |
| `verify/ir_artifacts.py` | `engine_plane/verify` | 确定性 Verification IR 落盘 |
| `verify/steps_dag.py` | `engine_plane/verify` | 确定性步骤 DAG 校验 |
| `verify/dut_checker.py` | `engine_plane/verify` | 确定性 DUT checker 建模 |
| `verify/steps/vplan_layout.py` | `engine_plane/verify` | 资产布局/打包（确定性） |
| `verify/steps/interface_spec.py` | `engine_plane/verify` | 接口规格解析（确定性） |

### 2.5 `ops` / `coverage` / `audit`

| 文件 | 主归属 |
|---|---|
| `ops/__init__.py`, `ops/main.py` | `engine_plane/ops` |
| `coverage/__init__.py`, `coverage/main.py`, `coverage/functional_coverage.py` | `engine_plane/coverage` |
| `audit/__init__.py`, `audit/main.py`, `audit/helpers.py` | `engine_plane/audit` |

### 2.6 `debug`

| 文件 | 主归属 | 备注 |
|---|---|---|
| `debug/__init__.py` | `agent_plane/specialists/debug` | |
| `debug/main.py` | `agent_plane/specialists/debug` | `_llm_analyze/_llm_regenerate_file` 为 LLM |
| `debug/test_debug_waveform.py` | `agent_plane/specialists/debug` | 测试随代码走 |
| `debug/tools/__init__.py` | `engine_plane/diagnostics` | |
| `debug/tools/main.py` | `engine_plane/diagnostics` | 日志/编译错误解析、指纹、bisect |
| `debug/tools/waveform.py` | `engine_plane/diagnostics` | Questa 波形转信号时间线 |
| `debug/tools/signal_diagnosis.py` | `engine_plane/diagnostics` | 确定性信号/时序对比 |
| `debug/tools/test_debug_tools.py` | `engine_plane/diagnostics` | |
| `debug/tools/test_waveform.py` | `engine_plane/diagnostics` | |

### 2.7 `engine_plane/agents`（原“Agent”命名收敛）

| 文件 | 主归属 | 说明 |
|---|---|---|
| `agents/__init__.py` | 删除 | 空包 |
| `agents/supervisor/{__init__,graph,routing,state}.py` | `orchestration_plane/supervisor` | 确定性工作流调度 |
| `agents/runtime_plane/{guards,markers}.py` | `orchestration_plane/` | 节点守卫/标记 |
| `agents/runtime_plane/nodes/pure/*` | `orchestration_plane/nodes/pure` | 确定性节点（approval/lifecycle/rounds/apply/converge） |
| `agents/runtime_plane/nodes/agent_plane/*` | `agent_plane/runtime_plane/pipeline_nodes` | 调工具/Stage 的 agentic 节点 |
| `agents/runtime_plane/tool_loop.py` | `agent_plane/runtime_plane/tool_loop.py` | **LLM** 工具循环 |
| `agents/runtime_plane/stage_tools.py` | `agent_plane/runtime_plane/stage_tools.py` | Stage 工具适配 |
| `agents/registry.py` | `orchestration_plane/registry.py` | AgentCard 能力表（静态） |
| `agents/stage_policy.py` | `orchestration_plane/stage_policy.py` | 阶段策略校验 |
| `agents/design/*` | `agent_plane/specialists/design` | LLM 设计专家 |
| `agents/verify/*` | `agent_plane/specialists/verify` | LLM 验证专家 |
| `agents/coverage/*` | `agent_plane/specialists/coverage` | LLM 覆盖率专家 |
| `agents/debug/*` | `agent_plane/specialists/debug` | LLM 调试专家 |
| `agents/gates/{audit,human}.py` | `engine_plane/audit/gates` | 人工/审计门 |

## 3. 混合职责债务（第二轮拆分）

| 文件 | 混合内容 | 建议 |
|---|---|---|
| `generation_plane/design/rtl/main.py` | 生成 + vlog 编译检查 | `_is_valid_rtl/_verify_ip_rtl` 抽到 `engine_plane/design/rtl/compile` |
| `generation_plane/design/cmodel/main.py` | 生成 + 编译验证 | `_verify_model` 抽到 `engine_plane/design/cmodel/compile` |
| `generation_plane/verification/main.py` | 生成 + 确定性 IR/assoc 写入 | `_write_association_report/_annotate_coverage_plan` 抽到 `engine_plane/verify` |
| `agent_plane/specialists/debug/main.py` | LLM 分析 + 波形/信号取数 | 取数调用 `engine_plane/diagnostics`，不自己解析 |

## 4. 本轮不动的边界

- `src/runtime_plane/`（l1 基础设施、l2 调度、l3 case/evidence）暂不改名。
- `src/runtime_plane/tools/`（UVM 模板、EDA 适配、common）暂不改名；`generation` 迁移已完成一轮。
- `src/workspace/` 的 gate 流程保留，作为 `engine_plane/audit` 的上层包装。
