```markdown
# IC Verification Multi-Agent System

基于 LangChain + DeepSeek 的 IC 验证多 Agent 协作系统，支持规格分析、UVM 代码生成、SVA 断言生成、覆盖率分析等验证全流程。

## 架构概览

```
User Input (CLI/REPL)
        │
        ▼
┌───────────────────────────────────────┐
│         VerificationOrchestrator       │
│   (Pipeline 编排、重试、降级、并行)      │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│            9 个专业 Agent               │
│  SpecPlanner | Architect | SeqEngineer │
│  AssertEngineer | CoverageMgr         │
│  RegressionMgr | DebugEngineer        │
│  QualityAssurance | ReportGenerator   │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│          LLM Factory                   │
│    DeepSeek-Chat / DeepSeek-Coder      │
└───────────────────────────────────────┘
```

## 快速开始

### 1. 环境要求

| 依赖 | 版本 |
|------|------|
| Python | 3.10+ |
| DeepSeek API Key | [获取](https://platform.deepseek.com/) |

### 2. 安装

```powershell
# 克隆项目
cd ic_verification_agent

# 创建虚拟环境
python -m venv venv
.\venv\Scripts\activate

# 安装依赖
pip install langchain==0.1.20 langchain-core==0.1.52 langchain-openai==0.0.8 langchain-community==0.0.38
pip install jinja2 pydantic pydantic-settings sqlalchemy aiosqlite rich click pyyaml tenacity structlog python-dotenv
pip install -e .
```

### 3. 配置 API Key

```powershell
# 方式1：环境变量
$env:LLM_API_KEY="sk-your-deepseek-api-key"

# 方式2：.env 文件
"LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-key
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1" | Out-File .env -Encoding ASCII
```

### 4. 验证安装

```powershell
ic-verify init
ic-verify status
```

## 命令速查

| 命令 | 说明 | 示例 |
|------|------|------|
| `ic-verify init` | 初始化系统 | |
| `ic-verify status` | 查看 9 个 Agent 状态 | |
| `ic-verify analyze <file>` | 分析设计规格 | `ic-verify analyze spec.txt` |
| `ic-verify analyze <file> --bypass` | 模拟模式（不消耗API） | `ic-verify analyze spec.txt --bypass` |
| `ic-verify verify <file>` | 运行完整验证流程 | `ic-verify verify spec.txt` |
| `ic-verify verify <file> -w quick_check` | 快速检查（3阶段） | |
| `ic-verify verify <file> -o result.json` | 保存结果 | |
| `ic-verify workflows` | 列出工作流 | |
| `ic-verify history` | 查看历史记录 | |
| `ic-verify repl` | 交互式对话模式 | |

## 9 个 Agent

| Agent | 角色 | 模型 |
|-------|------|------|
| SpecAndTestPlanner | 规格分析与测试规划 | deepseek-chat |
| VerificationArchitect | UVM 架构设计与代码生成 | deepseek-coder |
| SequenceEngineer | 测试序列生成 | deepseek-coder |
| AssertionEngineer | SVA 断言生成 | deepseek-coder |
| CoverageManager | 覆盖率分析 | deepseek-chat |
| RegressionManager | 回归测试管理 | deepseek-chat |
| DebugEngineer | 调试与问题定位 | deepseek-chat |
| QualityAssurance | 质量审查 | deepseek-chat |
| ReportGenerator | 报告生成 | deepseek-chat |

## 工作流

### Full Verification（7 阶段）

```
spec ──→ arch ──┬── seq ──┬── regress ──→ cover ──→ qa
                 └── assert ┘    (并行)
```

### Quick Check（3 阶段）

```
spec ──→ arch ──→ qa
```

## 项目结构

```
ic_verification_agent/
├── config/
│   ├── settings.py              # 全局配置
│   └── agent_config.yaml        # Agent YAML 配置（可选）
├── src/
│   ├── agents/                  # 9 个 Agent
│   │   ├── spec_planner.py
│   │   ├── architect.py
│   │   ├── sequence_engineer.py
│   │   ├── assertion_engineer.py
│   │   ├── coverage_manager.py
│   │   ├── regression_manager.py
│   │   ├── debug_engineer.py
│   │   ├── quality_assurance.py
│   │   └── report_generator.py
│   ├── core/                    # 核心框架
│   │   ├── base.py              # Agent 基类
│   │   ├── registry.py          # Agent 注册中心
│   │   ├── orchestrator.py      # 编排器
│   │   └── llm_factory.py       # LLM 工厂
│   ├── cli/                     # CLI 界面
│   │   └── commands.py
│   ├── tools/                   # 工具集
│   │   ├── spec_tools.py
│   │   ├── uvm_tools.py
│   │   ├── assertion_tools.py
│   │   ├── debug_tools.py
│   │   ├── coverage_tools.py
│   │   └── templates/           # Jinja2 UVM 模板
│   ├── database/                # 数据持久化
│   │   ├── models.py
│   │   ├── connection.py
│   │   └── repository.py
│   └── middleware/               # 中间件
│       ├── logging.py
│       ├── retry.py
│       └── cache.py
├── tests/                       # 单元测试
├── spec_uart.txt                # 示例规格文件
├── pyproject.toml
└── requirements.txt
```

## REPL 交互模式

```powershell
ic-verify repl --bypass
```

```
ic-verify> analyze UART Controller v2.1 supports full-duplex...
ic-verify> plan          # 生成测试计划
ic-verify> arch          # 生成 UVM 架构
ic-verify> seq           # 生成测试序列
ic-verify> assert        # 生成 SVA 断言
ic-verify> cover         # 覆盖率分析
ic-verify> qa            # 质量审查
ic-verify> history       # 查看历史
ic-verify> quit
```

## 配置

### YAML 配置（可选）

创建 `config/agent_config.yaml`：

```yaml
agents:
  spec_and_test_planner:
    model: deepseek-chat
    temperature: 0.0
    retry:
      max_retries: 3

pipelines:
  full_verification:
    phases:
      - {name: spec, agent: spec_and_test_planner}
      - {name: arch, agent: verification_architect}
      - {name: seq, agent: sequence_engineer, parallel_group: 1}
      - {name: assert, agent: assertion_engineer, parallel_group: 1}
```

## 设计模式

| 模式 | 应用 |
|------|------|
| Singleton | Settings, AgentRegistry |
| Factory | LLMFactory |
| Template Method | BaseAgent 生命周期 |
| Strategy | ExecutionStrategy |
| Observer | AgentSubject |
| Decorator | @tool, 中间件 |
| Repository | 数据访问层 |

## 测试

```powershell
pytest tests/ -v
pytest tests/ --cov=src --cov-report=term
```

## 常见问题

| 问题 | 解决 |
|------|------|
| API Key 无效 | 从 DeepSeek 平台重新获取 |
| Settings 读不到 .env | 添加 `extra="allow"` 到 model_config |
| @tool 报 self 错误 | 使用独立函数，不用类方法 |
| Agent 初始化失败 | 工具列表移到 `__init__` 中初始化 |

## 最近更新

- ✅ 9 Agent 全部可运行
- ✅ bypass 模式（不消耗 API 测试）
- ✅ REPL 交互模式
- ✅ 进度条 + 时间统计
- ✅ 失败重试 + 降级策略
- ✅ 并行执行（seq + assert）
- ✅ 数据库持久化 + history 命令
- ✅ YAML 配置支持
- ✅ Rich 表格 + 语法高亮
- ✅ 单元测试覆盖
```