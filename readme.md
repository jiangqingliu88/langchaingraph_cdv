# IC验证多Agent智能体系统

## 项目概述

基于LangChain和DeepSeek的多Agent协作IC验证系统，支持规格分析、UVM代码生成、断言生成、覆盖率分析等验证全流程。

## 项目结构

```
cdv_advanced/
├── config/                     # 配置管理
│   ├── __init__.py
│   └── settings.py             # 全局配置（Pydantic Settings）
├── src/
│   ├── __init__.py
│   ├── agents/                 # 9个专业Agent
│   │   ├── __init__.py
│   │   ├── spec_planner.py     # 规格与测试规划师
│   │   ├── architect.py        # 验证架构师
│   │   ├── sequence_engineer.py # 序列工程师
│   │   ├── assertion_engineer.py # 断言工程师
│   │   ├── coverage_manager.py  # 覆盖率管理器
│   │   ├── regression_manager.py # 回归管理器
│   │   ├── debug_engineer.py    # 调试工程师
│   │   ├── quality_assurance.py # 质量保证
│   │   └── report_generator.py  # 报告生成器
│   ├── core/                   # 核心框架
│   │   ├── __init__.py
│   │   ├── base.py             # Agent基类
│   │   ├── registry.py         # Agent注册中心
│   │   ├── orchestrator.py     # 编排器
│   │   ├── pipeline.py         # 管道模式
│   │   └── llm_factory.py      # LLM工厂
│   ├── cli/                    # CLI界面
│   │   ├── __init__.py
│   │   └── commands.py         # Click命令
│   ├── tools/                  # 工具集
│   │   ├── __init__.py
│   │   ├── spec_tools.py       # 规格分析工具
│   │   ├── uvm_tools.py        # UVM代码生成工具
│   │   ├── assertion_tools.py  # 断言生成工具
│   │   ├── debug_tools.py      # 调试工具
│   │   ├── coverage_tools.py   # 覆盖率工具
│   │   └── templates/          # Jinja2模板
│   ├── database/               # 数据库
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   ├── models.py           # SQLAlchemy模型
│   │   └── repository.py       # 数据仓库
│   ├── middleware/             # 中间件
│   │   ├── __init__.py
│   │   ├── logging.py          # 日志
│   │   ├── retry.py            # 重试
│   │   └── cache.py            # 缓存
│   └── prompts/                # Prompt管理
│       ├── __init__.py
│       └── manager.py
├── tests/                      # 测试
├── spec_uart.txt               # 示例规格文件
├── .env                        # 环境变量
├── pyproject.toml              # 项目配置
├── requirements.txt            # 依赖
└── run.ps1                     # 启动脚本
```

## 环境要求

| 依赖 | 版本 |
|------|------|
| Python | 3.10+（推荐3.11.9） |
| LangChain | 0.1.20 |
| LangChain-Core | 0.1.52 |
| LangChain-OpenAI | 0.0.8 |
| DeepSeek API | - |

## 安装部署

### 1. 克隆项目

```bash
cd C:\Users\liujiangqing\Desktop\cdv_advanced
```

### 2. 创建虚拟环境

```powershell
python -m venv venv
.\venv\Scripts\activate
```

### 3. 安装依赖

```powershell
pip install langchain==0.1.20 langchain-core==0.1.52 langchain-openai==0.0.8 langchain-community==0.0.38
pip install jinja2 pydantic pydantic-settings sqlalchemy aiosqlite rich click pyyaml tenacity structlog python-dotenv
pip install -e .
```

### 4. 配置API Key

```powershell
# 方式1：环境变量
$env:LLM_API_KEY="sk-your-deepseek-api-key"

# 方式2：.env文件
@"
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-your-deepseek-api-key
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
"@ | Out-File -FilePath .env -Encoding ASCII
```

### 5. 验证安装

```powershell
python -c "from src.core.base import BaseAgent; print('OK')"
```

## 使用指南

### CLI命令

```powershell
# 初始化系统
ic-verify init

# 分析规格文档
ic-verify analyze spec_uart.txt

# 运行完整验证流程
ic-verify verify spec_uart.txt -w full_verification

# 快速检查
ic-verify verify spec_uart.txt -w quick_check

# 查看系统状态
ic-verify status

# 列出可用工作流
ic-verify workflows

# 保存结果到文件
ic-verify verify spec_uart.txt -o results.json
```

