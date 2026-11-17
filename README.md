# SignOffAI

**An Evidence-Driven Autonomous IC Verification System**

由专业 Agent 驱动、确定性 Engine 执行与裁决、统一 IR 连接、Evidence 保证可追溯性的
自主 IC 设计验证系统。

> **Agent 可以生成和修改设计，可以提出 PASS/FAIL 建议；只有确定性 Engine 和受控
> Gate 才能形成正式验证结论。**

---

## Architecture 4.0：8 个职责平面 + Workbench

| 平面 | 负责 | 不负责 |
|---|---|---|
| **Agent Plane** | 理解需求、规划、生成、诊断、提出修复 | 签核裁决 |
| **Orchestration Plane** | 任务分解、调度、状态机、重试、人工审批 | 编译/仿真 |
| **Generation Plane** | RTL / UVM / SVA / C Model / testcase 候选产物 | 宣布产物正确 |
| **Engine Plane** | 解析、检查、编译、仿真、覆盖率、诊断、证据、签核 | 调用 LLM |
| **IR Plane** | Intent / Execution / Evidence / Case IR 语义契约 | 执行 EDA |
| **Knowledge Plane** | 协议、IP、设计规范知识 | 推理决策 |
| **Experience Plane** | 历史失败、修复记录、覆盖率闭合策略 | 替代知识库 |
| **Runtime Plane** | 进程、权限、工作区、会话、EDA 环境、任务恢复 | 验证业务逻辑 |
| **Workbench** | CLI / API / GUI（Interfaces Plane） | 独立验证引擎 |

```text
src/
├── agent_plane/          # Agent 内部 Domain 分组，不新增架构 Plane
│   ├── domains.py        # 五个 Domain ↔ R-020 产物目录的权威注册表
│   ├── reaction/         # openai-agents Agent/Runner、模型与工具适配
│   ├── design_understanding/ design_verification/ design_signoff/
│   ├── design_generation/ verification/  # 十个独立 SDK ReAct 角色
│   ├── common.py         # 独立专家的 LLM 校验/原子落盘骨架
│   └── runtime/ planner/ collaboration/ memory/
├── orchestration_plane/  # supervisor / nodes / gates / registry + l2
├── generation_plane/     # design{rtl,cmodel} / verification / planning / *_tools
├── engine_plane/         # front / verify / ops / coverage / audit / diagnostics
├── mental_ir_plane/      # 唯一 IR 根
│   ├── model.py/store.py # 理解层（MentalIR）
│   ├── dplan/            # 设计与模型契约（dplan_ir_v1）
│   ├── unified/          # Mental + DPlan + VPlan 统一对象图
│   └── contract/ decision/ formal/ interface_timing/ proposal/ specification_compiler/ vplan/
├── knowledge_plane/
├── experience_plane/
├── runtime_plane/        # core / infrastructure / tools / utils + task_store/session
│   ├── core/project_layout.py  # ProjectLayout：ChipStack L0–L5 工程目录契约
│   └── artifacts/        # 产物工作区投影 + project_layout 兼容入口
└── workbench/            # Interfaces：cli / api / modes（含 modes/chats 对话入口）/ ui
```

**工程目录**按 ChipStack `CS-DIR-REQ-001` 的 L0–L5 五层模型组织：输入
（`spec/ rtl/ tb/ ecn/ ref/`）与产物（`chipstack_artifacts/`）物理分离，每次
运行有 `run_manifest.json`、CLI 日志、agent 固定子目录与可清理/归档的产物根。
CLI 入口 `vagent project {init,layout,check,runs}` 与 `vagent workspace
{new-run,agents,backup,archive}`；GUI 在「项目 → 工程目录」。详见
[CHIPSTACK_PROJECT_LAYOUT.md](docs/architecture/CHIPSTACK_PROJECT_LAYOUT.md)。

边界由 `config/architecture_guard.py` 强制执行：

- Engine 不得 import Generation / Agent；
- Generation 不得 import Agent；
- 未登记模块、逆向依赖直接失败；
- 预算只能收紧，新增债务必须 `--approve-debt` 人工批准。

---

## 安装

```powershell
# 仓库根目录：按已合并的 requirements.txt 安装（含 Agent 扩展与约束）
& .\venv\Scripts\python.exe -I -m pip install -r .\requirements.txt

# 或在新的 Python 环境按项目自身依赖安装
python -m pip install -e ".[dev,gui]"
```

