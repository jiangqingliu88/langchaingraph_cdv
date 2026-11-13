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
├── agent_plane/          # runtime / planner / specialists / collaboration / memory
├── orchestration_plane/  # supervisor / nodes / gates / registry + l2
├── generation_plane/     # design{rtl,cmodel} / verification / planning / *_tools
├── engine_plane/         # front / verify / ops / coverage / audit / diagnostics
├── ir_plane/             # vplan / contract / proposal + decision
├── knowledge_plane/
├── experience_plane/
├── runtime_plane/        # core / infrastructure / tools / utils + task_store/session
└── workbench/            # Interfaces：cli / api / modes / ui
```

边界由 `config/architecture_guard.py` 强制执行：

- Engine 不得 import Generation / Agent；
- Generation 不得 import Agent；
- 未登记模块、逆向依赖直接失败；
- 预算只能收紧，新增债务必须 `--approve-debt` 人工批准。

---

## 安装

```bash
# 仓库自带 venv（Windows）
./venv/Scripts/python.exe -m pip install -e . --no-deps

# 或普通环境
python -m pip install -e .
```

EDA 端到端需要 `vlog / vopt / vsim / vcover` 在 PATH（QuestaSim 2024.1 验证通过）。

---

## 快速开始

```bash
# 交互式 REPL
python -m src.workbench.cli.commands

# 单次任务（agent 模式）
python -m src.workbench.cli.commands -p "分析 specs/npu_sched 的 RTL 接口并给出验证计划"

# 确定性 verify 模式
python -m src.workbench.cli.commands -p "跑 VPlan 验证并报告证据" --mode verify
```

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

### VPlan / 回归 / 签核

```bash
python -m src.workbench.cli.commands vplan status   <project>
python -m src.workbench.cli.commands vplan review   <project>   # 人工审阅
python -m src.workbench.cli.commands vplan execute  <project>
python -m src.workbench.cli.commands verify         <spec>
python -m src.workbench.cli.commands runs list
```

---

## Architecture Guard 2.0

```bash
python -m config.architecture_guard                 # 检查
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

当前基线：**1249 passed, 14 skipped**；guard **OK**。

测试集合包括 Guard 单向债务、VPlan 证据、Staged 回归、SVA 契约、SoC 适配、
Supervisor 状态机、Harness 多轮会话、安全边界等。

---

## 文档

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
- `orchestration_plane/l2`、`ir_plane/decision` 是原 L2/L3 的迁移落点，后续继续按
  职责下沉到 Engine / IR。
