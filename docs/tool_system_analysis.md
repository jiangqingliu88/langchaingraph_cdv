# SignOffAI Tool System 架构分析

> 分析日期：2026-08-09  
> 分析范围：`src/core/tool_system.py`、`src/core/agent_tools.py`、`src/tools/*`、`src/agents/*`

---

## 1. 总体架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Tool System 三层架构                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Layer 1: Tool + ToolRegistry                                       │
│  ──────────────────────────                                         │
│  JSON Schema 标准化 → 参数验证 → LLM 输出纠错                          │
│                                                                     │
│  Layer 2: Sandbox                                                   │
│  ────────────────                                                   │
│  三级风险控制: safe(自动通过) / write(终端确认) / danger(直接拦截)      │
│                                                                     │
│  Layer 3: ProjectMemory                                             │
│  ────────────────────                                               │
│  跨 run 持久记忆 (valiflow.md)，YAML frontmatter + Markdown section   │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                        代码组织层次                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  src/core/tool_system.py     ← 核心框架（Tool/ToolRegistry/Adapter）  │
│  src/core/agent_tools.py     ← 全局 Tool Schema 注册中心              │
│  src/tools/                  ← 各类工具实现（LangChain @tool 封装）    │
│  src/agents/                 ← Agent 层引用 Tool 执行任务             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心框架：`src/core/tool_system.py`

### 2.1 类关系图

```
┌──────────────┐     注册到    ┌───────────────┐    包装 LangChain    ┌──────────────────────┐
│    Tool      │ ───────────→ │  ToolRegistry  │ ──────────────────→ │ ToolRegistryAdapter   │
│              │              │                │                      │                      │
│ name         │              │ _tools: dict   │                      │ wrap(langchain_tools) │
│ description  │              │ invoke()       │                      │ → validated_tools     │
│ input_schema │              │ validate()     │                      │                      │
│ risk_level   │              │ record_hist()  │                      │ stats: calls/        │
│ handler      │              │ list_llm_specs │                      │   schema_rejects/    │
└──────┬───────┘              └───────┬────────┘                      │   sandbox_blocks     │
       │                              │                               └──────────┬───────────┘
       │                              │                                          │
       ▼                              ▼                                          │
┌──────────────┐              ┌───────────────┐                      ┌───────────┴───────────┐
│  validate_   │              │   Sandbox     │                      │  wrap_agent_tools()   │
│  args()      │              │               │                      │                        │
│              │              │ check(tool,   │                      │ 为 Agent 工具添加      │
│  to_llm_     │              │  args) → bool │                      │ Schema 验证 + Sandbox  │
│  description │              │               │                      │ + 重建 AgentExecutor   │
│  ()          │              │ is_path_safe  │                      └────────────────────────┘
└──────────────┘              └───────────────┘
```

### 2.2 风险等级体系

| 风险等级 | 审批模式 | 典型工具 | 说明 |
|----------|----------|----------|------|
| `safe` | 自动通过 | `read_report`, `parse_test_points` | 只读/无副作用 |
| `write` | 终端确认 | `gen_test_sv`, `backup_to_library` | 写磁盘/改配置 |
| `danger` | 直接拦截 | `run_vcs`, `run_simulation` | 删除/提权/长时间运行 |

### 2.3 Tool 定义

```python
@dataclass
class Tool:
    name: str                              # 工具唯一标识
    description: str                       # LLM 可见描述，决定何时调用
    input_schema: Dict[str, Any]           # JSON Schema (参数类型/必填/enum)
    risk_level: RiskLevel = "safe"         # "safe" | "write" | "danger"
    handler: Optional[Callable] = None     # 实际执行函数 fn(args) -> dict
```

**Schema 验证规则（`validate_args`）：**
- 必填字段检查（`required`）
- 类型检查（`string` / `integer` / `number`）
- 枚举检查（`enum`）

### 2.4 LLM 适配层

