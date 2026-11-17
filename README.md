# SignOffAI

**An Evidence-Driven Autonomous IC Verification System**

由专业 Agent 驱动、确定性 Engine 执行与裁决、统一 IR 连接、Evidence 保证可追溯性的
自主 IC 设计验证系统。

> **Agent 可以生成和修改设计，可以提出 PASS/FAIL 建议；只有确定性 Engine 和受控
> Gate 才能形成正式验证结论。**

---

## 职责平面

| 平面 | 负责 | 不负责 |
|---|---|---|
| **Agent** | 理解、规划、生成、诊断、提出修复 | 签核裁决 |
| **Orchestration** | 任务分解、调度、状态机、重试、人工审批 | 编译/仿真 |
| **Generation** | RTL / UVM / SVA / C Model / testcase 候选产物 | 宣布产物正确 |
| **Engine** | 解析、检查、编译、仿真、覆盖率、诊断、证据、签核 | 调用 LLM |
| **IR** | Mental / DPlan / VPlan / Execution / Evidence 语义契约 | 执行 EDA |
| **Knowledge** | 协议、IP、设计规范知识 | 推理决策 |
| **Experience** | 历史失败、修复记录、覆盖率闭合策略 | 替代知识库 |
| **Runtime** | 进程、权限、工作区、会话、EDA 环境、任务恢复 | 验证业务逻辑 |
| **Interfaces** | CLI、PySide6 UI/TUI、API | 独立验证引擎 |

```text
src/
├── agent_plane/              # 五个 Agent Domain + ReAct 角色
│   ├── domains.py            # Agent ↔ CLI/TUI ↔ 产物目录 权威注册表
│   ├── reaction/             # openai-agents Agent/Runner、模型与工具适配
│   ├── design_understanding/ design_verification/ design_signoff/
│   ├── design_generation/ verification/
│   └── runtime/ planner/ collaboration/ memory/
├── orchestration_plane/      # supervisor / nodes / gates / kernel
├── generation_plane/         # design / verification / planning / *_tools
├── engine_plane/             # front / verify / ops / coverage / audit / diagnostics
├── mental_ir_plane/          # 唯一 IR 根
│   ├── model.py / store.py   # 理解层（MentalIR）
│   ├── dplan/                # 设计与模型契约（dplan_ir_v1）
│   ├── unified/              # Mental + DPlan + VPlan 统一对象图
│   └── contract/ decision/ formal/ interface_timing/
│       proposal/ specification_compiler/ vplan/
├── knowledge_plane/
├── experience_plane/
├── runtime_plane/            # core / infrastructure / tools / artifacts
└── workbench/                # CLI / API / PySide6 UI / TUI
```

职责边界由 `config/architecture_guard.py` 强制执行：未登记模块、逆向依赖、超预算复杂度
直接失败；预算只能收紧。

---

## 统一 IR

`src/mental_ir_plane/` 是唯一 IR 根：

```text
总
├── model.py / store.py       MentalIR：goals / assumptions / ambiguities / intents / risks
├── dplan/                    DPlan IR：interfaces / features / modules / model_contract
└── unified/                  Mental + DPlan + VPlan 的项目作用域对象图

分
├── contract/                 VPlan / 测试点契约
├── decision/                 case IR、evidence、knowledge、spec tools
├── formal/                   FormalPlan
├── interface_timing/         Temporal IR / binding
├── proposal/                 受控修复 Proposal
├── specification_compiler/   Specification 编译契约
└── vplan/                    VPlan 加载 / 用例 / 执行 / 覆盖率
```

```bash
vagent mental build <spec.md> -o runs/mental
vagent mental dplan check <dplan.json>
vagent mental dplan normalize <dplan.json> --out runs/dplan_ir.json
vagent mental unify --mental ... --dplan ... --vplan ... --out runs/unified_ir.json
vagent vplan status|review|execute <project>
```

统一 IR 的规则：

- 三投影分别保留，不互相覆盖；
- 关系默认 `candidate`，同名 native id 也不自动升级；
- 缺输入、空 behaviors、乱码、重复 key 进入 `issues`；
- 不包含执行事实与签核结论。

---

## 两种前端模式

| 模式 | 定位 | 入口 |
|---|---|---|
| **CLI（headless）** | 脚本、CI、回归 | `vagent <agent> ...`、`vagent -p ...`、`vagent verify ...` |
| **PySide6 UI / TUI（interactive）** | 人工交互、监控、审批、Markdown 产物 | `vagent gui`、`vagent tui`、`vagent chat --repl` |

`chat / plan / verify` 是两种前端共用的交互方式，不是第三种前端。

```bash
vagent modes
vagent tui --mode formal --session-name fifo_review
vagent gui --mode formal
```

---

## 安装

```powershell
# 仓库根目录
& .\venv\Scripts\python.exe -I -m pip install -r .\requirements.txt
```

Windows 下 `requirements.txt` 含中文注释，pip 需要 UTF-8 模式：

```powershell
$env:PYTHONUTF8 = "1"
& .\venv\Scripts\python.exe -m pip install -r requirements.txt `
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

检查：

```powershell
& .\venv\Scripts\python.exe -m pip check
& .\venv\Scripts\python.exe -m src.workbench.cli.commands --help
```

EDA 端到端需要 `vlog / vopt / vsim / vcover` 在 PATH（已验证 QuestaSim 2024.1）。
没有 EDA 时，编译/仿真会明确降级为 `BLOCKED_EDA_MISSING` / `INCOMPLETE`，不伪造 PASS。

---

## 快速开始

