# SignOffAI 用户指南

> 版本：2026-11-18  
> 适用代码：`refactor/langgraph-migration`  
> 原则：Agent 负责理解、生成、分析、提出修复；确定性 Engine 负责执行、检查、裁决与签核。**没有真实执行证据的能力保持 `NOT_RUN` / `NOT_IMPLEMENTED`，不补造 PASS。**

---

## 1. 系统定位

SignOffAI 是一个 evidence-driven 的 IC 设计验证系统：

- **Agent Plane**：理解、规划、生成、诊断、修复建议；
- **Engine Plane**：编译、仿真、覆盖率、诊断、证据、签核；
- **IR 根**：`src/mental_ir_plane/` 统一承载 Mental / DPlan / VPlan 与执行契约；
- **Interfaces**：CLI（headless）、PySide6 UI / TUI（interactive）；
- **ChipStack 2.0 工程目录**：L0–L5 分层、run manifest、agent 产物目录、归档与日志。

本仓库不内置 Cadence JasperGold / SuperLint / Verisium / Joules / Stratus 等专有后端。缺失时相关命令会明确提示 `NOT_IMPLEMENTED` 或保持 `NOT_RUN`。

---

## 2. 安装与环境

### 2.1 安装依赖

```powershell
# 仓库根目录
& .\venv\Scripts\python.exe -I -m pip install -r .\requirements.txt
```

本机 pip 建议使用清华源；`requirements.txt` 含中文注释，Windows 下需要 UTF-8 模式：

```powershell
$env:PYTHONUTF8 = "1"
& .\venv\Scripts\python.exe -m pip install -r requirements.txt `
  -i https://pypi.tuna.tsinghua.edu.cn/simple `
  --trusted-host pypi.tuna.tsinghua.edu.cn
```

### 2.2 检查环境

```powershell
& .\venv\Scripts\python.exe -m pip check
& .\venv\Scripts\python.exe -m src.workbench.cli.commands --help
```

需要 EDA 时，`vlog / vopt / vsim / vcover` 必须在 PATH（已验证 QuestaSim 2024.1）。没有 EDA 时，编译/仿真相关步骤会走 `BLOCKED_EDA_MISSING` / `INCOMPLETE`，这是设计行为，不是伪装失败。

### 2.3 可执行入口

- 已安装 console script：`vagent ...`
- 未安装或用模块方式：`python -m src.workbench.cli.commands ...`

本指南中的 `vagent` 均可替换为后一种形式。

---

## 3. 两种前端模式

| 模式 | 定位 | 入口 |
|---|---|---|
| CLI（headless） | 脚本、CI、回归 | `vagent <agent> ...`、`vagent chat --mode ...`、`vagent verify ...` |
| PySide6 UI / TUI（interactive） | 人工交互、监控、审批、Markdown 产物 | `vagent gui`、`vagent tui`、`vagent chat --repl` |

`chat / plan / verify` 是两种前端共用的交互方式，不是第三种前端。

```bash
vagent modes                 # 查看两种模式与能力
vagent modes --json
```

### 3.1 交互语义

- `chat`：普通对话；执行类操作仍需审批；
- `plan`：返回真实 `pending.kind=plan` 检查点，必须人工审查；
- `verify`：只走确定性验证主链，不从聊天内容猜命令。

```bash
vagent chat "解释 VALID/READY 握手"
vagent chat --mode plan "为 DMA 制定验证计划"
vagent chat --mode verify "验证指定项目"
vagent chat --resume <session-id> --approve yes
```

---

## 4. 快速开始

### 4.1 初始化 ChipStack 工程

```bash
vagent project init sync_fifo --top sync_fifo
cd sync_fifo
vagent project layout          # L0–L5 目录树
vagent project check           # CS-DIR-REQ-001 §7 验收
```

就地初始化当前目录：

```bash
vagent workspace init --top sync_fifo --force
```

### 4.2 新建一次运行

```bash
vagent workspace new-run sync_fifo \
  --agents mental_model_agent,formal_agent,simulation_agent
