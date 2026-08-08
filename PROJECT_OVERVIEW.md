# SignOffAI — IC 验证签核平台：项目概览

## 1. 项目简介

本项目是一个面向数字 IC 验证的多 Agent 自动化平台。它以 Markdown 规格说明为输入，串联规格分析、RTL 与验证环境生成、参考模型与测试生成、仿真回归、覆盖率分析、问题定位和报告输出等工作，帮助将验证流程标准化、可追踪化。

系统既可通过 CLI 执行，也提供基于 FastAPI 的 Web API 与仪表盘。LLM 可用于规格理解和生成结果润色；当未配置 API Key 时，部分基于模板的能力仍可运行。

## 2. 核心能力

- 读取 Markdown 格式的模块规格，提取功能、接口、寄存器和测试点。
- 生成设计架构信息及可综合 RTL。
- 基于 Jinja2 模板生成 UVM Agent、环境、测试台和约束相关代码。
- 生成 C++ 参考模型、DPI 桥接与 UVM predictor。
- 由测试策略生成 SystemVerilog 测试与约束场景。
- 生成 SVA 断言，并执行回归、覆盖率收集和失败日志分析。
- 发现设计、环境、模型或规格不一致时，路由到对应 Agent 进行有限次数的反馈修复。
- 保存运行、回归、签核、知识库和审计等数据到 SQLite（默认配置）。

## 3. 验证流水线

默认的 `full_verification` 工作流共 11 个阶段：

```text
规格分析
  → 设计架构 / RTL
  → 参考模型
  → UVM 验证环境
  → 测试生成
  → SVA 断言
  → 回归仿真
  → 覆盖率分析
  → 调试诊断
  → 质量审查
  → 报告生成
```

对应的 Agent 与主要产物如下：

| 阶段 | Agent | 主要产物 |
| --- | --- | --- |
| spec | `spec_and_test_planner` | 结构化规格与验证计划 |
| design | `design_architect` | 设计架构、RTL |
| model | `model_agent` | C++ 参考模型、predictor/DPI 相关内容 |
| UVM | `verification_architect` | UVM 环境与 Agent 代码 |
| test | `test_engineer` | 测试场景、约束与 SV 测试代码 |
| assert | `assertion_engineer` | SVA 断言与形式属性 |
| regress | `regression_manager` | 编译、仿真与回归结果 |
| cover | `coverage_manager` | line/branch/toggle 等覆盖率数据 |
| debug | `debug_engineer` | 失败分类、根因与修复建议 |
| qa | `quality_assurance` | 质量评审结果 |
| report | `report_generator` | 汇总报告 |

`quick_check` 仅运行前五个阶段：规格、设计、参考模型、UVM 环境和测试生成。

当调试阶段给出可修复的问题时，执行服务最多启动 2 轮反馈：重新运行目标 Agent，然后依次重跑测试、回归、覆盖率和调试阶段。

## 4. 项目结构

```text
config/                 全局设置、Agent 配置、回归配置
specs/                  ALU、UART 等 Markdown 规格示例
src/
  agents/               各专业验证 Agent 的实现
  core/                 注册表、编排、执行服务、LLM 工厂
  tools/                UVM、测试、断言、覆盖率、模型等生成工具
  web/                  FastAPI 接口和仪表盘模板
  database/             SQLite 数据模型与仓储层
  infra/                RBAC、项目隔离、验证计划管理
  middleware/           日志、缓存、重试等基础能力
  cli/commands.py       Click 命令行入口
output/                 生成的 RTL、UVM、测试和报告示例
logs/                   Agent 调试日志
tests/                  核心单元测试
```

## 5. 快速开始

### 环境要求

- Python 3.10–3.12
- 可选：DeepSeek/OpenAI 兼容 LLM 服务
- 可选：QuestaSim，用于真实编译、仿真与覆盖率收集

### 安装

```powershell
cd D:\cdv_a
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 配置 LLM（可选）

在项目根目录创建或更新 `.env`：

```ini
LLM_PROVIDER=deepseek
LLM_API_KEY=your-api-key
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
```

请勿将包含真实 API Key 的 `.env` 提交到版本库。

### 执行验证

```powershell
# 初始化输出与日志目录
python -m src.cli.commands init

# 完整流水线
python -m src.cli.commands verify specs\alu_combined.md

# 快速检查，并指定输出目录
python -m src.cli.commands verify specs\alu_combined.md --workflow quick_check --output output\alu_quick

# 安装为命令行工具后也可使用
ic-verify verify specs\alu_combined.md
```

CLI 的 `verify` 命令还支持 `--refine`（LLM 润色/迭代修复模式）和 `--compile`（UVM 阶段后运行 QuestaSim 编译）选项。

### 启动 Web 服务

```powershell
uvicorn src.web.api:app --host 127.0.0.1 --port 8000
```

或：

```powershell
python -m src.cli.commands web --host 127.0.0.1 --port 8000
```

访问 `http://127.0.0.1:8000`。当前代码中提供测试账号 `admin / admin123`；部署前应替换默认凭据并使用安全的 JWT 密钥。

## 6. 输入、输出与可观测性

- 输入规格：通常位于 `specs/`，例如 `specs/alu_combined.md`。
- 生成产物：默认写入 `output/`；可通过 CLI 的 `--output` 指定位置。
- 调试日志：`logs/agent_debug/` 下会记录流水线事件以及 Agent 输入输出摘要。
- 持久化数据：默认 SQLite 文件为项目根目录的 `ic_verification.db`，可用 `DB_` 前缀环境变量覆盖连接配置。
- 验证计划：`src/infra/vplan_manager.py` 提供需求、测试用例、追溯矩阵与覆盖状态管理能力。

## 7. Web API 范围

Web 层围绕以下能力提供接口：

- 认证、RBAC、项目与审计管理。
- 流水线启动、运行状态查询及单 Agent 执行。
- 验证计划、需求—测试追溯、导入导出。
- 规格 Markdown 文档的浏览与保存。
- 覆盖率摘要、回归历史/趋势、签核与知识库。
- 调试会话和 Agent 日志查询。

接口实现位于 `src/web/api.py`；启动服务后可通过 FastAPI 的 OpenAPI 页面查看当前可用接口。

## 8. 开发与测试

```powershell
pytest tests/ src/agents/ src/tools/ -v --tb=short
```

主要依赖定义在 `requirements.txt` 和 `pyproject.toml`。项目将 `tests` 与 `src` 同时纳入 pytest 搜索范围，新增 Agent 或工具时建议同步添加 `test_*.py`。

## 9. 使用注意事项

- 真实仿真与覆盖率结果依赖本地 QuestaSim 环境及其工具路径；缺少该环境时，相关阶段可能降级或跳过。
- LLM 输出具有不确定性。流水线使用 Agent 自检评分、重试和调试反馈降低风险，但生成的 RTL、断言与验证结论仍应经过工程师评审。
- 规格文档是整个流水线的源头。应明确接口位宽、时钟复位、时序行为、寄存器地址、异常处理和可验证的需求编号。
- 当前工作区包含历史生成文件和本地配置；运行前请使用独立的输出目录，避免覆盖需要保留的结果。