```bash
# ChipStack 工程目录（L0–L5）
vagent project init sync_fifo --top sync_fifo
cd sync_fifo
vagent project layout
vagent project check

# 一次运行
vagent workspace new-run sync_fifo
vagent workspace runs
vagent workspace agents

# 10 个 Agent
vagent agents list
vagent mental-model chat "解释这份 spec 的验证目标"
vagent simulation-agent run --rtl rtl/sync_fifo.sv --module sync_fifo --out runs/unit
vagent formal-agent plan --spec spec/sync_fifo_spec.md --module sync_fifo --out runs/formal

# 统一 IR
vagent mental build spec/sync_fifo_spec.md -o runs/mental
vagent mental unify --mental runs/mental/mental_ir/mental_ir.json --vplan <project> \
  --out runs/unified_ir.json

# UI / TUI
vagent tui --mode mental_model
vagent gui
```

### 十个 Agent

| Agent | CLI 名 | TUI 模式 | 产物目录 |
|---|---|---|---|
| Mental Model | `mental-model` | `mental_model` | `mental_model_agent/` |
| Unit Testing | `simulation-agent` | `unit_testing` | `simulation_agent/` |
| Lint AutoFix | `lint-autofix-agent` | — | `lint_autofix/` |
| RTL Upgrade | `experimental rtl-generation` | `rtl_designer` | `rtl_generation/` |
| RTL Early Estimation | `rtl-early-estimation` | — | `rtl_early_estimation_agent/` |
| Formal | `formal-agent` | `formal` | `formal_agent/` |
| Functional Coverage | `functional-coverage-agent` | `functional_coverage` | `functional_coverage_agent/` |
| Test Plan | `uvm-agentic-flow` | `uvm` | `test_plan_agent/` |
| UVM Coding | `uvm-agentic-flow` | `uvm` | `uvm_agent/` |
| DV Debug | `dv-debug-agent` | `debug` | `dv_debug/` |

没有 Cadence 专有后端的命令显式返回 `NOT_IMPLEMENTED`，例如
`formal-agent launch-full-flow`、`lint-autofix-agent run`、`dv-debug-agent auto-debug`。

---

## 工程目录与产物

```text
<DESIGN_ROOT>/
├── cli_config.yaml
├── spec/ rtl/ tb/ ecn/ ref/ scripts/ docs/
├── workflows/
└── chipstack_artifacts/
    ├── run_manifest.json
    ├── artifacts.sqlite
    ├── compile_config.yaml
    ├── cli_logs/cli_YYYYMMDD-HHMMSS.log
    ├── Archive/<design>.<agent>.<timestamp>/
    ├── uvm_agent/
    ├── tui/sessions/<name>.json
    └── <top>-<run_id>/
        ├── run_manifest.json
        ├── run_results/
        ├── backup/<timestamp>/
        └── <agent>/...
```

```bash
vagent project layout / check / runs / agents
vagent workspace new-run / show / runs / agents
vagent workspace backup rtl/top.sv --reason "ECN-123"
vagent workspace archive formal_agent
vagent project clean
```

配置查找顺序：

```text
--config > 安装目录 cli_config.yaml > $CHIPSTACK_HOME/cli_config.yaml > 工程根
```

---

## 端到端验证

`npu_sched` 的 Mental + DPlan + VPlan 实测：

| 项目 | 结果 |
|---|---|
| Mental | 12 goals / 7 assumptions / 15 ambiguities（4 blocking）/ 12 intents / 10 risks |
| DPlan | 328 interfaces / 43 features / 6 modules / 274 model ports / 8 states / 0 behaviors |
| VPlan | 26 requirements / 43 features / 46 contracts / 58 testpoints / 20 cases |
| Unified IR | 634 entities / 471 relations（357 confirmed + 114 candidate） |
| 三投影 | Mental 56 / DPlan 428 / VPlan 150 |
| 完整性 | 实体 id 唯一；关系端点全部可解析；digest 读回一致 |

本轮核查：`compileall src tests`、关键导入、CLI、Architecture Guard、上述 IR 端到端。
未据此声明 EDA、formal proof、SuperLint 或完整 UVM 回归通过。

```bash
python -m config.architecture_guard
python -m config.architecture_guard --json
```

---

## 已知边界

- JasperGold / SuperLint / Verisium / Joules / Stratus 未内置；
- Functional coverage covergroup 全流程、UVM 完整 TB 管线未接入；
- ChipStack YAML workflow DAG 未实现，现有 supervisor 为代码图；
- 不提供 Web 服务器/SSE；需要离线查看时用 `vagent setup artifact-review-html`；
- MCP server 未内置；VSCode Extension 不在本仓库；
- 没有 EDA 时，编译/仿真保持 `INCOMPLETE` / `BLOCKED_EDA_MISSING`。

---

## 文档

- [用户指南](user_guide.md)
- [文档总索引](docs/INDEX.md)
- [总体架构](ARCHITECTURE_4.0.md)
- [ChipStack 2.0 对齐矩阵](docs/architecture/CHIPSTACK_2_ALIGNMENT.md)
- [ChipStack 工程目录（L0–L5）](docs/architecture/CHIPSTACK_PROJECT_LAYOUT.md)
- [Mental IR](docs/architecture/MENTAL_IR.md)
- [统一 IR：Mental + DPlan + VPlan](docs/architecture/IR_FUSION_MENTAL_DPLAN_VPLAN.md)
- [Agent Domain 与 ReAct 布局](docs/architecture/AGENT_DOMAIN_LAYOUT.md)
- [交互模式](docs/architecture/INTERACTION_MODES.md)
- [Architecture Guard 原则](docs/architecture/ARCHITECTURE_GUARD_PRINCIPLES.md)
- [Security](SECURITY.md)

---

## License

Apache-2.0
