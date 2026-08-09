# SignOffAI 工具架构分析报告

> 日期：2026-08-09  
> 分析范围：`src/core/tool_system.py`、`src/core/agent_tools.py`、`src/tools/*/`、`src/agents/*/main.py`  
> 目的：评估当前工具架构是否能对接第三方工具，识别架构问题并给出改进方案

---

## 1. 当前架构总览

```
┌─────────────────────────────────────────────────────────┐
│                      CLI Layer                           │
│            vagent tool list/call/history                 │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                   Agent Layer                             │
│  BaseAgent → LangChain AgentExecutor → @tool / Tool      │
│  consumes/produces 契约 → ctx 共享上下文                   │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│             Tool Registration Layer                       │
│  ┌─────────────────┐  ┌──────────────────────────┐      │
│  │ @tool 装饰器     │  │ ToolRegistry + Tool      │      │
│  │ (LangChain 原生) │  │ (SignOffAI 自研)         │      │
│  │ • spec_tools     │  │ • agent_tools.py 集中注册 │      │
│  │ • debug_tools    │  │ • uvm_tools/agent_tools  │      │
│  │ • coverage_tools │  │ • 含 JSON Schema 验证    │      │
│  │ • assertion_tools│  │ • risk_level 标注        │      │
│  └────────┬────────┘  └───────────┬──────────────┘      │
│           │                       │                      │
│           └───────────┬───────────┘                      │
│                       │                                  │
│         ToolRegistryAdapter.wrap() 桥接                   │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│              Tool Implementation Layer                    │
│  src/tools/                                              │
│  ├── uvm_tools/     ← 独立 main.py + run() 函数          │
│  ├── spec_tools/    ← @tool 装饰器 → LLM 直接调用         │
│  ├── debug_tools/   ← @tool 装饰器（硬编码示例数据）      │
│  ├── coverage_tools/← @tool 装饰器 + vcover.exe 调用     │
│  ├── assertion_tools/                                     │
│  ├── testcase_tools/                                      │
│  ├── doc_tools/                                           │
│  ├── reuse_tools/                                         │
│  └── lib/           ← 共享基础设施（compile/sim/static）   │
└─────────────────────────────────────────────────────────┘
```

### 核心数据流

```
Spec → Agent._read_ctx() → task_input (JSON string)
     → LangChain Executor
     → LLM 决定调用哪个 Tool(args)
     → ToolRegistryAdapter.validate_args()
     → Sandbox.check()
     → handler(args) 或 @tool func(args)
     → 返回 JSON string
     → Agent._write_ctx() → ctx[key] = parsed_output
```

---

## 2. 两套工具注册体系对比

| 维度 | `@tool` 装饰器 (LangChain) | `Tool` + `ToolRegistry` (SignOffAI) |
|:---|:---|:---|
| **使用位置** | `src/tools/spec_tools/main.py`<br>`src/tools/debug_tools/main.py`<br>`src/tools/coverage_tools/main.py` | `src/core/agent_tools.py`<br>`src/tools/uvm_tools/agent_tools.py` |
| **Schema 定义** | 无——LLM 从 docstring 推断参数 | 完整 JSON Schema（`input_schema`） |
| **参数验证** | 无——运行时 TypeError | 先验验证 `tool.validate_args()` |
| **风险控制** | 无 | `risk_level`: safe/write/danger → `Sandbox.check()` |
| **调用历史** | 无 | `ToolRegistry.record_invocation()` |
| **第三方可扩展** | ❌ 需要 import + 修改 Agent 代码 | ⚠️ 半可扩展——需在 `register_all_tools()` 中注册 |
| **LLM 兼容性** | ✅ 原生 LangChain function-calling | ⚠️ 需 `ToolRegistryAdapter.wrap()` 桥接 |

**问题**：两套体系并存，导致：
- 同一 Agent 的 tools 可能部分走 `@tool`，部分走 `ToolRegistry`
- 无法统一管理、审计、沙盒控制
- 第三方不知道应该用哪个接口接入

---

## 3. 第三方工具对接能力评估

### 3.1 当前对接路径

要接入一个第三方工具（如 Synopsys VCS、Cadence JasperGold、自定义 Python 脚本），目前需要：

```
步骤 1: 在 src/tools/ 下创建新目录
步骤 2: 写 main.py + @tool 装饰器 或 Tool 对象
步骤 3: 在 src/core/agent_tools.py 的 register_all_tools() 中手工注册
步骤 4: 在 Agent 的 _setup() 中设置 tool_registry
步骤 5: 在 Agent 的 Prompt 中描述新工具的用法
```

**对接成本**：修改 4+ 个核心源文件，破坏开闭原则。

### 3.2 关键缺失