`requirements.txt` 包含基础依赖和核验后的 Agent Stack。它由基础清单与
`requirements/agent-stack-resolved.txt` 合并去重而来。重新运行
`python scripts/sync_requirements.py` 会按基础 `pyproject.toml` 重建，不应在
没有保留 Agent 扩展段时直接覆盖该文件。

`-I` 用于隔离外部 `PYTHONPATH`，确保调用项目 venv 而不是另一环境的 pip。
本仓库核对版本为 `openai-agents==0.24.0`、`openai==3.51.0`，并保留项目的
`langchain-core==1.6.6`。普通模型生成、数据库服务和观测上报都仍需各自配置，
安装上述包不等于这些外部能力已经启动。

EDA 端到端需要 `vlog / vopt / vsim / vcover` 在 PATH（QuestaSim 2024.1 验证通过）。

---

## 快速开始

两种前端模式：**CLI（headless）** 与 **PySide6 UI / TUI（interactive）**。
`chat / plan / verify` 是两者共用的交互方式，不是第三种前端。

```bash
# 查看两种前端模式
python -m src.workbench.cli.commands modes

# CLI headless：单次任务 / 确定性 verify / 每个 agent 的子命令
python -m src.workbench.cli.commands -p "分析 specs/npu_sched 的 RTL 接口并给出验证计划"
python -m src.workbench.cli.commands -p "跑 VPlan 验证并报告证据" --mode verify
python -m src.workbench.cli.commands formal chat "生成 FormalPlan"

# UI / TUI：PySide6 或终端 REPL（按 chat/plan/verify 区分任务）
python -m src.workbench.cli.commands gui
python -m src.workbench.cli.commands
python -m src.workbench.cli.commands chat --repl --mode plan
```

### Workbench（GUI）

```bash
python -m src.workbench
```

导航树按 Architecture 4.0 的 8 个职责平面分组；「架构治理 → 架构 4.0 平面」
显示各平面职责、禁止项、文件数和 Architecture Guard 状态。GUI 是任务发起、
审批与展示的交互入口，本身不拥有独立 Engine；界面完成展示不等于 Engine 已给出通过结论。

### DMA / SoC 端到端

```bash
# 输入检查（不跑 EDA）
python -m src.workbench.cli.commands soc check examples/open_npu_soc

# 真实 Questa 回归（参考 TB + E203 C 用例，含 DMA）
python -m src.workbench.cli.commands soc run examples/open_npu_soc -o output_dma_e2e

# 证据与报告
python -m src.workbench.cli.commands soc report   output_dma_e2e_*/
python -m src.workbench.cli.commands soc evidence output_dma_e2e_*/
```

已验证结果：

- build / test **4/4 PASS**；
- `gemm_8x8`（参考 TB）：`mismatched=0` / `PASS`；
- `gemm_8x8_c`（E203 C 用例）：`TEST_PASS`；
- 证据包 27 文件，`soc evidence` 哈希校验通过；
- DMA 信号链：`dma_load → dma_store → dma_busy → c_we`（波形 `u_dma`）。

### Resource / Interaction IR（M1）

```bash
# intent → resources/operations/interactions → 确定性冲突与场景
vagent resource verify examples/open_npu_soc/spec/dma_gemm_interaction.yaml
vagent resource verify examples/open_npu_soc/spec/dma_gemm_conflict.yaml
```

覆盖无重叠 / 完全重叠 / 部分重叠 / 边界相邻四类场景；结论为
`PASS / FAIL / INCOMPLETE`，可 `--out` 落盘 `resource_intent_result.json`。

SoC 主链：`examples/open_npu_soc/spec/resource_intent.yaml` 存在时，`soc run`
会先做确定性 preflight；`FAIL/INCOMPLETE` 直接不跑回归。结果写入
`coverage/resource_intent_result.json` 并进入签核证据包。

### Evidence v2（M2）

```bash
vagent evidence audit <run>/signoff_evidence          # 完整性/有效性/可信度
vagent evidence stale <run>/docs/provenance.jsonl current_inputs.json
```

`audit` 把“文件存在”升级为“section 齐全 + 哈希匹配 + manifest 可信”；
`stale` 用当前输入 hash 对比 provenance，输出失效清单。

### 受控修复（M4）

