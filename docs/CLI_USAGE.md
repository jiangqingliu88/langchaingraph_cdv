# SignOffAI CLI 使用手册

> **运行方式**: `python -m src.cli.commands <command>` (无需 pip install)

---

## 目录

1. [快速开始](#1-快速开始)
2. [命令总览](#2-命令总览)
3. [核心命令详解](#3-核心命令详解)
   - [verify — 一键验证流水线](#verify)
   - [agent — Agent 管理](#agent)
   - [spec — 规格文档工具](#spec)
   - [env — UVM 环境工具](#env)
   - [regression — 回归管理](#regression)
   - [coverage — 覆盖率分析](#coverage)
   - [debug — 调试分析](#debug)
   - [signoff — 签核审批](#signoff)
   - [dump — 证据导出](#dump)
   - [pipeline — 流水线管理](#pipeline)
   - [其他命令](#其他命令)
4. [工作流 (Workflow)](#4-工作流-workflow)
5. [Agent 流水线](#5-agent-流水线)
6. [环境配置](#6-环境配置)

---

## 1. 快速开始

```powershell
# 前置条件
cd D:\SignOffAI
.\venv\Scripts\activate

# 最简用法：拿一个 spec 文件，全自动跑
python -m src.cli.commands verify specs\apb_uart\apb_uart_spec.md

# 只看结果摘要
python -m src.cli.commands verify specs\apb_uart\apb_uart_spec.md --summary

# 只跑单个阶段
python -m src.cli.commands verify specs\apb_uart\apb_uart_spec.md --step spec

# 快速检查（前 5 阶段，跳过仿真）
python -m src.cli.commands verify specs\apb_uart\apb_uart_spec.md --workflow quick_check
```

---

## 2. 命令总览

| 命令 | 用途 | 子命令 |
|------|------|--------|
| `verify` | 一键验证流水线（核心入口） | — |
| `agent` | Agent 管理与单步执行 | `list` `show` `run` |
| `spec` | 规格文档分析 | `analyze` `validate` `convert` `trace` |
| `env` | UVM 环境生成 | `generate` `validate` `compile` `template` |
| `regression` | 回归测试管理 | `run` `report` `trend` `compare` |
| `coverage` | 覆盖率分析 | `report` `gaps` `trend` `merge` |
| `debug` | 调试与日志分析 | `log` `analyze` `repl` |
| `signoff` | 签核审批 | `generate` `export` `verify` `checklist` `diff` |
| `dump` | 证据链导出 | — |
| `pipeline` | 流水线编排 | `list` `run` `graph` |
| `diff` | 版本对比 | `coverage` `spec` `regression` |
| `ci` | CI/CD 集成 | `verify` `check` `precheck` |
| `docs` | 文档自动生成 | `generate` `preview` |
| `config` | 配置管理 | `show` `set` `init` `validate` |
| `project` | 项目管理 | `init` `status` `info` `list` `clean` |
| `plugin` | 插件管理 | `list` `discover` `install` `uninstall` `search` |
| `hub` | 工具注册中心 | `status` `list` `health` `bootstrap` |
| `tool` | 工具直接调用 | `list` `show` `call` `history` |
| `status` | 查看 Agent 状态 | — |
| `history` | 运行历史 | — |
| `workflows` | 列出工作流 | — |
| `watch` | 实时监控流水线 | — |
| `init` | 初始化项目目录 | — |
| `web` | 启动 Web 仪表盘 | — |

---

## 3. 核心命令详解

### verify

**一键验证流水线**，从 Spec 到签核全自动。

```powershell
# 完整流水线
python -m src.cli.commands verify <spec_file>

# 指定工作流
python -m src.cli.commands verify <spec_file> --workflow quick_check

# 单阶段
python -m src.cli.commands verify <spec_file> --step spec
python -m src.cli.commands verify <spec_file> --step UVM

# 阶段范围
python -m src.cli.commands verify <spec_file> --from design --to cover

# 指定多个阶段（逗号分隔）
python -m src.cli.commands verify <spec_file> --steps spec,design,rtl

# 输出模式
python -m src.cli.commands verify <spec_file> --json        # CI 模式
python -m src.cli.commands verify <spec_file> --summary     # 只出摘要
python -m src.cli.commands verify <spec_file> --quiet       # 静默

# 断点续跑
python -m src.cli.commands verify <spec_file> --resume <run_id>

# 只重跑失败阶段
python -m src.cli.commands verify <spec_file> --retry-failed

# 自定义输出目录
python -m src.cli.commands verify <spec_file> -o output/my_project

# LLM refine 模式（迭代改进）
python -m src.cli.commands verify <spec_file> --refine
```

**可用阶段名**: `spec` `design` `model` `rtl` `ifspec` `rtlsign` `vplan` `tpoint` `rtm` `UVM` `test` `assert` `regress` `cover` `debug` `qa` `report` `vclose`

**可用工作流**:

| 工作流 | 阶段数 | 说明 |
|--------|:------:|------|
| `full_verification` | 17 | 完整流程（默认） |
| `quick_check` | 5 | 前端设计快速检查 |
| `regression_only` | 3 | 只跑回归+覆盖率+报告 |
| `ppa_analysis` | 2 | PPA 分析 |

---

### agent

**Agent 管理与单步执行**。

```powershell
# 列出所有 Agent
python -m src.cli.commands agent list

# 查看某个 Agent 详情
python -m src.cli.commands agent show <role>
python -m src.cli.commands agent show spec_and_test_planner

# 单独运行一个 Agent
python -m src.cli.commands agent run <role> --input "spec text here"
python -m src.cli.commands agent run test_engineer --input-file test.json
```

Agent 角色名对照:

| 缩写 | 完整 role | 职责 |
|:----:|-----------|------|
| spec | `spec_and_test_planner` | 规格分析 |
| design | `design_architect` | 设计架构 |
| model | `model_agent` | 参考模型 |
| rtl | `write_rtl` | RTL 代码生成 |
| UVM | `verification_architect` | UVM 环境 |
| test | `test_engineer` | 测试用例 |
| assert | `assertion_engineer` | SVA 断言 |
| regress | `regression_manager` | 回归管理 |
| cover | `coverage_manager` | 覆盖率 |
| debug | `debug_engineer` | 调试分析 |
| qa | `quality_assurance` | 质量审查 |
| report | `report_generator` | 报告生成 |

---

### spec

**规格文档分析工具**。

```powershell
# 分析 spec 文件
python -m src.cli.commands spec analyze <spec_file>

# 校验 spec 格式
python -m src.cli.commands spec validate <spec_file>

# 格式转换
python -m src.cli.commands spec convert <spec_file> --format json

# 需求追踪
python -m src.cli.commands spec trace <spec_file> --output trace.md
```

---

### env

**UVM 环境生成与管理**。

```powershell
# 从 spec 生成 UVM 环境
python -m src.cli.commands env generate <spec_file> -o output/env

# 校验 UVM 环境
python -m src.cli.commands env validate output/env

# 编译 UVM 环境
python -m src.cli.commands env compile output/env --sim questa

# 生成 UVM 模板
python -m src.cli.commands env template --type agent --name my_agent
```

---

### regression

**回归测试管理**。

```powershell
# 执行回归
python -m src.cli.commands regression run <regression_yaml>

# 生成回归报告
python -m src.cli.commands regression report <run_id>

# 回归趋势
python -m src.cli.commands regression trend --days 30

# 对比两次回归
python -m src.cli.commands regression compare <run_id_1> <run_id_2>
```

---

### coverage

**覆盖率分析**。

```powershell
# 生成覆盖率报告
python -m src.cli.commands coverage report <run_id>

# 查看覆盖率缺口
python -m src.cli.commands coverage gaps <run_id>

# 覆盖率趋势
python -m src.cli.commands coverage trend --days 30

# 合并覆盖率数据
python -m src.cli.commands coverage merge <dir1> <dir2> -o merged
```

---

### debug

**调试与日志分析**。

```powershell
# 查看运行日志
python -m src.cli.commands debug log <run_id>

# 分析失败原因
python -m src.cli.commands debug analyze <run_id>

# 交互式调试
python -m src.cli.commands debug repl
```

---

### signoff

**签核审批流程**。

```powershell
# 生成签核证据包
python -m src.cli.commands signoff generate <run_id>

# 导出签核文档
python -m src.cli.commands signoff export <run_id> --format pdf

# 验证签核完整性
python -m src.cli.commands signoff verify <run_id>

# 签核检查清单
python -m src.cli.commands signoff checklist <run_id>

# 对比两个签核包
python -m src.cli.commands signoff diff <run_id_a> <run_id_b>
```

---

### dump

**导出证据链**。

```powershell
# 导出指定 session 的证据链
python -m src.cli.commands dump <session_id>

# 列出所有可导出的 session
python -m src.cli.commands dump --list

# JSON 格式输出
python -m src.cli.commands dump <session_id> --json

# 指定输出路径
python -m src.cli.commands dump <session_id> -o output/evidence

# Agent 角色 → 阶段 → 输入 → 输出 → hash → 判定
# 构成一条从 Spec 到 Signoff 的完整可审计链
```

---

### pipeline

**流水线编排管理**。

```powershell
# 列出所有可用流水线
python -m src.cli.commands pipeline list

# 执行指定流水线
python -m src.cli.commands pipeline run <name> --spec <spec_file>

# 生成流水线关系图
python -m src.cli.commands pipeline graph --output pipeline.png
```

---

### 其他命令

```powershell
# 项目管理
python -m src.cli.commands project init <name>         # 初始化项目
python -m src.cli.commands project status              # 项目状态
python -m src.cli.commands project list                # 列出项目
python -m src.cli.commands project clean               # 清理输出

# 配置管理
python -m src.cli.commands config show                 # 查看配置
python -m src.cli.commands config set KEY VALUE        # 设置配置
python -m src.cli.commands config init                 # 生成 .env 模板
python -m src.cli.commands config validate             # 校验配置

# CI/CD
python -m src.cli.commands ci verify <spec_file>       # CI 模式验证
python -m src.cli.commands ci check                    # 检查 CI 环境
python -m src.cli.commands ci precheck                 # 提交前检查

# 版本对比
python -m src.cli.commands diff coverage <r1> <r2>     # 覆盖率对比
python -m src.cli.commands diff spec <s1> <s2>         # Spec 对比
python -m src.cli.commands diff regression <r1> <r2>   # 回归对比

# 文档生成
python -m src.cli.commands docs generate <run_id>      # 生成完整文档
python -m src.cli.commands docs preview <run_id>       # 预览文档

# 工具管理
python -m src.cli.commands tool list                   # 列出工具
python -m src.cli.commands tool show <tool>            # 工具详情
python -m src.cli.commands tool call <tool> --args '{}' # 直接调用

# 插件管理
python -m src.cli.commands plugin list                 # 列出插件
python -m src.cli.commands plugin install <name>       # 安装插件
python -m src.cli.commands plugin search <keyword>     # 搜索插件

# 监控与状态
python -m src.cli.commands status                      # Agent 状态
python -m src.cli.commands watch <run_id>              # 实时监控
python -m src.cli.commands history                     # 运行历史
python -m src.cli.commands workflows                   # 列出工作流

# 项目初始化
python -m src.cli.commands init                        # 初始化目录结构

# Web 仪表盘（企业版）
python -m src.cli.commands web --port 8000             # 启动 Web
```

---

## 4. 工作流 (Workflow)

```powershell
# 列出所有工作流
python -m src.cli.commands workflows

# 指定工作流执行
python -m src.cli.commands verify <spec_file> --workflow <name>
```

| 工作流 | 包含阶段 | 适用场景 |
|--------|----------|----------|
| `full_verification` | 17 阶段全流程 | 正式签核 |
| `quick_check` | spec→design→model→rtl→ifspec | 快速验证前端设计 |
| `regression_only` | regress→cover→report | 只跑仿真回归 |
| `ppa_analysis` | vplan→report | PPA 分析 |

---

## 5. Agent 流水线

### 数据流

```
spec.md
  │
  ▼
┌──────────────────┐
│ 1.spec_planner   │  ◀ LLM: deepseek-chat, Tool: SpecAnalysisTools
│ → ctx.spec       │
└──────┬───────────┘
       │
       ├──────────────────────┐
       ▼                      ▼
┌──────────────────┐  ┌──────────────────┐
│ 2.design_arch    │  │ 3.model_agent    │  ← 可并行
│ → ctx.design_arch│  │ → ctx.model      │
└──────┬───────────┘  └──────┬───────────┘
       │                      │
       ├──────────────────────┘
       ▼
┌──────────────────┐
│ 4.write_rtl      │  ◀ 写 .sv 文件到磁盘
└──────┬───────────┘
       │
       ├──────────────────────┐
       ▼                      ▼
┌──────────────────┐  ┌──────────────────┐
│ 5.verify_arch    │  │ 6.test_engineer  │  ← 可并行
│ → ctx.env (UVM)  │  │ → ctx.tests      │
└──────┬───────────┘  └──────┬───────────┘
       │                      │
       │    ┌─────────────────┘
       │    ▼
       │ ┌──────────────────┐
       │ │ 7.assert_engineer│  ◀ 生成 SVA 断言
       │ └──────┬───────────┘
       │        │
       ├────────┘
       ▼
┌──────────────────┐
│ 8.regress_mgr    │  ◀ 需要 EDA 仿真器 (VCS/Questa)
│ → ctx.regression │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ 9.coverage_mgr   │  ◀ 收集覆盖率数据
│ → ctx.coverage   │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ 10.debug_engineer│  ◀ 反馈闭环: 失败→路由修复→重试
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ 11.quality_assur │  ◀ 质量评审
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ 12.report_gen    │  ◀ 生成签核报告 + Manifest + 证据链
└──────────────────┘
```

### Agent 配置

| Agent | LLM 模型 | 工具 | consumes | produces |
|-------|----------|------|----------|----------|
| spec_planner | deepseek-chat | SpecAnalysisTools(4) | — | spec |
| design_architect | deepseek-coder | — | spec | design_arch |
| model_agent | deepseek-coder | analyze/generate(3) | spec, design_arch | model |
| write_rtl | deepseek-coder | parse_tree/generate/write(4) | spec, design_arch | (文件) |
| verify_architect | deepseek-coder | — | spec | env |
| test_engineer | deepseek-coder | TestcaseTools | spec, design_arch | tests |
| assert_engineer | deepseek-coder | AssertionTools | spec, design_arch | — |
| regression_manager | deepseek-chat | RegressionTools→dvsim | spec, env, tests | regression |
| coverage_manager | deepseek-chat | CoverageTools | spec, regression | coverage |
| debug_engineer | deepseek-chat | DebugTools | regression, tests, env | debug |
| quality_assurance | deepseek-chat | — | regression, coverage | — |
| report_generator | deepseek-chat | DocTools | (all) | — |

---

## 6. 环境配置

在 `.env` 中配置：

```ini
# LLM 提供商 (必填)
LLM_PROVIDER=deepseek              # deepseek | openai | anthropic | custom
LLM_MODEL=deepseek-chat
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.deepseek.com/v1

# 产品等级 (可选，默认 personal)
PLATFORM_TIER=personal             # personal | community | enterprise

# Agent 配置 (可选)
AGENT_MAX_AGENTS=5
AGENT_MAX_ITERATIONS=8
AGENT_TIMEOUT=300

# 验证配置 (可选)
VERIFY_COVERAGE_TARGET=95.0
VERIFY_MAX_RETRIES=3
```

等级差异 (`PLATFORM_TIER`):

| 能力 | personal | community | enterprise |
|------|:--------:|:---------:|:----------:|
| Agent 并发 | 5 | 9 | 20 |
| 反馈闭环 | ❌ | ❌ | ✅ |
| 证据链 | ❌ | ✅ | ✅ |
| SSE 推送 | ❌ | ✅ | ✅ |
| 五大引擎 | ❌ | ❌ | ✅ |
| Web 仪表盘 | ❌ | ✅ | ✅ |
| 多用户/RBAC | ❌ | ❌ | ✅ |