| 能力 | 当前状态 | 对接影响 |
|:---|:---|:---|
| **插件发现机制** | ❌ 无 | 第三方工具无法自动被发现 |
| **标准 Tool 接口** | ⚠️ 有两套，不统一 | 开发者困惑该用哪套 |
| **配置文件注册** | ❌ 无 | 无法在不修改代码的情况下添加工具 |
| **独立进程隔离** | ❌ 无 | 第三方工具崩溃会影响主进程 |
| **依赖声明** | ❌ 无 | 不知道第三方工具依赖哪些二进制/库 |
| **版本管理** | ❌ 无 | 工具升级后无法复现历史结果 |
| **工具市场/索引** | ❌ 无 | 无法浏览可用工具 |
| **文档生成** | ❌ 无 | 无法自动生成工具使用文档 |
| **输入/输出类型安全** | ⚠️ JSON string 输入输出 | 无编译时类型检查 |
| **工具组合/编排** | ❌ 无 | 无法声明工具间的依赖关系 |

### 3.3 结论：当前架构 **无法零代码对接第三方工具**

---

## 4. 架构问题深度分析

### 问题 1：全局状态污染

```python
# src/tools/uvm_tools/tool_check_compile/main.py
from src.tools.lib.uvm_context import ctx  # ← 全局单例！
od = Path(env_dir) if env_dir else Path(ctx.output_dir)
```

**风险**：
- 工具不可重入（多个并发调用会互相覆盖）
- 无法隔离执行（一个工具的 ctx 变更会影响其他工具）
- 测试困难（必须 mock 全局状态）

### 问题 2：工具实现混杂

```python
# coverage_tools: collect_coverage 从真实的 vcover.exe 读数据
# debug_tools: analyze_simulation_log 返回硬编码示例数据
# spec_tools: analyze_specification 返回硬编码 UART 示例
```

**风险**：
- 部分工具是"真实的"，部分工具是"占位的"，但对外接口完全一样
- LLM 无法区分真实工具和 mock 工具
- 在生产环境中可能会静默使用 mock 数据

### 问题 3：Prompt 耦合

```python
# verify_architect/main.py — System Prompt 中硬编码了工具调用顺序
"""WORKFLOW (execute in order, one step at a time):
1. CALL find_spec_yaml(spec_text=<full markdown spec>)
2. CALL jinja_render(output_dir=<output_dir>)
3. CALL quality_report()
4. IF quality.passed == true, DONE.
"""
```

**风险**：
- 第三方工具无法插入到已有工作流中
- 更换工具时需要同时修改 Prompt
- Prompt 与工具实现强耦合

### 问题 4：无工具隔离执行

所有工具在同一个 Python 进程中运行：
- 一个工具的 `import` 异常会影响整个 Agent
- 无法限制工具的执行时间（无 timeout）
- 无法限制工具的资源使用（内存/CPU）
- 第三方工具的依赖冲突无法解决

### 问题 5：ToolRegistryAdapter 是单向桥接

```python
# ToolRegistryAdapter.wrap() 将 Tool → LangChain @tool
# 但没有 LangChain @tool → Tool 的反向转换
# 导致两套工具无法在同一个统计/审计视图中管理
```

---

## 5. 改进方案

### 5.1 统一 Tool 接口（短期，1-2 周）

定义标准 Tool Protocol，所有工具（内置 + 第三方）统一实现：

```python
# src/core/tool_protocol.py
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable
from enum import Enum

class ToolRisk(str, Enum):
    SAFE = "safe"
    WRITE = "write"
    DANGER = "danger"

class ToolStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"

@dataclass
class ToolManifest:
    """工具自描述清单 —— 第三方工具接入的唯一契约"""
    name: str                                    # 全局唯一名，如 "vcs_compile"
    version: str                                 # semver, 如 "1.2.0"
    description: str                             # 给 LLM 看的，决定何时调用
    author: str = ""
    
    # Schema
    input_schema: Dict[str, Any] = field(default_factory=dict)  # JSON Schema
    output_schema: Dict[str, Any] = field(default_factory=dict)  # 返回值 JSON Schema
    
    # 执行
    risk_level: ToolRisk = ToolRisk.SAFE
    timeout_s: float = 300.0                     # 超时限制
    retry_count: int = 0                         # 失败重试次数
    
    # 依赖
    requires_binaries: List[str] = field(default_factory=list)  # ["vcs", "verdi"]
    requires_python: str = ">=3.10"
    requires_packages: List[str] = field(default_factory=list)  # ["numpy>=1.21"]
    
    # 元数据
    tags: List[str] = field(default_factory=list)  # ["simulation", "synopsys"]
    status: ToolStatus = ToolStatus.ACTIVE
    examples: List[Dict[str, Any]] = field(default_factory=list)  # 给 LLM 的 few-shot


@runtime_checkable
class ITool(Protocol):
    """标准 Tool 协议 —— 所有工具必须实现"""
    
    @property
    def manifest(self) -> ToolManifest:
        """返回工具自描述清单"""
        ...
    
    async def execute(self, args: Dict[str, Any], context: "ExecutionContext") -> Dict[str, Any]:
        """执行工具。args 符合 manifest.input_schema，返回值符合 manifest.output_schema"""
        ...
    
    async def check_health(self) -> bool:
        """检查工具是否可用（二进制是否在 PATH 等）"""
        ...
    
    async def validate_input(self, args: Dict[str, Any]) -> List[str]:
        """业务级输入验证（超出 JSON Schema 的语义验证）"""
        ...
```