vagent workspace runs
vagent workspace agents
```

默认运行目录：

```text
chipstack_artifacts/<top>-<YYYY_MM_DD_HH_MM_SS>/
```

### 4.3 查看产物

```bash
vagent workspace show
vagent workspace backup rtl/sync_fifo.sv --reason "RTL upgrade"
vagent workspace archive formal_agent
vagent project clean            # 删除产物根；输入与配置不受影响
```

---

## 5. 十个 Agent

`vagent agents list` 是权威清单。

| Agent | CLI 名 | TUI 模式 | 产物目录 | 当前状态 |
|---|---|---|---|---|
| Mental Model | `mental-model` | `mental_model` | `mental_model_agent/` | ✅ 生成 MentalIR |
| Unit Testing | `simulation-agent` | `unit_testing` | `simulation_agent/` | ✅ 生成纯 SV TB；EDA 缺失时 SKIPPED |
| Lint AutoFix | `lint-autofix-agent` | — | `lint_autofix/` | ✗ SuperLint 未内置 |
| RTL Upgrade | `experimental rtl-generation` | `rtl_designer` | `rtl_generation/` | ◐ 候选生成 + 备份约束 |
| RTL Early Estimation | `rtl-early-estimation` | — | `rtl_early_estimation_agent/` | ✗ Joules 未内置 |
| Formal | `formal-agent` | `formal` | `formal_agent/` | ✅ FormalPlan；✗ Jasper 全流程 |
| Functional Coverage | `functional-coverage-agent` | `functional_coverage` | `functional_coverage_agent/` | ◐ 只读工具；✗ covergroup 全流程 |
| Test Plan | `uvm-agentic-flow` | `uvm` | `test_plan_agent/` | ◐ 角色入口；✗ 全流程 |
| UVM Coding | `uvm-agentic-flow` | `uvm` | `uvm_agent/`（artifact root） | ◐ 生成/审批；✗ 完整 TB 管线 |
| DV Debug | `dv-debug-agent` | `debug` | `dv_debug/` | ◐ 确定性 DebugExecutor；✗ Verisium DB |

示例：

```bash
vagent mental-model chat "解释这份 spec 的验证目标"
vagent mental-model generate --spec spec/npu_sched.md --module npu_sched --out runs/mental
vagent simulation-agent run --rtl rtl/npu_sched.sv --module npu_sched --out runs/unit
vagent formal-agent plan --spec spec/npu_sched.md --module npu_sched --out runs/formal
vagent functional-coverage-agent chat "分析现有覆盖率报告"
vagent uvm-agentic-flow chat "检查 UVM testplan 结构"
vagent dv-debug-agent chat "分析这条 failing test"
vagent filelist-tools build --rtl-dir rtl --out rtl/top.f
```

没有后端的命令：

```bash
vagent formal-agent launch-full-flow --spec spec.md --module dut   # exit 2, NOT_IMPLEMENTED
vagent lint-autofix-agent run --rtl rtl/top.sv                     # exit 2, NOT_IMPLEMENTED
vagent dv-debug-agent auto-debug --simulation-db-path sim.db       # exit 2, NOT_IMPLEMENTED
vagent rtl-early-estimation run --rtl rtl/top.sv                   # exit 2, NOT_IMPLEMENTED
```

---

## 6. TUI 主窗口

TUI 与老 PySide6 GUI 并列，执行链相同。

```bash
vagent tui
vagent tui --mode mental_model
vagent tui --mode formal
vagent tui --mode functional_coverage
vagent tui --mode uvm
vagent tui --mode rtl_designer
vagent tui --mode debug
vagent tui --mode workflows