`to_llm_description()` 将 Tool 转为 OpenAI function-calling 格式：

```python
{
    "type": "function",
    "function": {
        "name": "run_vcs",
        "description": "Compile and run VCS simulation for a testbench",
        "parameters": { "type": "object", "properties": {...}, "required": [...] }
    }
}
```

---

## 3. 全局注册中心：`src/core/agent_tools.py`

所有 Agent 使用的 Tool 统一在此注册 JSON Schema，实现**工具定义与 Agent 逻辑分离**。

```python
def register_all_tools() -> ToolRegistry:
    registry = ToolRegistry()
    # 按 Agent 分组注册
    # verify_architect → uvm_tools (7 tools)
    # model_agent       → analyze_design_arch, generate_ref_model, generate_test_vectors (3)
    # test_engineer     → parse_test_points, map_policies... 等 (6)
    # regression_manager → compile_env, run_simulation, generate_regression_report (3)
    # report_generator  → generate_reports, query_trend_history (2)
    return registry
```

### 注册的 Tool 清单

| Agent | Tool 数量 | 工具列表 |
|-------|-----------|----------|
| verify_architect | 7 | 委托自 uvm_tools |
| model_agent | 3 | analyze_design_arch, generate_ref_model, generate_test_vectors |
| test_engineer | 6 | parse_test_points, map_policies_to_tests, build_scenario_yaml, build_priority_rules, generate_test_cases, check_test_coverage |
| regression_manager | 3 | compile_env, run_simulation, generate_regression_report |
| report_generator | 2 | generate_reports, query_trend_history |

---

## 4. Tool 分类目录结构

```
src/tools/
├── __init__.py
├── spec_tools/              # 规格分析工具集
│   ├── __init__.py
│   ├── main.py              # analyze_spec / extract_features / generate_test_plan / assess_risk
│   └── test_spec_tools.py
├── assertion_tools/         # SVA 断言生成工具集
│   ├── __init__.py
│   ├── main.py              # generate_sva / immediate / concurrent / formal / CDC / cover / package
│   └── test_assertion_tools.py
├── coverage_tools/          # 覆盖率分析工具集
│   ├── __init__.py
│   ├── main.py              # collect_coverage / analyze_gaps / generate_report / suggest_tests
│   └── test_coverage_tools.py
├── debug_tools/             # 调试分析工具集
│   ├── __init__.py
│   ├── main.py              # analyze_log / analyze_waveform / trace_error / generate_fix
│   └── test_debug_tools.py
├── doc_tools/               # 文档生态工具集（SQL 后端）
│   ├── __init__.py
│   ├── main.py              # search_docs / get_doc / get_req_trace / get_doc_tree / list_requirements
│   └── test_doc_tools.py
├── testcase_tools/          # 测试用例生成器
│   ├── __init__.py
│   ├── main.py              # CLI 入口
│   ├── generator.py         # TestCaseGenerator（YAML→SV 代码），Jinja2 模板驱动
│   ├── tools.py
│   └── test_testcase.py
├── uvm_tools/               # UVM 环境代码生成
│   ├── __init__.py
│   ├── main.py              # CLI 入口
│   ├── agent_tools.py       # verify_architect 的 7 个工具注册
│   ├── tool_uvm/            # UVM 代码生成引擎
│   │   ├── __init__.py
│   │   ├── gen_uvm.py       # JinjaRenderer + TEMPLATES_DIR，从 YAML 生成接口/环境/测试代码
│   │   └── templates/       # Jinja2 模板库（interface/environment/test templates）
│   ├── tool_sc_red/         # SC_RED 相关
│   │   ├── generate.py
│   │   └── main.py
│   └── test_uvm.py
├── cmodel_tools/            # C-Model + DPI 编译
│   ├── gen_cmodel.py        # 生成 UVM predictor + DPI wrapper
│   └── dpi_compile.py       # 调用 QuestaSim GCC 编译 C++ → .so
├── reuse_tools/             # VIP 复用顾问
│   ├── __init__.py
│   ├── main.py              # scan_env / extract_if / auto_param / normalize / backup / search / match / integrate / reuse_report / lib_stats
│   └── test_reuse_tools.py
├── regression_tools/        # 回归框架
│   └── regression_framwork/
│       ├── regression.py
│       └── src/regression_framework/
│           ├── core/        # config, exceptions, logging
│           ├── execution/   # strategy
│           ├── generators/  # makefile, shell
│           ├── models/      # scheduler, task
│           ├── plugins/     # base, slack_notifier, dingtalk_notifier
│           └── reporters/   # ...
└── testcase_tools/
    └── tools.py
```