### 5.2 插件系统（中期，2-4 周）

```python
# src/core/plugin_manager.py
class PluginManager:
    """第三方工具插件管理器"""
    
    def __init__(self, plugin_dirs: List[str] = None):
        self.plugin_dirs = plugin_dirs or [
            "src/tools/",                    # 内置工具
            "~/.signoffai/plugins/",         # 用户级插件
            ".signoffai/plugins/",           # 项目级插件
        ]
        self._tools: Dict[str, ITool] = {}
    
    def discover(self) -> List[ToolManifest]:
        """从 plugin_dirs 发现所有工具。
        
        发现机制（按优先级）：
        1. Python 包：目录下有 __init__.py + tool.py（实现 ITool）
        2. 独立脚本：单个 .py 文件，顶层有 manifest 变量 + execute() 函数
        3. 配置文件：tool.yaml 描述外部 CLI 工具
        """
        ...
    
    def register(self, tool: ITool) -> None:
        """动态注册工具（无需重启）"""
        ...
    
    def get_llm_specs(self) -> List[dict]:
        """生成 LLM function-calling 规格"""
        ...
```

**插件目录结构示例**：

```
.signoffai/plugins/
├── vcs_simulation/
│   ├── tool.yaml          # 工具描述
│   ├── tool.py            # ITool 实现
│   └── requirements.txt   # Python 依赖
├── jaspergold_formal/
│   ├── tool.yaml
│   └── tool.py
└── custom_checker.py      # 单文件工具
```

### 5.3 外部 CLI 工具适配器（中期）

对 VCS/QuestaSim/JasperGold 等外部 CLI 工具，提供声明式配置：

```yaml
# tool.yaml — 零代码接入外部 CLI 工具
name: vcs_compile
version: "1.0.0"
description: Compile SystemVerilog with Synopsys VCS
risk_level: safe
timeout_s: 600

input_schema:
  type: object
  properties:
    filelist:
      type: string
      description: Path to filelist.f
    top_module:
      type: string
      description: Top-level module name
    options:
      type: string
      default: "-sverilog -debug_pp"
  required: [filelist, top_module]

output_schema:
  type: object
  properties:
    status:
      type: string
      enum: [PASS, FAIL]
    errors:
      type: integer
    warnings:
      type: integer
    log_path:
      type: string

exec:
  command: "vcs -f {filelist} -top {top_module} {options}"
  working_dir: "{output_dir}"
  env:
    VCS_HOME: "$VCS_HOME"
  
  # 输出解析
  parse_output:
    status:
      regex: "Compilation (succeeded|failed)"
      map: {succeeded: PASS, failed: FAIL}
    errors:
      regex: "Error-.*?(\d+)"
      group: 1
    warnings:
      regex: "Warning-.*?(\d+)"
      group: 1
```

### 5.4 工具执行沙盒（中期）

```python
# src/core/tool_sandbox.py
class ToolSandbox:
    """工具隔离执行环境"""
    
    async def execute(self, tool: ITool, args: dict, ctx: ExecutionContext) -> ToolResult:
        """在隔离环境中执行工具"""
        with self._timeout(tool.manifest.timeout_s):
            with self._resource_limit(memory_mb=1024, cpu_percent=50):
                try:
                    result = await tool.execute(args, ctx)
                    self._audit(tool, args, result)
                    return ToolResult(success=True, data=result)
                except ToolTimeoutError:
                    return ToolResult(success=False, error="Tool timeout")
                except ToolExecutionError as e:
                    return ToolResult(success=False, error=str(e))
```

### 5.5 工具注册中心（中期）

替代当前分散的 `register_all_tools()`：