vagent tui --session-name fifo_review --mode mental_model
vagent tui --session-name fifo_review       # 恢复会话
```

界面包含：

- 当前领域模式 / 交互方式 / workspace / session；
- 7 个领域模式；
- 命名会话；
- 当前工程最新 run；
- 输入区与最近结果。

TUI 内命令：

```text
/agent mental_model|formal|functional_coverage|uvm|rtl_designer|debug|workflows
/mode chat|plan|verify
/md list|show|edit
/status /session /approve /deny /answer /plan /help /exit
```

TUI 会话索引：

```text
chipstack_artifacts/tui/sessions/<session-name>.json
```

---

## 7. PySide6 GUI

```bash
vagent gui
vagent gui --mode formal
vagent gui run
```

常用页面：

| 页面 | 用途 |
|---|---|
| 项目 → 工程目录 | L0–L5 树、验收清单、运行索引、Agent 产物 |
| 项目 → 交互与验证 | 9 种 Agent 模式；chat/plan/verify；审批恢复 |
| 流程与证据 → 验证流程 | 启动闭环、阶段时间线、日志、审批 |
| 流程与证据 → 运行历史 | 选择运行，广播 `run.selected` |
| 流程与证据 → 证据 / 产物 | 原始文件树与覆盖率轨迹 |
| 流程与证据 → 产物审查 | 中间 YAML 编辑 + schema 诊断 + 证据链记账 |
| 流程与证据 → Markdown 产物 | 浏览/编辑/预览 `.md`，保存记证据链 |
| 平台配置 | 当前项目、清单、Python/Qt、EDA、数据库目录 |

边界：

- GUI 不拥有独立 Engine；
- 点击「启动验证」不等于 PASS；
- 没有 `session/pending` 就不显示审批区；
- 保存产物不会自动重跑。

---

## 8. 统一 IR 架构

唯一 IR 根：

```text
src/mental_ir_plane/
├── model.py / store.py        # 总：理解层（MentalIR）
├── dplan/                     # 总：设计与模型契约（dplan_ir_v1）
├── unified/                   # 总：Mental + DPlan + VPlan 融合
├── contract/ decision/ formal/ interface_timing/
├── proposal/ specification_compiler/ vplan/   # 分：引擎与契约
└── example/
```

### 8.1 Mental IR

```bash
vagent mental build spec/npu_sched.md -o runs/mental
vagent mental build <spec.md> -o <run> --json
```

产物：

```text
<run>/mental_ir/
├── mental_ir.json
├── mental_ir.yaml
└── manifest.json
```

### 8.2 DPlan IR

```bash
vagent mental dplan check specs/npu_sched/docs/specs/npu_sched_dplan.json
vagent mental dplan normalize <dplan.json> --out runs/dplan_ir.json
```

`dplan_ir_v1` 包含：

- interfaces / registers / features / modules；
- architecture：top / stages / method；
- model_contract：module / ports / state / behaviors / scoreboard；
- `embedded_vplan`：原 DPlan 内嵌的 VPlan-like 集合，保留但**不作为 VPlan 权威**；
- `extra`：未知字段。

### 8.3 VPlan

```bash
vagent vplan status  specs/npu_sched
vagent vplan review  specs/npu_sched
vagent vplan execute specs/npu_sched
```

### 8.4 统一 IR

```bash
vagent mental unify \
  --mental runs/mental/mental_ir/mental_ir.json \
  --dplan runs/dplan_ir.json \
  --vplan specs/npu_sched \
  --out runs/unified_ir.json \
  --views-out runs/unified_views.json
```

规则：

- 三投影（Mental / DPlan / VPlan）分别保留；
- DPlan↔VPlan 关系默认 `candidate`；
- 同名 native id 也只是候选，不自动升级；
- 缺输入、空 behaviors、乱码、重复 key 进入 `issues`；
- `Execution / Evidence` 仍是独立记录；
- 统一 IR **不是签核表**。

---

## 9. 工程目录与产物

L0–L5：

| 层 | 内容 |
|---|---|
| L0 安装层 | 只读源码/工具 |
| L1 用户配置层 | `$CHIPSTACK_HOME` 或 `~/.signoffai` |
| L2 工程输入层 | `spec/ rtl/ tb/ ecn/ ref/ scripts/ docs/` |
| L3 工程配置层 | `cli_config.yaml` |
| L4 产物层 | `chipstack_artifacts/` |
| L5 工作流层 | `workflows/` |

产物根：

```text
chipstack_artifacts/
├── run_manifest.json
├── artifacts.sqlite
├── compile_config.yaml
├── cli_logs/cli_YYYYMMDD-HHMMSS.log
├── Archive/<design>.<agent>.<timestamp>/
├── uvm_agent/                 # 2.0 手册：UVM 产物固定在 artifact root
├── tui/sessions/<name>.json
├── <top>/
└── <top>-<run_id>/
    ├── run_manifest.json
    ├── run_results/
    ├── backup/<timestamp>/
    └── <agent>/...
```

保留名（不能当 design root）：`Archive`、`tui_sessions`、`app_state`、`cli_logs`、`symphony_logs`、`tui`、`tmp`、`compile_fix`、`semantic_cache`。

### 9.1 配置

查找顺序（`vagent config lookup`）：

```text
--config > 安装目录 cli_config.yaml > $CHIPSTACK_HOME/cli_config.yaml > 工程根
```

关键组：`tools`、`flow`、`llm`、`context`、`mental_model`。  
`compile_config.yaml` 默认字段包括 `sv_version`、`uvm_path`、blackbox、错误/告警分类、宏/参数覆盖。

### 9.2 日志、备份、归档

- 每次 CLI 调用一份 `cli_logs/cli_*.log`；
- 修改 RTL 前：

  ```bash
  vagent workspace backup rtl/top.sv --reason "ECN-123"
  ```

- 归档：

  ```bash
  vagent workspace archive formal_agent
  ```

  命名：`<design>.<agent>.<timestamp>`。

---

## 10. Skills / 离线产物浏览器

```bash
vagent setup seed-skills
vagent install-skills claude-code
vagent install-skills claude-code --project
```

生成单文件离线产物浏览器（不启动 Web 服务）：

```bash
vagent setup artifact-review-html --run chipstack_artifacts/<top>-<run> --out review.html
```

`vagent mcp run` 当前明确 `NOT_IMPLEMENTED`，不启动假服务。

---

## 11. 端到端示例：Mental + DPlan + VPlan

以 `npu_sched` 为例：

```bash
# 1. Mental IR（LLM）
vagent mental build specs/npu_sched/docs/specs/npu_sched.md -o runs/mental_npu