### 4.1 工具统一接口模式

每个 Tool 目录遵循统一模式：

```python
# 模式 1：LangChain @tool 装饰器 (spec_tools / assertion_tools / coverage_tools / debug_tools / reuse_tools)
@tool("tool_name")
def tool_name(param: str = "") -> str:
    """LLM 可见的 description"""
    # 业务逻辑
    return json.dumps(result, indent=2)

class XxxTools:
    def get_tools(self):
        return [tool1, tool2, ...]

# 模式 2：后端集成 (doc_tools)
# 通过 repository 模块访问 SQL 数据库
search_docs = tool("search_docs")(_search_docs_impl)

# 模式 3：独立引擎 (testcase_tools / uvm_tools / cmodel_tools)
# CLI 入口 + Python API + Jinja2 模板生成
class TestCaseGenerator:
    def __init__(self, yaml_path): ...
    def generate_all(self, output_dir): ...
```

---

## 5. 工具调用流程

```
┌─────────┐    LLM 决策调用    ┌──────────────┐    Schema 验证    ┌─────────────┐
│  Agent  │ ────────────────→ │ ToolRegistry  │ ────────────────→ │    Tool     │
│         │                   │  .invoke()    │                   │ .validate() │
│ (LLM)   │                   │               │                   │             │
└─────────┘                   └──────┬────────┘                   └──────┬──────┘
                                     │                                  │
                                     ▼                                  ▼
                              ┌──────────────┐                   ┌──────────────┐
                              │   Sandbox    │                   │   handler()  │
                              │  .check()    │                   │  执行实际函数 │
                              │              │                   │              │
                              │ auto/confirm │                   │ fn(args)→dict│
                              │ /block       │                   └──────┬───────┘
                              └──────┬───────┘                          │
                                     │                                  │
                                     ▼                                  ▼
                              ┌──────────────┐                   ┌──────────────┐
                              │  返回结果     │ ←──────────────── │  result dict │
                              │ {success,     │                   └──────────────┘
                              │  result,      │
                              │  error}       │
                              └──────────────┘
```

---

## 6. 在六层架构中的位置

依据 `src/infra/architecture.py` 定义的六层架构，Tool 系统的定位：

```
Interface   ← API/CLI 暴露 tool 调用入口
Service     ← Agent 层编排 tool 调用链
Domain      ← Tool 定义、Schema、RiskLevel（核心实体）
Repository  ← tool 执行历史的持久化存储
Infra       ← Sandbox 权限控制、ProjectMemory 持久记忆
Tool        ← ★ 工具实现层（本分析的核心）
```

Bounded Context 中的归属（`architecture.py` 的 `DomainMap`）：

| 模块 | 文件 | Context | Layer |
|------|------|---------|-------|
| testcase | `src/tools/testcase_tools` | Verification | **Tool** |
| regression | `src/tools/regression_tools` | Verification | **Tool** |

---

## 7. 设计特点与改进建议

### 7.1 设计亮点