```bash
vagent repair validate proposal.json --project-root <project>
vagent repair stage proposal.json --staging <staging-dir> --project-root <project>
```

修复只能写 staging；`signoff_evidence/ contract/ coverage/ config/ .signoffai/`
等保护路径直接拒绝；`requires_engine_verification=true`，Engine 复验前不产生 PASS。

### VPlan / 回归 / 签核

```bash
python -m src.workbench.cli.commands vplan status   <project>
python -m src.workbench.cli.commands vplan review   <project>   # 人工审阅
python -m src.workbench.cli.commands vplan execute  <project>
python -m src.workbench.cli.commands verify         <spec>
python -m src.workbench.cli.commands runs list
```

---

## Architecture Guard 2.1

```bash
python -m config.architecture_guard                 # 检查
python -m src.workbench.cli.commands arch check     # CLI 入口
python -m src.workbench.cli.commands arch planes    # 8 平面 + 文件数
python -m src.workbench.cli.commands arch matrix    # zone 依赖矩阵
python -m config.architecture_guard --json          # 机器读
python -m config.architecture_guard --reduce-debt   # 只降不升，写 history
python -m config.architecture_guard --approve-debt \
    --key <file|file::Class.func> --reason "..." --approver "<human>"
```

规则文档：[`docs/architecture/ARCHITECTURE_GUARD_PRINCIPLES.md`](docs/architecture/ARCHITECTURE_GUARD_PRINCIPLES.md)

- 文件行数、函数圈复杂度、依赖方向、债务四个预算；
- `--update-baseline` 已移除，禁止整表覆盖；
- 嵌套函数独立计算；函数身份为 `file::Class.func`；
- 债务变更追加到 `config/architecture_debt_history.jsonl`。

---

## 测试

```bash
./venv/Scripts/python.exe -m pytest tests/ -q
./venv/Scripts/python.exe -m config.architecture_guard
```

历史全量测试基线：**1249 passed, 14 skipped**；这不是新十角色 SDK 适配层的当前全量测试数字。
新 Agent/依赖整理阶段的实际核查为：十个 SDK Agent 构造、SDK 消息/调用类型、隔离导入与
`pip check`、CLI 导入，以及 **Architecture Guard OK**。没有据此宣称模型生成正确性、
EDA、仿真或全量回归已经通过。执行完整测试时，以当次实际输出更新本节，而不是沿用旧计数。

测试集合包括 Guard 单向债务、VPlan 证据、Staged 回归、SVA 契约、SoC 适配、
Supervisor 状态机、Harness 多轮会话、安全边界等。

---

## 文档

- [文档总索引](docs/INDEX.md)（当前说明、学习笔记与历史记录）
- [ChipStack 工程目录架构（L0–L5）](docs/architecture/CHIPSTACK_PROJECT_LAYOUT.md)
- [ChipStack 2.0 对齐矩阵](docs/architecture/CHIPSTACK_2_ALIGNMENT.md)
- [Agent Domain / SDK 目录](docs/architecture/AGENT_DOMAIN_LAYOUT.md)
- [独立专家与兼容入口](docs/architecture/SPECIALIST_AGENTS.md)
- [交互模式](docs/architecture/INTERACTION_MODES.md)
- [Architecture 4.0](ARCHITECTURE_4.0.md)
- [Stage Ownership](docs/architecture/STAGE_OWNERSHIP.md)
- [Stage Migration Plan](docs/architecture/STAGE_MIGRATION_PLAN.md)
- [Stage Dependency Matrix](docs/architecture/STAGE_DEPENDENCY_MATRIX.md)
- [Architecture Guard Principles](docs/architecture/ARCHITECTURE_GUARD_PRINCIPLES.md)
- [Security](SECURITY.md)
- [TODO / 技术债](TODO.md)

---

## 已知边界

- SoC DMA 端到端当前覆盖回归、波形、证据；功能覆盖率闭环需另跑 coverage 阶段。
- 四个生成/诊断文件仍混有确定性检查函数（design/cmodel/verification/debug），
  第二轮将把这些函数抽到 `engine_plane/`。
- import 环检测、字符串拼接动态 import 尚未实现。
- `orchestration_plane/kernel`、`mental_ir_plane/decision` 是原 L2/L3 的迁移落点，后续继续按
  职责下沉到 Engine / IR。