# 2. DPlan
vagent mental dplan check specs/npu_sched/docs/specs/npu_sched_dplan.json
vagent mental dplan normalize specs/npu_sched/docs/specs/npu_sched_dplan.json \
  --out runs/npu_dplan_ir.json

# 3. VPlan 检查
vagent vplan status specs/npu_sched

# 4. 统一 IR
vagent mental unify \
  --mental runs/mental_npu/mental_ir/mental_ir.json \
  --dplan runs/npu_dplan_ir.json \
  --vplan specs/npu_sched \
  --out runs/npu_unified_ir.json \
  --views-out runs/npu_unified_views.json
```

本次实际运行结果（2026-11-18）：

| 项目 | 结果 |
|---|---|
| Mental | 12 goals / 7 assumptions / 15 ambiguities（4 blocking）/ 12 intents / 10 risks |
| DPlan | 328 interfaces / 43 features / 6 modules / 274 model ports / 8 states / 0 behaviors |
| VPlan | 26 req / 43 features / 46 contracts（assume）/ 58 TP / 20 cases |
| Unified | 634 实体 / 471 关系（357 confirmed + 114 candidate）/ 7 issues |
| 三投影 | Mental 56 / DPlan 428 / VPlan 150 |
| 完整性 | 实体 id 全唯一；关系端点全部可解析；digest 读回一致 |

注意：

- DPlan 的空 `behaviors` 被记录为缺口；
- 4 条 blocking ambiguity 需要人工澄清；
- 内嵌 VPlan-like 集合保留但不重复计数；
- 本轮未跑 EDA / VPlan execute。

---

## 12. 当前限制

| 能力 | 状态 |
|---|---|
| JasperGold formal 全流程 | 未内置；`formal-agent launch-full-flow` NOT_IMPLEMENTED |
| SuperLint | 未内置；`lint-autofix-agent run` NOT_IMPLEMENTED |
| Verisium Debug / xcelium DB | 未内置；`dv-debug-agent auto-debug` NOT_IMPLEMENTED |
| Joules PPA / Stratus HLS | 未内置 |
| Functional coverage covergroup 全流程 | 未内置 |
| UVM 完整 TB 管线 | 仅角色与候选生成 |
| ChipStack YAML workflow DAG | 未实现；现有 supervisor 为代码图 |
| Web 服务器 / SSE | 项目规则禁止；提供单文件 HTML 导出 |
| MCP server | 未内置 |
| VSCode Extension | 外部扩展，不在仓库内 |

---

## 13. 常见问题

### `UnicodeDecodeError: 'gbk' codec ...`

`requirements.txt` 含中文注释；安装时设置：

```powershell
$env:PYTHONUTF8 = "1"
```

### `No module named 'agents'`

`openai-agents` 未安装或不在当前解释器：

```powershell
& .\venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

### `No module named 'langchain*'`

确认使用仓库 venv，并检查 `pip check`：

```powershell
& .\venv\Scripts\python.exe -m pip check
```

### LLM 连接失败

- 确认 `.env` 中 key 已设置；
- 如果系统代理为 `127.0.0.1:7897`，代理未启动时 httpx 会读取注册表并失败；
- 可临时关闭代理或启动代理后重试。

### `BLOCKED_EDA_MISSING`

`vlog/vsim` 不在 PATH。两者不存在时，系统会明确降级为 `INCOMPLETE` / `BLOCKED_EDA_MISSING`，不伪造 PASS。

### `vagent gui` 打不开

PySide6 缺失：

```powershell
& .\venv\Scripts\python.exe -m pip install PySide6 qdarkstyle
```

---

## 14. 文档索引

- [README](README.md)
- [ARCHITECTURE_4.0](ARCHITECTURE_4.0.md)
- [ChipStack 2.0 对齐矩阵](docs/architecture/CHIPSTACK_2_ALIGNMENT.md)
- [ChipStack 工程目录](docs/architecture/CHIPSTACK_PROJECT_LAYOUT.md)
- [Mental IR](docs/architecture/MENTAL_IR.md)
- [融合 IR：Mental + DPlan + VPlan](docs/architecture/IR_FUSION_MENTAL_DPLAN_VPLAN.md)
- [Agent Domain 与 ReAct 布局](docs/architecture/AGENT_DOMAIN_LAYOUT.md)
- [交互模式](docs/architecture/INTERACTION_MODES.md)
- [文档总索引](docs/INDEX.md)