```python
# 统一注册入口
class ToolHub:
    """全局工具注册中心 —— 单例，支持热加载"""
    
    def __init__(self):
        self._tools: Dict[str, ITool] = {}
        self._plugin_manager = PluginManager()
    
    def bootstrap(self):
        """启动时从所有来源加载工具"""
        # 1. 内置工具
        self._plugin_manager.discover("src/tools/")
        # 2. 用户/项目插件
        self._plugin_manager.discover("~/.signoffai/plugins/")
        self._plugin_manager.discover(".signoffai/plugins/")
        # 3. 外部 CLI 工具
        self._load_cli_tools()
    
    def list_tools(self, agent_role: str = None, risk: str = None) -> List[ToolManifest]:
        """按条件过滤工具列表"""
        ...
    
    def get_llm_tools(self, agent_role: str) -> List[dict]:
        """获取某 Agent 可用工具（已转化为 LLM function-calling 格式）"""
        ...
```

---

## 6. 改进路线图

```
Phase 1 (1-2 周): 统一接口，消除双轨制
├── 定义 ITool Protocol
├── 将所有现有工具迁移到 ITool
├── 统一 ToolRegistry → ToolHub
└── 废弃 @tool 装饰器直接调用路径

Phase 2 (2-4 周): 插件系统 + 沙盒
├── PluginManager + 自动发现
├── 外部 CLI 工具 YAML 适配器
├── ToolSandbox（超时/资源限制）
└── 工具版本锁定（pip 风格 requirements）

Phase 3 (4-6 周): 生态建设
├── 工具市场（在线索引 + 一键安装）
├── 自动文档生成（manifest → markdown）
├── 工具编排 DSL（声明式工具链）
└── 工具调用性能监控

Phase 4 (6-8 周): 企业级能力
├── 多租户工具隔离
├── 工具审批流程（管理员审核后才能使用）
├── 私有工具仓库
└── 工具计费/用量统计
```

---

## 7. 与业界对比

| 能力 | SignOffAI 当前 | Claude Code MCP | LangChain Tools | OpenAI Plugins |
|:---|:---|:---|:---|:---|
| 工具定义方式 | `@tool` + `Tool` 双轨 | MCP Server (JSON-RPC) | `@tool` 装饰器 | OpenAPI spec |
| Schema 验证 | ⚠️ 部分有 | ✅ JSON Schema | ✅ Pydantic | ✅ OpenAPI |
| 进程隔离 | ❌ 同进程 | ✅ 独立进程 (stdio/SSE) | ❌ 同进程 | ✅ HTTP |
| 插件发现 | ❌ 手工注册 | ✅ `mcp.json` 配置 | ❌ 手工导入 | ✅ manifest.json |
| 第三方接入 | ❌ 改源码 | ✅ 独立部署 MCP Server | ⚠️ 需 pip install | ✅ REST API |
| 工具组合 | ❌ | ✅ MCP 多 Server | ❌ | ❌ |
| 类型安全 | ❌ JSON string | ✅ JSON Schema | ✅ Pydantic | ✅ OpenAPI |
| 版本管理 | ❌ | ✅ Server version | ❌ | ✅ API version |
| 热加载 | ❌ | ✅ 修改配置即生效 | ❌ | ✅ |
| 权限控制 | ⚠️ risk_level 未强制执行 | ✅ 用户审批 | ❌ | ✅ OAuth |

---

## 8. 总结与建议

### 当前架构的核心问题

1. **双轨制**：`@tool` 和 `Tool` 两套体系并存，第三方不知道该用哪个
2. **无插件机制**：所有工具必须在 `register_all_tools()` 中硬编码注册
3. **无进程隔离**：第三方工具崩溃会影响整个平台
4. **全局状态污染**：`uvm_context.ctx` 全局单例导致不可重入
5. **prompt 硬编码**：工具调用顺序写死在 Agent Prompt 中

### 首要行动项

| 优先级 | 行动 | 工作量 |
|:---:|------|:---:|
| **P0** | 统一 ITool 协议，消除 `@tool` / `Tool` 双轨 | 3 天 |
| **P0** | 所有现有工具迁移到 ITool | 3 天 |
| **P1** | 创建 PluginManager，支持 `tool.yaml` 外部 CLI 配置 | 5 天 |
| **P1** | 创建 ToolSandbox，支持超时 + 资源限制 | 3 天 |
| **P2** | Prompt 中工具描述从 manifest 自动生成（去硬编码） | 2 天 |
| **P2** | 消除全局 uvm_context.ctx，改为参数传递 | 3 天 |

### 最终结论

**当前工具架构可以对内使用，但无法零代码对接第三方工具。**  
核心短板是缺少标准插件接口（对标 Claude Code 的 MCP 协议）。  
建议优先实施 Phase 1（统一接口），再实施 Phase 2（插件系统），最终达到"第三方工具只需提供一个 `tool.yaml` + 一个 `tool.py` 即可接入"的目标。
