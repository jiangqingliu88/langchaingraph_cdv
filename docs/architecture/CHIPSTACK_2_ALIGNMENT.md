# ChipStack 2.0 对齐矩阵

来源：`chipstack_user_guide.pdf`（Product Version 2.0, July 2026）学习摘要。
本文回答一件事：**哪些完全对齐、哪些是适配层、哪些明确未实现**。
原则不变：没有真实后端的能力保持 `NOT_RUN` / `NOT_IMPLEMENTED`，不补造报告。

## 1. 总体定位

| 2.0 概念 | 本仓库落点 | 状态 |
|---|---|---|
| coordinated multi-agent platform | 五个 Agent Domain + 10 个独立角色 | ✅ |
| Super-Agent 编排 | `orchestration_plane/supervisor` + `modes/router` | ◐ 代码图，不是 2.0 YAML workflow |
| Mental Model 共享基础 | `mental_ir_plane` + `design_understanding/mental_model_agent` | ✅（生成）/ ◐（一致性检查） |
| Cadence 专用 agent/工具 | Jasper / Verisium / xrun / Stratus / SuperLint | ✗ 未内置，保持 NOT_RUN |

## 2. 十个 Agent

权威注册表：`src/agent_plane/domains.py`（`vagent agents list`）。

| Domain | Agent | CLI 名 | TUI 模式 | 产物目录 | 当前能力 |
|---|---|---|---|---|---|
| Design Understanding | Mental Model | `mental-model` | `mental_model` | `mental_model_agent/` | ✅ 从 spec 生成 Mental IR |
| Design Verification | Unit Testing (`simulation_agent`) | `simulation-agent` | `unit_testing` | `simulation_agent/` | ✅ 生成纯 SV TB；EDA 缺失时 SKIPPED |
| Design Signoff | Lint AutoFix | `lint-autofix-agent` | — | `lint_autofix/` | ✗ SuperLint 未内置 |
| Design Generation | RTL Upgrade | `experimental rtl-generation` | `rtl_designer` | `rtl_generation/` | ◐ 候选生成 + 备份约束 |
| Design Generation | RTL Early Estimation | `rtl-early-estimation` | — | `rtl_early_estimation_agent/` | ✗ Joules 未内置 |
| Verification | Formal | `formal-agent` | `formal` | `formal_agent/` | ✅ FormalPlan；✗ Jasper 全流程 |
| Verification | Functional Coverage | `functional-coverage-agent` | `functional_coverage` | `functional_coverage_agent/` | ◐ 只读工具；✗ covergroup+Jasper 全流程 |
| Verification | Test Plan | `uvm-agentic-flow` | `uvm` | `test_plan_agent/` | ◐ 角色入口；✗ 全流程 |
| Verification | UVM Coding | `uvm-agentic-flow` | `uvm` | `uvm_agent/`（artifact root） | ◐ 生成/审批；✗ 完整 TB 管线 |
| Verification | DV Debug | `dv-debug-agent` | `debug` | `dv_debug/` | ◐ 确定性 DebugExecutor；✗ Verisium DB |

## 3. 六种使用接口

| 2.0 接口 | 本仓库 | 状态 | 说明 |
|---|---|---|---|
| CLI（headless） | `vagent ...` / 各 agent 子命令 | ✅ | JSON + 退出码，脚本/回归可用 |
| TUI | `vagent tui --mode ... --session-name ...` | ✅ | **独立 TUI 主窗口**（`src/workbench/tui/app.py`）：模式/会话/最新运行 + 7 个领域模式；会话索引在 `chipstack_artifacts/tui/sessions/`。与老 PySide6 GUI 并列，不合并 |
| Web UI | `vagent setup artifact-review-html` | ◐ | **静态单文件 HTML**（离线 MONITOR/ARTIFACTS）；项目规则禁止 Web 服务器 |
| Standalone Artifacts Browser | 同上 | ✅ | 单文件、离线、可编辑后下载副本 |
| Coding Agent 集成（Skills） | `vagent setup seed-skills`、`vagent install-skills claude-code [--project]` | ✅ | 复制仓库 skills；不覆盖用户已有技能 |
| Coding Agent 集成（MCP） | `vagent mcp run` | ✗ | 明确 `NOT_IMPLEMENTED`，不启动假服务 |
| VSCode Extension | — | ✗ | 外部扩展，不在本仓库内 |

## 4. CLI 命令映射

