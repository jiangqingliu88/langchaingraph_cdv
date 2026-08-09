# SignOffAI 项目深度分析报告

> 生成日期：2026-08-09 | 分支：develop_claude | 提交数：22

---

## 目录

1. [项目概述](#1-项目概述)
2. [体积分析](#2-体积分析)
3. [技术架构](#3-技术架构)
4. [代码规模与分布](#4-代码规模与分布)
5. [模块详解](#5-模块详解)
6. [Pipeline 工作流](#6-pipeline-工作流)
7. [数据流与证据链](#7-数据流与证据链)
8. [技术栈](#8-技术栈)
9. [问题与风险](#9-问题与风险)
10. [瘦身方案](#10-瘦身方案)
11. [改进建议](#11-改进建议)

---

## 1. 项目概述

**SignOffAI** 是一个 **IC 验证 AI 签核平台**，核心价值主张是「可复现、可审计、可治理」。它通过 11 个专业 AI Agent 协同完成从规格分析到签核的完整芯片验证流程。

### 核心能力

- 📋 **规格解析** — LLM 分析自然语言规格文档
- 🏗️ **设计生成** — 自动生成 RTL 设计代码
- 🔧 **UVM 环境** — 自动生成验证组件（Agent/Driver/Monitor/Scoreboard）
- 🧪 **测试生成** — 基于约束自动生成测试用例
- ✅ **断言生成** — SystemVerilog Assertions (SVA) 自动生成
- 📊 **覆盖率分析** — 自动编译仿真并收集覆盖率
- 🐛 **错误诊断** — AI 辅助调试
- ✍️ **签核审批** — 多角色审批工作流 + 可审计证据链

### 命令行入口

```bash
vagent verify specs/alu_combined.md    # 全自动验证流水线
vagent signoff <run_id> --type tapeout  # 签核
vagent agent list                       # 查看 Agent 状态
```

---

## 2. 体积分析

| 组件 | 大小 | 占比 | 问题等级 |
|------|------|------|----------|
| `venv/` | **376 MB** | 56.7% | 🔴 严重 — 虚拟环境不应在源码仓库中 |
| `.git/` | **265 MB** | 40.0% | 🔴 严重 — 历史中藏有构建产物二进制 |
| `src/` | 21 MB | 3.2% | 🟢 正常 |
| `.claude/` | ~800 KB | 0.1% | 🟢 正常 |
| `logs/` | 532 KB | 0.1% | 🟡 应定期清理 |
| `ic_verification.db` | 428 KB | <0.1% | 🟡 本地数据库 |
| 其他 | ~1 MB | <0.1% | 🟢 正常 |
| **总计** | **~663 MB** | 100% | |

### Git 历史膨胀分析

```
输出构建产物 (.qpg 文件)     ~200 MB   ← output/build/ 下的综合中间文件
虚拟环境二进制                ~44 MB   ← numpy .dll, pydantic .pyd 等
自动生成的构建文件            ~10 MB   ← generated/ build/
其他大文件                    ~11 MB   ← PDF 文档等
─────────────────────────────────
Git 对象总计                 265 MB   (仅 22 次提交，极不合理)
```

**根因**：早期提交中意外将 `output/`、`build/`、`venv/` 等目录加入了版本控制，虽然后续提交可能删除了工作区文件，但 Git 历史永久保留了这些二进制对象。

### 其他浪费

| 项目 | 大小 | 说明 |
|------|------|------|
| `src/tools/dvsim/.git/` | 3.6 MB | 嵌套 Git 仓库 |
| `src/tools/uvm_tools/` PDF 文档 | 1.8 MB | UvmConnectPrimer.pdf + HTML |
| `abandoned/` | 60 KB | 废弃代码 |
| `regression_trend.db` | 44 KB | 本地趋势数据库 |
| `__pycache__/` (散落各处) | ~2 MB | Python 字节码缓存 |

---

## 3. 技术架构

### 3.1 分层架构（6 层）

```
┌─────────────────────────────────────────────┐
│  Interface    │ CLI (click+rich)  │ Web (FastAPI+SSE) │
├─────────────────────────────────────────────┤
│  Service      │ PipelineExecution  │ SignoffService   │
├─────────────────────────────────────────────┤
│  Domain       │ AgentRegistry │ ContextStore │ Manifest  │
├─────────────────────────────────────────────┤
│  Repository   │ SQLAlchemy + SQLite (async)            │
├─────────────────────────────────────────────┤
│  Infra        │ RBAC │ Audit │ EventBus │ Health │ Obs │
├─────────────────────────────────────────────┤
│  Tool         │ UVM │ VCS │ Coverage │ DVTools │ SVA   │
└─────────────────────────────────────────────┘
```

### 3.2 限界上下文（6 个 Bounded Context）

| Context | 职责 | 核心模块 |
|---------|------|----------|
| **Verification** | 验证执行 | Pipeline、Regression、Coverage、Testcase |
| **Signoff** | 签核审批 | Signoff、ApprovalWorkflow、Evidence、Manifest |
| **Document** | 文档管理 | DocDocument、DocVersion、DocRequirement |
| **Design** | 设计追溯 | DesignModule、DesignFeature、ReqFeatureMap |
| **Platform** | 平台治理 | User、Project、RBAC、Audit、Template |
| **Intelligence** | AI 引擎 | DebugCopilot、VPlan、SmartRegression、AutoFix |

### 3.3 设计模式

| 模式 | 应用位置 | 说明 |
|------|----------|------|
| **Singleton** | `AgentRegistry`, `PipelineExecutionService`, `AppContainer` | 全局唯一实例 |
| **Observer** | `AgentObserver` | Agent 生命周期事件监听 |
| **Strategy** | `RegressionRunner` 插件系统 | 回归策略可替换 |
| **Template Method** | `BaseTool` / `BaseAgent` | 工具和 Agent 基类 |
| **IoC Container** | `AppContainer` | 依赖注入，支持 mock |
| **Factory** | `LLMFactory` | LLM 提供商创建 |
| **Repository** | `repository.py` | 数据访问抽象 |

---

## 4. 代码规模与分布

### 4.1 总体统计

| 指标 | 数值 |
|------|------|
| Python 源文件 | ~235 个 |
| 总代码行数 | **~75,000 行** |
| 非缓存文件总数 | 1,159 个 |
| SystemVerilog 文件 | 62 个 (模板 + 示例) |
| Markdown 文档 | 70+ 个 |

### 4.2 源码分布

```
src/
├── agents/          (11 Agent × main.py + test)  ~6,200 行
├── core/            (引擎核心 28 文件)            ~12,000 行
├── cli/             (CLI 3 文件)                  ~2,800 行
├── web/             (API + 路由 + SSE + 模板)     ~4,500 行
├── infra/           (基础设施 25 文件)            ~10,000 行
├── database/        (5 文件)                       ~2,300 行
├── middleware/       (6 文件)                       ~700 行
├── tools/           (9 工具组 + dvsim + lib)      ~30,000 行
│   ├── dvsim/        (第三方仿真调度器)            ~20,000 行
│   ├── uvm_tools/    (UVM 代码生成)               ~4,500 行
│   ├── regression_tools/ (回归框架)               ~2,000 行
│   └── 其他 6 工具                                   ~3,500 行
└── utils/           (脚本工具)                       ~500 行
```

### 4.3 11 个 AI Agent

| Agent | 角色 | 核心能力 |
|-------|------|----------|
| `spec_planner` | 规格规划师 | 解析 Markdown 规格 → 结构化测试计划 |
| `design_architect` | 设计架构师 | 从规格提取设计信号和功能列表 |
| `write_rtl` | RTL 编写 | 生成可综合的 SystemVerilog RTL |
| `model_agent` | 建模工程师 | 生成 C++ 参考模型用于 co-simulation |
| `verify_architect` | 验证架构师 | 生成 UVM 环境骨架 (Agent/Driver/Monitor) |
| `test_engineer` | 测试工程师 | 生成约束随机测试用例 |
| `assertion_engineer` | 断言工程师 | 生成 SVA 断言和覆盖率属性 |
| `regression_manager` | 回归经理 | 编译仿真 + 回归测试 + 日志分析 |
| `coverage_manager` | 覆盖率经理 | 收集合并覆盖率 + 生成报告 |
| `debug_engineer` | 调试工程师 | AI 辅助波形分析 + 错误定位 |
| `quality_assurance` | 质量保证 | 评分卡 + SignOff 门禁 |
| `report_generator` | 报告生成器 | 生成签核报告文档 |

---

## 5. 模块详解

### 5.1 `src/core/` — 引擎核心（最重要的模块）

| 文件 | 行数 | 职责 |
|------|------|------|
| `base.py` | ~450 | Agent 基类、Observer 模式、数据模型 (AgentResult, AgentMessage) |
| `execution.py` | ~400 | **Pipeline 执行引擎** — 18 阶段流水线编排 |
| `llm_factory.py` | ~60 | LLM 工厂 — 统一 DeepSeek/OpenAI 接口 |
| `container.py` | ~80 | IoC 容器 — 依赖注入 |
| `registry.py` | ~80 | Agent 注册中心 — Singleton |
| `context.py` | ~120 | 共享上下文存储 |
| `manifest.py` | ~250 | **证据链核心** — SHA256 哈希 + JSON Manifest |
| `tool_system.py` | ~400 | Tool 标准化 — JSON Schema 校验 + 风险分级 |
| `tool_protocol.py` | ~180 | ITool 协议定义 |
| `tool_sandbox.py` | ~250 | 工具沙箱 — safe/write/danger 权限控制 |
| `tool_orchestrator.py` | ~200 | 工具编排 — LLM 输出纠错 |
| `plugin_manager.py` | ~150 | 插件发现 — Python/YAML/CLI 三种插件形式 |
| `services.py` | ~180 | 业务服务层 — SignoffService, DocService |
| `rules_engine.py` | ~80 | 规则引擎 — 评分阈值 + 自动重试 |
| `step_executor.py` | ~100 | 步骤执行器 |
| `engines.py` | ~70 | 引擎别名 |
| `checkpoint.py` | ~60 | 检查点/断点续传 |
| `design_mapper.py` | ~90 | 设计映射 |
| `evidence.py` | ~120 | 证据收集 |
| `domain_registry.py` | ~50 | 领域状态机 |

### 5.2 `src/infra/` — 基础设施层

| 文件 | 职责 |
|------|------|
| `rbac.py` + `rbac_web.py` | 基于角色的访问控制（5 种角色）|
| `security.py` | 安全加固（输入校验、速率限制） |
| `audit_logger.py` | 审计日志 |
| `event_bus.py` | 事件总线（Agent 间异步通信） |
| `observability.py` | 可观测性（结构化日志 + metrics） |
| `health_monitor.py` | 健康检查端点 |
| `platform_health.py` | 平台运行状态监控 |
| `architecture.py` | **架构约束验证器** — 领域边界 + 分层检查 |
| `collaboration.py` | Agent 间协作 |
| `error_handler.py` | 统一错误处理 |
| `auto_fix_engine.py` | 自动修复引擎 |
| `behavior_analyzer.py` | Agent 行为分析 |
| `failure_cluster.py` | 失败聚类分析 |
| `impact_analyzer.py` | 变更影响分析 |
| `data_governance.py` | 数据治理 |
| `context_snapshot.py` | 上下文快照 |
| `doc_signoff_binding.py` | 文档签核绑定 |
| `resource_scheduler.py` | 资源调度器 |
| `template_system.py` | 模板系统 |
| `workflow_config.py` | 工作流配置 |
| `workflow_triggers.py` | 工作流触发器 |
| `vplan_manager.py` | 验证计划管理 |
| `approval_workflow.py` | 审批工作流 |
| `project_isolation.py` | 项目隔离 |

### 5.3 `src/tools/` — 工具层

#### 内置工具组 (9 组)

| 工具 | 用途 |
|------|------|
| `assertion_tools` | SVA 断言生成与检查 |
| `coverage_tools` | 覆盖率收集、合并、报告 |
| `debug_tools` | AI 辅助调试、日志分析 |
| `doc_tools` | 文档生成、流水线文档 |
| `regression_tools` | 回归测试框架 |
| `reuse_tools` | 验证组件复用 |
| `spec_tools` | 规格解析工具 |
| `testcase_tools` | 测试用例生成器 |
| `uvm_tools` | UVM 环境生成 (10+ 子工具) |

#### 第三方嵌入

| 组件 | 说明 |
|------|------|
| `dvsim/` | OpenTitan 风格的仿真调度器 (独立 Git 仓库嵌入) |
| `uvm_tools/tool_sc_red/` | SystemC 桥接库 (uvmc-2.3.3) |
| `lib/` | 通用工具库 (编译、覆盖率、回归等) |

### 5.4 `src/web/` — Web 界面

```
src/web/
├── api.py              # FastAPI 主应用 (200+ 行)
├── sse.py              # Server-Sent Events 实时推送
├── routes/
│   ├── pipeline.py     # Pipeline API 端点
│   ├── signoff.py      # 签核 API 端点
│   ├── docs.py         # 文档管理 API
│   └── ppa.py          # PPA 分析 API
├── templates/          # Jinja2 HTML 模板
│   ├── dashboard.html  # 仪表盘
│   ├── login.html      # 登录页
│   └── ...
└── static/             # JS/CSS 静态资源
    ├── js/dashboard.js
    └── ...
```

---

## 6. Pipeline 工作流

### 6.1 完整验证流程（18 阶段）

```
前端设计 (de/)
  [1] spec    → 规格解析 (LLM)
  [2] design  → 设计架构生成 (LLM + 模板)
  [3] model   → C++ 参考模型 (LLM)
  [4] rtl     → RTL 代码生成 (LLM)
  [5] ifspec  → 接口控制文档 (文档)
  [6] rtlsign → RTL 签核报告 (文档)

功能验证 (dv/)
  [7] vplan   → 验证计划 (文档)
  [8] tpoint  → 测试点分解 (文档)
  [9] rtm     → 需求追踪矩阵 (文档)
 [10] UVM     → UVM 环境生成 (模板 + 编译仿真 ★)
 [11] test    → 测试用例生成 (LLM + 约束)
 [12] assert  → SVA 断言生成 (LLM)
 [13] regress → 回归测试 (编译 + 仿真 ★)
 [14] cover   → 覆盖率分析 (收集 + 报告 ★)
 [15] debug   → AI 调试 (LLM 分析日志)
 [16] qa      → 质量评分 (规则引擎)
 [17] report  → 签核报告 (模板)
 [18] vclose  → 验证收敛报告 (文档)
```

★ = 涉及真实 EDA 工具调用（VCS/QuestaSim/Verdi）

### 6.2 快速检查模式

```
spec → design → model → vplan → tpoint  (仅前端设计，不跑仿真)
```

### 6.3 回归模式

```
regress → cover → report  (仅仿真 + 覆盖率 + 报告)
```

---

## 7. 数据流与证据链

### 7.1 执行追踪

```
spec.md  →  [PipelineExecutionService]
                │
                ├─→ Phase 1..N  →  AgentOutput (JSON)
                │                      │
                │                      ├─→ 写回 ContextStore
                │                      └─→ 写入 PipelineRun DB
                │
                └─→ Manifest (SHA256 hash tree)
                       │
                       └─→ EvidencePackage (.zip)
                              ├── manifest.json
                              ├── input/  (原始规格)
                              ├── output/ (每阶段产物)
                              └── logs/   (执行日志)
```

### 7.2 可审计性设计

- 每个阶段输入/输出均计算 SHA256 哈希
- Manifest 记录完整依赖链和工具版本
- 支持从 JSONL trace 重建 manifest
- 签核证据包可导出为 ZIP 并验证完整性

---

## 8. 技术栈

| 层 | 技术选型 |
|----|----------|
| **语言** | Python 3.11+ |
| **AI/LLM** | LangChain + DeepSeek API (兼容 OpenAI SDK) |
| **Web 框架** | FastAPI + Uvicorn + Jinja2 |
| **CLI 框架** | Click + Rich (彩色终端输出) |
| **数据库** | SQLAlchemy (async) + SQLite/AIOSQLite |
| **配置** | Pydantic Settings + YAML + Hjson |
| **日志** | structlog (结构化日志) |
| **异步** | asyncio + SSE (Server-Sent Events) |
| **测试** | pytest + pytest-asyncio |
| **代码质量** | pre-commit + ruff |
| **CI/CD** | GitHub Actions |
| **EDA 工具** | VCS / QuestaSim / Verdi / Verilator |

---

## 9. 问题与风险

### 9.1 严重问题

| 问题 | 影响 | 优先级 |
|------|------|--------|
| **Git 历史膨胀** — 265MB 仅 22 次提交 | clone 极慢、CI 浪费带宽 | 🔴 P0 |
| **嵌套 Git 仓库** — `src/tools/dvsim/.git/` | 版本混乱、可能冲突 | 🔴 P0 |
| **venv/ 未清理** — 376MB 虚拟机环境 | 占用磁盘 | 🟡 P1 |
| **构建产物在历史中** — .qpg 文件 | 无法彻底删除 | 🔴 P0 |

### 9.2 架构风险

| 问题 | 说明 |
|------|------|
| **Singleton 滥用** — 4+ 处全局单例 | 测试隔离困难，并发风险 |
| **过度工程化** — 25 个 infra 文件 vs 11 个 Agent | 基础设施远重于业务核心 |
| **第三方代码嵌入** — dvsim 直接 copy 进仓库 | 上游更新困难，license 风险 |
| **死代码** — `abandoned/` 目录 + `_tools_old.py` | 维护负担 |

### 9.3 代码质量

| 问题 | 说明 |
|------|------|
| **导入混乱** — 混用 `from __future__ import annotations` 和旧式类型注解 | 不一致 |
| **双重容器** — 既有 `AppContainer` (IoC) 又有 `AgentRegistry` (Singleton) | 架构冗余 |
| **假 LLM** — `fake_llm.py` 表明测试缺乏 mock 框架 | 测试设计需要改进 |
| **硬编码路径** — README 中写死 `D:\cdv_a` | 不可移植 |

### 9.4 安全风险

| 问题 | 说明 |
|------|------|
| `.env` 包含 API Key | 敏感信息，已在 .gitignore 但风险仍在 |
| `bootstrap_admin_password` | 空字符串默认值不安全 |
| SQLite 并发限制 | 不适合多用户生产环境 |

---

## 10. 瘦身方案

### 10.1 立即可执行（无风险）

| 操作 | 命令 | 节省 |
|------|------|------|
| 删除虚拟环境 | `rm -rf venv/` | **376 MB** |
| 清理 `__pycache__` | `find . -name __pycache__ -exec rm -rf {} +` | ~2 MB |
| 删除废弃代码 | `rm -rf abandoned/` | 60 KB |
| 清理日志 | `rm -rf logs/*` | ~500 KB |

### 10.2 需要谨慎执行（重写历史）

```bash
# 方案 A：使用 git filter-repo（推荐）
pip install git-filter-repo

# 从历史中删除特大文件 (>10MB)
git filter-repo --strip-blobs-bigger-than 10M --force

# 或精确删除路径
git filter-repo \
  --path output/ \
  --path build/ \
  --path generated/ \
  --path venv/ \
  --invert-paths \
  --force
```

**预期效果**：`.git/` 从 265MB → ~15MB，节省 ~250MB。

### 10.3 处理嵌套 Git 仓库

```bash
# 选择一：直接去 git 化（推荐 — dvsim 作为源码快照使用）
rm -rf src/tools/dvsim/.git/

# 选择二：转为正式 submodule
git submodule add <dvsim-repo-url> src/tools/dvsim/
```

### 10.4 补充 .gitignore

```gitignore
# 构建产物
output/
build/
generated/
*.qpg
*.vdb

# 嵌套仓库
src/tools/dvsim/.git/

# 数据库
*.db

# 大型第三方文档（可选）
src/tools/uvm_tools/tool_sc_red/uvmc-*/docs/
```

### 10.5 预期最终体积

| 阶段 | 体积 |
|------|------|
| 当前 | 663 MB |
| 删除 venv | 287 MB |
| 清理 Git 历史 | **~35 MB** |
| 清理嵌套 .git | **~31 MB** |
| 其他优化 | **~28 MB** |

**最终目标**：从 663MB → 约 30MB，缩减 **95%**。

---

## 11. 改进建议

### 11.1 短期（1-2 周）

- [ ] 执行瘦身方案 10.1-10.4
- [ ] 将 `src/tools/dvsim/` 转为 Git submodule 或 pip 依赖
- [ ] 删除 `abandoned/` 和 `_tools_old.py`
- [ ] 统一类型注解风格
- [ ] 移除 `fake_llm.py`，改用 pytest mock
- [ ] 移除 README 中的硬编码路径

### 11.2 中期（1 个月）

- [ ] 合并 `AppContainer` 和 `AgentRegistry`，减少双重容器
- [ ] 精简 `src/infra/` — 25 个文件中有多处只定义未使用
- [ ] 添加 `pre-commit` hook 禁止提交 >1MB 文件
- [ ] 拆分 `src/tools/uvm_tools/` 为独立 pip 包
- [ ] CI 中添加体积检查步骤

### 11.3 长期（1 季度）

- [ ] 迁移到 PostgreSQL（替代 SQLite）
- [ ] Agent 热插拔 — 支持动态加载/卸载 Agent
- [ ] 引入 Redis 缓存层
- [ ] 容器化部署（Docker + K8s）
- [ ] 开源准备：LICENSE 文件、CONTRIBUTING.md、CODE_OF_CONDUCT.md

---

## 附录

### A. 关键文件索引

| 文件 | 用途 |
|------|------|
| `src/core/execution.py` | Pipeline 执行引擎入口 |
| `src/core/base.py` | Agent 基类和数据模型 |
| `src/core/manifest.py` | 证据链与可审计性 |
| `src/core/tool_system.py` | 工具标准化与风险控制 |
| `src/core/container.py` | 依赖注入容器 |
| `src/cli/commands.py` | CLI 23 个命令组入口 |
| `src/web/api.py` | Web API 入口 |
| `src/infra/architecture.py` | 架构约束与六层模型定义 |
| `src/database/models.py` | 数据库模型定义 |
| `config/settings.py` | 分环境配置 |
| `valiflow.md` | 项目记忆文件 |

### B. 目录结构总览

```
SignOffAI/
├── src/
│   ├── agents/       # 11 个 AI Agent
│   ├── core/         # 引擎核心（28 文件）
│   ├── cli/          # 命令行接口
│   ├── web/          # Web API + UI
│   ├── infra/        # 基础设施（25 文件）
│   ├── database/     # 数据持久层
│   ├── middleware/    # 中间件（缓存/日志/重试）
│   ├── tools/        # 工具层（9 组 + dvsim）
│   └── utils/        # 工具脚本
├── config/           # 配置文件
├── tests/            # 集成测试
├── docs/             # 文档
├── specs/            # 规格文件 (.md)
├── projects/         # 项目配置 (.yaml/.hjson)
├── scripts/          # 运维脚本
├── logs/             # 日志
└── venv/             # Python 虚拟环境（应删除）
```
