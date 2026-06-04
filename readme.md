# IC Verification Multi-Agent System

基于 LangChain + DeepSeek 的 IC 验证多 Agent 协作系统，10 个专业 Agent 协同完成规格分析、UVM 代码生成、SVA 断言、测试用例生成、覆盖率分析等验证全流程。

## 快速开始

```powershell
# 1. 激活环境
cd D:\cdv_a
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

# 7. 带编译检查的运行
ic-verify verify spec_uart.txt --bypass --compile
```

## 命令速查

| 命令 | 说明 |
|------|------|
| `ic-verify init` | 初始化系统 |
| `ic-verify status` | 查看 10 个 Agent 状态 |
| `ic-verify analyze <file>` | 分析设计规格 |
| `ic-verify analyze <file> --bypass` | 模拟分析（不消耗API） |
| `ic-verify verify <file>` | 运行完整验证流程 |
| `ic-verify verify <file> --bypass` | 模拟验证 |
| `ic-verify verify <file> -w quick_check` | 快速检查（4阶段） |
| `ic-verify verify <file> --compile` | 验证 + QuestaSim 编译检查 |
| `ic-verify verify <file> -o <dir>` | 指定输出目录 |
| `ic-verify workflows` | 列出可用工作流 |
| `ic-verify repl --bypass` | 交互式调试控制台 |
| `ic-verify debug-log` | 查看 Agent 调试日志 |
| `ic-verify debug-log -s <session>` | 查看特定会话日志 |
| `ic-verify history` | 查看历史记录 |

## 10 个 Agent

| Agent | 角色 | 模型 |
|-------|------|------|
| `spec_and_test_planner` | 规格分析与测试规划 | deepseek-chat |
| `verification_architect` | UVM 架构设计与代码生成 | deepseek-coder |
| `sequence_engineer` | 测试序列生成 | deepseek-coder |
| `testcase_engineer` | 测试用例自动生成 | deepseek-coder |
| `assertion_engineer` | SVA 断言生成 | deepseek-coder |
| `coverage_manager` | 覆盖率分析 | deepseek-chat |
| `regression_manager` | 回归测试管理 | deepseek-chat |
| `debug_engineer` | 调试与问题定位 | deepseek-chat |
| `quality_assurance` | 质量审查 | deepseek-chat |
| `report_generator` | 报告生成 | deepseek-chat |

## 工作流

### Full Verification（10 阶段）

```
spec → arch → seq → tc → assert → regress → cover → debug → qa → report
```

### Quick Check（4 阶段）

```
spec → arch → seq → tc
```

## REPL 调试控制台

交互式单 Agent 调试，支持逐一验证 Tool 代码：

```
ic-verify> agents                    # 列出所有 Agent
ic-verify> tools arch                # 查看 Agent 的 Tool 列表
ic-verify> arch <input>              # 执行 Agent
ic-verify> exec arch generate_uvm    # 直接调用 Tool 函数
ic-verify> bypass on|off             # 切换 bypass 模式
ic-verify> ctx                       # 显示上下文
```

## 调试日志

每次运行自动记录到 `logs/agent_debug/debug_<session>.jsonl`：

```jsonl
{"timestamp":"...","event":"pipeline_start","workflow":"full_verification","phases":["spec","arch",...]}
{"timestamp":"...","agent":{"role":"spec_and_test_planner","name":"规格与测试规划师"},"input":"分析规格...","output":"{...}","tools_used":[],"elapsed":"0.0s","success":true}
{"timestamp":"...","event":"pipeline_end","passed":10,"degraded":0,"total_time":"0.5s"}
```

查看日志：
```powershell
ic-verify debug-log                    # 列出所有会话
ic-verify debug-log -s 20260602_210500 # 查看特定会话
```

## 项目结构