| 2.0 | 本仓库命令 |
|---|---|
| `chipstack mental-model` | `vagent mental-model chat` / `vagent mental-model generate --spec ... --module ... --out ...` |
| `chipstack simulation-agent` | `vagent simulation-agent chat` / `vagent simulation-agent run --rtl ...` |
| `chipstack formal-agent` | `vagent formal-agent chat` / `vagent formal-agent plan` |
| `chipstack functional-coverage-agent` | `vagent functional-coverage-agent chat` |
| `chipstack uvm-agentic-flow` | `vagent uvm-agentic-flow chat` |
| `chipstack --experimental rtl-generation` | `vagent experimental rtl-generation chat` |
| `chipstack lint-autofix-agent` | `vagent lint-autofix-agent run`（明确 NOT_IMPLEMENTED） |
| `chipstack dv-debug-agent` | `vagent dv-debug-agent chat` / `auto-debug`（Verisium 未内置） |
| `chipstack filelist-tools` | `vagent filelist-tools build --rtl-dir ... --out ...` |
| `chipstack tui` | `vagent tui [--mode ...] [--session-name ...]` |
| `chipstack gui --mode ...` | `vagent gui [--mode ...]`（或 `vagent gui run`） |
| `chipstack setup artifact-review-html` | `vagent setup artifact-review-html --run ... --out ...` |
| `chipstack setup seed-skills` | `vagent setup seed-skills` |
| `chipstack install-skills claude-code` | `vagent install-skills claude-code [--project]` |
| `chipstack mcp run` | `vagent mcp run`（NOT_IMPLEMENTED） |

`launch-full-flow` / `auto-debug` / `mcp run` 等没有真实后端的命令**显式退出 2**，
不会产出假报告。

## 5. 配置

查找顺序（`vagent config lookup`）：
`--config` → 安装目录 `cli_config.yaml` → `$CHIPSTACK_HOME/cli_config.yaml` → 工程根。

关键组（`src/workbench/chipstack_compat.py:CONFIG_GROUPS`）：
- `tools`：`sim_bin_path` / `cov_bin_path` / `formal_bin_path` / `lint_tool_bin_path` /
  `verisium_debug_root` / `ppa_bin_path` / `hls_stratus_root`
- `flow`：autocorrect 次数、`max_parallel_workers`、各种 `*_flow_mode`、
  `enable_mental_model`、`enable_user_checkpoints`、`reuse_runid`
- `llm`：`llm_timeout` / `use_litellm_client` / `is_azure_model` / `reasoning`
- `context`、`mental_model`（lite steps / very lite / RAG）

`wire_api` 已弃用，不在模板里出现。

## 6. Artifacts 约定

- 根：`<DESIGN_ROOT>/chipstack_artifacts/`
- 保留名（不能当 design root）：`Archive`、`tui_sessions`、`app_state`、`cli_logs`、
  `symphony_logs`、`tui`、`tmp`、`compile_fix`、`semantic_cache`
- UVM 产物固定在 artifact root 的 `uvm_agent/`；`ChipStackWorkspace` 同时保留
  design 内副本供旧调用方读取（同一批文件）
- TUI 会话索引：`chipstack_artifacts/tui/sessions/<session-name>.json`
- 运行级：`<top>-<run_id>/`；streamlined：`<top>/`；`run_manifest.json` + `cli_logs/`

## 7. 明确未实现 / 外部依赖

| 能力 | 原因 |
|---|---|
| JasperGold formal 全流程（SVA/bind/TCL/执行/report） | 无 Cadence license / 二进制 |
| SuperLint 抽取与安全/不安全修复 | 同上 |
| Verisium Debug + xcelium failure DB RCA | 同上 |
| Joules PPA、Stratus HLS | 同上 |
| Functional coverage covergroup + 不可达删除 | 同上 |
| UVM full pipeline（mental model → coding → filelist → syntax → compile） | 仅角色与生成候选 |
| ChipStack YAML workflow DAG + Web UI 实时 MONITOR | 现有 supervisor 是代码图；Web 服务器被项目规则禁止，提供静态 HTML 导出 |
| MCP server | 未内置；命令明确 NOT_IMPLEMENTED |
| VSCode Extension | 外部扩展 |

## 8. 验证

```bash
vagent modes
vagent agents list
vagent filelist-tools build --rtl-dir rtl --out rtl/top.f
vagent tui --mode formal --session-name fifo_review
vagent setup artifact-review-html --out review.html
vagent config lookup
vagent lint-autofix-agent run --rtl rtl/top.sv   # exit 2 + NOT_IMPLEMENTED
```
