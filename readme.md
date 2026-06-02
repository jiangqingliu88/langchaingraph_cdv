```markdown
# IC Verification Multi-Agent System

基于 LangChain + DeepSeek 的 IC 验证多 Agent 协作系统，9 个专业 Agent 协同完成规格分析、UVM 代码生成、SVA 断言、覆盖率分析等验证全流程。

## 快速开始

```powershell
# 1. 激活环境
cd C:\Users\liujiangqing\Desktop\cdv_advanced
.\venv\Scripts\activate

# 2. 设置 API Key
$env:LLM_API_KEY="sk-your-deepseek-key"

# 3. 初始化
ic-verify init

# 4. 查看状态
ic-verify status

# 5. 模拟运行（不消耗API）
ic-verify verify spec_uart.txt --bypass

# 6. 真实运行（消耗API）
ic-verify verify spec_uart.txt
```

## 命令速查

| 命令 | 说明 |
|------|------|
| `ic-verify init` | 初始化系统 |
| `ic-verify status` | 查看 9 个 Agent 状态 |
| `ic-verify analyze <file>` | 分析设计规格 |
| `ic-verify analyze <file> --bypass` | 模拟分析（不消耗API） |
| `ic-verify verify <file>` | 运行完整验证流程 |
| `ic-verify verify <file> --bypass` | 模拟验证 |
| `ic-verify verify <file> -w quick_check` | 快速检查（3阶段） |
| `ic-verify workflows` | 列出可用工作流 |
| `ic-verify repl --bypass` | 交互式对话模式 |
| `ic-verify debug-log` | 查看 Agent 调试日志 |
| `ic-verify debug-log -s <session>` | 查看特定会话日志 |
| `ic-verify history` | 查看历史记录 |

## 9 个 Agent

| Agent | 角色 | 模型 |
|-------|------|------|
| `spec_and_test_planner` | 规格分析与测试规划 | deepseek-chat |
| `verification_architect` | UVM 架构设计与代码生成 | deepseek-coder |
| `sequence_engineer` | 测试序列生成 | deepseek-coder |
| `assertion_engineer` | SVA 断言生成 | deepseek-coder |
| `coverage_manager` | 覆盖率分析 | deepseek-chat |
| `regression_manager` | 回归测试管理 | deepseek-chat |
| `debug_engineer` | 调试与问题定位 | deepseek-chat |
| `quality_assurance` | 质量审查 | deepseek-chat |
| `report_generator` | 报告生成 | deepseek-chat |

## 工作流

### Full Verification（7 阶段）

```
spec → arch → seq + assert (并行) → regress → cover → qa
```

### Quick Check（3 阶段）

```
spec → arch → qa
```

## 调试日志

每次运行自动记录到 `logs/agent_debug/debug_<session>.jsonl`：

```jsonl
{"timestamp":"...","event":"pipeline_start","workflow":"full_verification","phases":["spec","arch",...]}
{"timestamp":"...","agent":{"role":"spec_and_test_planner","name":"规格与测试规划师"},"input":"分析规格...","output":"{...}","tools_used":[],"elapsed":"0.0s","success":true}
{"timestamp":"...","event":"pipeline_end","passed":7,"degraded":0,"total_time":"0.5s"}
```

查看日志：
```powershell
ic-verify debug-log                    # 列出所有会话
ic-verify debug-log -s 20260602_210500 # 查看特定会话
```

## 项目结构

```
cdv_advanced/
├── config/
│   └── settings.py              # 全局配置
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
│   │   └── llm_factory.py       # LLM 工厂
│   ├── cli/
│   │   └── commands.py          # CLI 命令
│   ├── tools/                   # 工具集
│   │   ├── spec_tools.py
│   │   ├── uvm_tools.py
│   │   ├── assertion_tools.py
│   │   ├── debug_tools.py
│   │   └── coverage_tools.py
│   ├── database/                # 数据持久化
│   │   ├── models.py
│   │   ├── connection.py
│   │   └── repository.py
│   └── middleware/               # 中间件
│       ├── logging.py
│       ├── retry.py
│       ├── cache.py
│       └── debug_logger.py       # Agent 调试日志
├── tests/                       # 单元测试
├── logs/agent_debug/            # 调试日志输出
├── spec_uart.txt                # 示例规格文件
├── pyproject.toml
└── requirements.txt
```

## 设计模式

| 模式 | 应用 |
|------|------|
| Singleton | Settings, AgentRegistry, DebugLogger |
| Factory | LLMFactory |
| Template Method | BaseAgent 生命周期 |
| Observer | AgentSubject |
| Decorator | @tool 工具函数 |
| Repository | 数据访问层 |

## 关键特性

| 特性 | 说明 |
|------|------|
| bypass 模式 | `--bypass` 使用模拟数据，不消耗 API，快速测试 |
| 调试日志 | 自动记录每个 Agent 的输入/输出/Prompt |
| 并行执行 | seq 和 assert 阶段并行运行 |
| 失败重试 | 自动重试 3 次，失败后降级继续 |
| Rich 输出 | 表格、进度条、语法高亮 |

## 测试

```powershell
pytest tests/ -v --tb=short
```

## 环境要求

| 依赖 | 版本 |
|------|------|
| Python | 3.10+ |
| langchain | 0.1.20 |
| langchain-core | 0.1.52 |
| langchain-openai | 0.0.8 |
| DeepSeek API Key | [获取](https://platform.deepseek.com/) |
```