| 特点 | 说明 |
|------|------|
| **Schema 驱动** | 每个 Tool 有完整 JSON Schema，LLM 按 schema 生成参数，框架自动 validate |
| **三级风险控制** | safe/write/danger 三级权限模型，防止危险操作自动执行 |
| **跨层适配** | `ToolRegistryAdapter` 将核心 Tool 体系无缝接入 LangChain Agent |
| **统一注册** | `agent_tools.py` 集中管理所有 Tool Schema，Agent 无需关心定义 |
| **工具->Agent 分离** | tools/ 目录按功能域独立，agents/ 按角色编排调用 |
| **持久记忆** | `ProjectMemory` 实现跨 run 的 valiflow.md 记忆机制 |
| **可测试性** | 每个 tool 目录有对应 `test_*.py` |

### 7.2 值得注意的问题

| 问题 | 位置 | 影响 |
|------|------|------|
| **Mock 数据** | `spec_tools/main.py`, `assertion_tools/main.py` 等返回硬编码数据 | 工具尚未对接真实仿真器/VCS |
| **doc_tools 异步混用** | `doc_tools/main.py` 同步函数内 `asyncio.run()` | 在已有 event loop 时会报错 |
| **tool_system.py 重复 import** | `record_invocation` 方法内重复 `import time`（L144） | 风格不一致，L22 已有 |
| **reuse_tools 参数签名** | `backup_to_library` 的 `source_dir` 不是类型注解缺省值 | 部分工具未在 `agent_tools.py` 注册 Schema |
| **regression_tools** | 位于 tools/ 目录但结构更接近独立框架 | 与其他 tools/ 风格不统一 |
| **Sandbox.console_approve** | 依赖 `input()` 阻塞式交互 | 在 Web/API 场景下不可用 |

### 7.3 建议

1. **将 Mock 工具逐步替换为真实后端调用**：`spec_tools`、`assertion_tools`、`coverage_tools`、`debug_tools` 目前返回静态 JSON，应接入真实 EDA 工具链
2. **统一 `asyncio` 使用**：`doc_tools` 应改为 async def 并配合 `asyncio.create_task()` 或在 LangChain 异步链中调用
3. **将 `reuse_tools` 的 10 个工具注册到 `agent_tools.py`**：目前 `reuse_tools` 未出现在中心注册表
4. **Sandbox 支持 Web 模式**：`console_approve` 应支持 callback/事件驱动替代 `input()`
5. **tools/ 目录风格统一**：`regression_tools/regression_framwork/` 层级过深，可考虑扁平化

---

## 8. 关键文件索引

| 文件 | 职责 |
|------|------|
| `src/core/tool_system.py` | 核心框架：Tool / ToolRegistry / Sandbox / ProjectMemory / ToolRegistryAdapter |
| `src/core/agent_tools.py` | 全局 Tool Schema 注册中心（`register_all_tools()`） |
| `src/core/container.py` | IoC 容器，管理 Service/Repository 依赖注入 |
| `src/infra/architecture.py` | 六层架构定义 + 领域映射 + 架构校验器 |
| `src/tools/spec_tools/main.py` | 规格分析：4 个 LangChain @tool |
| `src/tools/assertion_tools/main.py` | SVA 断言生成：8 个 LangChain @tool |
| `src/tools/coverage_tools/main.py` | 覆盖率：4 个 LangChain @tool |
| `src/tools/debug_tools/main.py` | 调试：4 个 LangChain @tool |
| `src/tools/doc_tools/main.py` | 文档查询：5 个 LangChain @tool（SQL 后端） |
| `src/tools/reuse_tools/main.py` | VIP 复用：10 个 LangChain @tool |
| `src/tools/testcase_tools/generator.py` | 测试用例生成引擎（YAML→SV，Jinja2） |
| `src/tools/uvm_tools/tool_uvm/gen_uvm.py` | UVM 代码生成引擎（YAML→SV，Jinja2） |
| `src/tools/cmodel_tools/gen_cmodel.py` | C-Model Predictor + DPI wrapper 生成 |
| `src/tools/cmodel_tools/dpi_compile.py` | DPI C++ 编译（g++ → .so） |
| `src/tools/regression_tools/` | 回归测试框架 |