```
cdv_a/
├── config/
│   ├── settings.py                  # 全局配置
│   └── agent_config.yaml            # Agent & Pipeline 定义
├── src/
│   ├── agents/                      # 10 个 Agent
│   │   ├── spec_planner.py
│   │   ├── architect.py
│   │   ├── sequence_engineer.py
│   │   ├── testcase_engineer.py     # 测试用例生成
│   │   ├── assertion_engineer.py
│   │   ├── coverage_manager.py
│   │   ├── regression_manager.py
│   │   ├── debug_engineer.py
│   │   ├── quality_assurance.py
│   │   └── report_generator.py
│   ├── core/                        # 核心框架
│   │   ├── base.py                  # Agent 基类 + 责任链
│   │   ├── registry.py              # Agent 注册中心
│   │   ├── orchestrator.py          # 编排器（中介者 + 管道模式）
│   │   ├── pipeline.py              # 管道策略
│   │   ├── llm_factory.py           # LLM 工厂
│   │   └── deepseek_config.py       # DeepSeek 配置
│   ├── cli/
│   │   └── commands.py              # CLI 命令 + REPL
│   ├── tools/                       # 工具集
│   │   ├── spec_tools.py            # 规格分析工具
│   │   ├── uvm_tools.py             # UVM 代码生成工具
│   │   ├── assertion_tools.py       # SVA 断言工具
│   │   ├── debug_tools.py           # 调试工具
│   │   ├── coverage_tools.py        # 覆盖率工具
│   │   ├── reuse_tools.py           # 复用顾问工具
│   │   ├── uvm/                     # UVM 模板 + 代码生成器
│   │   │   ├── tool_uvm/            #   Jinja2 模板 + gen_uvm.py
│   │   │   └── tool_sc_red/         #   SC 参考模型生成
│   │   ├── testcase/                # 测试用例生成器
│   │   │   ├── generator.py
│   │   │   └── templates/           #   Jinja2 序列/测试模板
│   │   └── compilesim/              # 仿真编译集成
│   │       ├── regression_wrapper.py
│   │       └── agent_loopback_test.py  # Agent 回环测试
│   ├── database/                    # 数据持久化
│   │   ├── models.py
│   │   ├── connection.py
│   │   └── repository.py
│   ├── infra/                       # 基础设施
│   │   ├── vplan_manager.py         # 验证计划管理
│   │   ├── rbac.py                  # RBAC 权限管理
│   │   └── project_isolation.py     # 多项目隔离
│   ├── middleware/                   # 中间件
│   │   ├── logging.py
│   │   ├── retry.py
│   │   ├── cache.py
│   │   └── debug_logger.py          # Agent 调试日志
│   ├── prompts/                     # Prompt 管理
│   └── web/                         # Web 管理平台
│       └── templates/
│           └── dashboard.html       # Mock 仪表盘
├── generated/                       # 生成的 UVM 代码
│   └── uart/
│       ├── agents/                  #   UART_in / UART_out / AXI_in
│       ├── bench/                   #   testbench top
│       └── env/                     #   验证环境
├── output/                          # 流水线输出
│   └── testcases/                   #   生成的测试用例
├── build/                           # 编译产物（QuestaSim work lib）
├── tests/                           # 单元测试
├── logs/agent_debug/                # 调试日志输出
├── scripts/
│   └── init_db.py                   # 数据库初始化
├── spec_uart.txt                    # 示例规格文件
├── verify_architect_loopback.py     # Agent 回环验证脚本
├── switch_llm.sh                    # LLM 切换脚本
├── pyproject.toml
└── requirements.txt
```

## 设计模式

| 模式 | 应用 |
|------|------|
| Singleton | Settings, AgentRegistry, DebugLogger |
| Factory | LLMFactory |
| Template Method | BaseAgent 生命周期 |
| Mediator | VerificationOrchestrator |
| Pipeline / Chain of Responsibility | 工作流阶段串联 + 请求处理链 |
| Observer | AgentSubject |
| Decorator | @tool 工具函数 |
| Repository | 数据访问层 |
| Strategy | SequentialStrategy / ParallelStrategy / ConditionalStrategy |

## 关键特性

| 特性 | 说明 |
|------|------|
| bypass 模式 | `--bypass` 使用模拟数据，不消耗 API，快速测试 |
| 调试日志 | 自动记录每个 Agent 的输入/输出/Prompt |
| 并行执行 | seq + assert 阶段可并行运行 |
| 失败重试 | 自动重试 3 次，失败后降级继续 |
| Rich 输出 | 表格、进度条、语法高亮 |
| QuestaSim 集成 | `--compile` 自动编译检查生成的 UVM 代码 |
| REPL 调试 | 单 Agent 交互式调试，支持直接调用 Tool |
| Agent 回环测试 | 验证 Agent 生成代码的可编译性 |
| Web 仪表盘 | Mock 管理界面（Pipeline / 测试用例 / Agent 状态） |
| 验证计划管理 | vPlan 导入/导出 + 需求追踪矩阵 |
| RBAC 权限 | 角色-based 权限控制（管理员/经理/工程师） |
| 多项目隔离 | 项目间数据 + 权限隔离 |

## 测试

```powershell
pytest tests/ -v --tb=short
```

## 环境要求

| 依赖 | 版本 |
|------|------|
| Python | 3.10 - 3.12 |
| langchain | 0.1.20 |
| langchain-core | 0.1.52 |
| langchain-openai | 0.0.8 |
| Jinja2 | >=3.1.0 |
| Rich | >=13.0 |
| Click | >=8.0 |
| PyYAML | >=6.0 |
| SQLAlchemy | >=2.0 |
| DeepSeek API Key | [获取](https://platform.deepseek.com/) |
| QuestaSim（可选） | 用于 `--compile` 编译检查 |