### Python脚本

```python
import asyncio
from src.agents.spec_planner import SpecAndTestPlanner

async def main():
    agent = SpecAndTestPlanner()
    await agent.initialize()
    
    result = await agent.execute_task({
        "input": "分析UART设计规格..."
    })
    print(result.data["output"])

asyncio.run(main())
```

## 9个Agent说明

| Agent | 角色 | 任务类型 | 使用模型 |
|-------|------|---------|---------|
| SpecAndTestPlanner | 规格与测试规划 | spec_analysis | deepseek-chat |
| VerificationArchitect | 验证架构师 | code_generation | deepseek-coder |
| SequenceEngineer | 序列工程师 | sequence_generation | deepseek-coder |
| AssertionEngineer | 断言工程师 | assertion_generation | deepseek-coder |
| CoverageManager | 覆盖率管理 | coverage_analysis | deepseek-chat |
| RegressionManager | 回归管理 | regression_management | deepseek-chat |
| DebugEngineer | 调试工程师 | debug_analysis | deepseek-chat |
| QualityAssurance | 质量保证 | quality_review | deepseek-chat |
| ReportGenerator | 报告生成 | report_generation | deepseek-chat |

## 架构设计模式

| 模式 | 应用位置 |
|------|---------|
| Singleton | Settings, AgentRegistry |
| Factory | LLMFactory, Agent创建 |
| Template Method | BaseAgent生命周期 |
| Strategy | ExecutionStrategy |
| Observer | AgentSubject |
| Chain of Responsibility | Handler |
| Repository | 数据访问层 |
| Decorator | @tool, 中间件 |

## 工作流

### 完整验证流程

```
Phase 1: spec_analysis     → SpecAndTestPlanner
Phase 2: architecture       → VerificationArchitect
Phase 3: parallel_dev       → SequenceEngineer + AssertionEngineer
Phase 4: regression         → RegressionManager
Phase 5: parallel_analysis  → CoverageManager + DebugEngineer
Phase 6: quality_review     → QualityAssurance
Phase 7: decision           → Orchestrator
```

### 快速检查流程

```
Phase 1: spec_analysis  → SpecAndTestPlanner
Phase 2: architecture   → VerificationArchitect
Phase 3: review         → QualityAssurance
```

## 工具集说明

| 工具类 | 包含工具 |
|--------|---------|
| SpecAnalysisTools | analyze_specification, extract_features, generate_test_plan, assess_risk |
| UVMTools | generate_uvm_driver, generate_uvm_monitor, generate_uvm_scoreboard等 |
| AssertionTools | generate_sva_assertions, generate_cdc_assertions等 |
| DebugTools | analyze_simulation_log, analyze_waveform, trace_error_source |
| CoverageTools | collect_coverage, analyze_coverage_gaps, suggest_coverage_tests |

## LangChain @tool 使用规范

```python
# ✅ 正确 - 独立函数
@tool("my_tool")
def my_tool(param: str = "") -> str:
    """工具描述（必须有docstring）"""
    return "result"

# ✅ 正确 - 工具集组织
class MyTools:
    def get_tools(self):
        return [my_tool]

# ❌ 错误 - 类方法（self会被当作参数）
class MyTools:
    @tool("my_tool")
    def my_tool(self, param: str) -> str:
        ...
```

## 常见问题

### 1. Settings读取不到.env

**原因**：Pydantic Settings默认`extra=forbidden`，.env中未定义的字段会被拒绝。

**解决**：在`model_config`中添加`extra="allow"`。

### 2. AgentExecutor报chat_history缺失

**原因**：Prompt模板中有`MessagesPlaceholder(variable_name="chat_history")`但AgentExecutor没传。

**解决**：从Prompt模板中删除`chat_history`的MessagesPlaceholder。

### 3. @tool报self field required

**原因**：@tool不支持类方法，self被当作必填参数。

**解决**：改为独立函数，用工具类组织。

### 4. API Key认证失败

**原因**：Key无效或格式错误。

**解决**：
- 确认Key是`sk-`开头
- 从DeepSeek平台重新获取
- 用`$env:LLM_API_KEY`设置环境变量

## 快速启动脚本

```powershell
# run.ps1
$env:LLM_API_KEY="sk-your-key"
.\venv\Scripts\activate
ic-verify analyze spec_uart.txt
```

---

**系统状态：✅ 已成功运行**