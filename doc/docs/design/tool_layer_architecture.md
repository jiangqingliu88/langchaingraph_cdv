# 工具层架构（`src/tools/`）—— 现状判定与目标形态

> 范围：只谈工具层。编排（LangGraph）、决策（L3）、记忆（L4）见
> `docs/design/full_project_refactoring_plan.md`。
> 本文与那份文档的关系：它 §3.1 / ADR-3 谈「工具怎么被调用」，本文谈
> **「工具自己长什么样」**——这是它没展开的那一半。

---

## 0. 一句话结论

**工具层的目标不是"更多工具"，而是"每个工具都是一个可复现、可审计、可替换的确定性单元"。**

这句话不是修辞。项目宣称的差异化是 **可复现 · 可审计 · 可治理**（CLAUDE.md 三·四节），
而这四件事在 LLM 层**做不到**——同一个 prompt 两次跑出两个结果。唯一能真正做到的地方
就是工具层：工具是确定性的，所以工具是可复现的；工具是可复现的，证据链才有根。

**因此工具层的架构判定标准只有一条：一个新工具进来，能不能在不动任何既有代码的前提下接上去、
被 Audit 看见、被换掉。** 今天这条做不到，所以今天的工具层是 **7 个包的形状各不相同 + 3 套
工具协议并存 + 契约层大面积失效**。

目标形态一句话：

> `src/tools/` 里**只放纯函数库**（dict 进 dict 出，零 LLM、零 Qt、零跨工具 import）。
> 工具对外的每一个"面"（Agent / CLI / GUI）都在工具**之外**生成。
> 工具之间只通过**文件格式契约**协作，不通过 Python 对象。

---

## 1. 判定口径

沿用 `full_project_refactoring_plan.md` 的标记：

| 标记 | 含义 |
|---|---|
| ✅ | 已实现，且有真实调用点 |
| ⚠️ | 部分实现 / 存在但被旁路 / 默认不生效 |
| ❌ | 声明存在，代码里没有 |
| 💀 | 有代码但零调用 |

---

## 2. 工具层的真实形状

### 2.1 十个包的成熟度分布

`src/tools/` 下现存 10 个包。它们不是"同一件事的十个实例"，而是**三代不同做法的叠层**：

| 包 | 目录结构 | 入口 | schema | 测试 | 纯度 | 代际 |
|---|---|---|---|---|---|---|
| `casemodel_tools` | `domain/ repository/ generation/ analysis/ tests/` | `api.py` + `cli.py` | `schema/*.json`（真在用） | `tests/` 10 文件 | ✅ 零 LLM/Qt（有守卫测试） | **第三代** |
| `uvm_tools/tool_uvm` | `templates/（~90 .j2） schema/ examples/` | `main.py` → `gen_uvm.py`(**3373 行**) | `schema/*.json`（真在用） | 3 文件（平铺） | 工具面纯 | **第二代** |
| `uvm_tools/tool_uvmtestgen` | 平铺 | `main.py`（670 行） | 无 | 1 文件 | 纯 | 第一代 |
| `assertion_tools` | 平铺 | `main.py`（8 个 `@tool`） | `schema.yaml`（**无人读**） | 1 文件 | **含 LangChain** | 第一代 |
| `coverage_tools` | 平铺 | `main.py`（4 个 `@tool`） | 无 | 1 文件 | **含 LLM 调用** | 第一代 |
| `debug_tools` | 平铺 | `main.py`（7 个 `@tool`） | `schema.yaml`（**无人读**） | 1 文件 | 纯 | 第一代 |
| `spec_tools` | 平铺 + `testplan.py` | `main.py`（3 个 `@tool`） | 无（`base.py` 指向的文件**不存在**） | 1 文件 | **含 LangChain** | 第一代 |
| `doc_tools` | 平铺 + `md2feishu.py` | `main.py` | 无 | 2 文件 | **含 LangChain** | 第一代 |
| `cmodel_tools` | 两个散脚本 | `dpi_compile.py` / `gen_cmodel.py` | 无 | **无** | 纯，但跨界 import | 零代 |
| `lib/` | 13 个模块 | `__init__.py` 只 re-export 3 个 | — | **无** | ❌ **含 LLM，且向上 import `src.layers`** | 垃圾桶 |

**读法**：只有 **1 个包（casemodel）** 走完了目标形态。它恰好是最近重写过的那一个 ——
这不是巧合，是"重写一次才会对它一次"。

### 2.2 已经跑通的范式：casemodel 的五段式

casemodel 之所以是模板，不是因为它文件多，而是因为它把五件事**各自放在唯一的地方**：

```
src/tools/casemodel_tools/
├─ api.py            ← 语义只此一份。def run_x(yaml_text) -> dict，零 LLM
├─ cli.py            ← 人用的面（argparse）
├─ schema/*.json     ← 输入契约，被 analysis/schema_check.py 真读
├─ domain/           ← 领域对象；**不 import 本包任何其它层**
├─ repository/       ← 只 import domain
├─ analysis/         ← import domain（+ repository 的产物）
├─ text.py           ← 只 import domain + analysis 的结果，不 import repository
├─ readme.md
└─ tests/            ← 与源码同址
```

它的分层规则写在 `domain/__init__.py:3-10`，且**依赖方向是靠 import 纪律维持的**：

> `domain 不 import 本包其它任何层` / `repository 只 import domain` /
> `generation import domain` / `analysis import domain（+ repository 的产物）`

它对外的接入面在**包外**（`src/agents/verify/casemodel/`），三个面共用 `api.py`
的同一份实现，且有测试钉住三者一致。

**这三条就是目标形态的全部内容**：一个实现、一个契约、面向外生成。

### 2.3 四条退化路径

其余九个包各自踩了不同的坑，合起来是四种：

**(a) LLM 代码住在工具目录里** ——
`assertion_tools/main.py:40` 等 8 处、`spec_tools/main.py:9` 等 3 处、`doc_tools/main.py:11`、
`coverage_tools/main.py:8`、`uvm_tools/agent_tools.py:22` 直接把 `@tool` 装饰器写在工具包里。
后果就是 `_lc_tool_compat.py:9` 自己记下的那句：

> 本仓库有 **49 处** `@tool("name")`，且大量调用点把工具对象当普通函数用

实测今天 `src/` 下有 **43 处** `@tool(`（不含 `_lc_tool_compat` 文档串里那句），
分散在 7 个包；而它们要经 **3 种不同适配器**（`_OldToolAdapter`、
`_LangChainToolAdapter`、原生 `ITool`）才能进 `ToolHub`。

**(b) 公共库变成公共垃圾场** ——
`src/tools/lib/`（~1900 行）自述是"所有 UVM Tool 的公共依赖"，但里面：

- `llm_refine.py:21` import `LLMFactory`、`llm_custom_logic.py:107` import `LLMQueryEngine`
  —— **LLM 代码住进了工具层**；
- `uvm_context.py:40` 懒 import `src.layers.l1_infrastructure.output_config`
  —— **依赖方向倒置**（工具层向上依赖层）；
- 被 23 个 `lib/` 之外的文件 import，包括 `src/cli/commands.py` 与 `src/layers/*`。

一个文件进 `lib/` 的判据今天是"反正别人也要用"，于是它必然膨胀成第二个 `src/`。

**(c) 工具之间互相 import** ——
本仓库的规矩写得很清楚（`casemodel_tools/readme.md:410`、`cli.py:240`、`api.py:38`
三处重申"工具互不 import，只有文件格式契约"），且有子进程守卫测试
（`tests/test_uvm_tests.py:155`）。但规矩只对 casemodel 生效：

| 违规点 | 说明 |
|---|---|
| `cmodel_tools/dpi_compile.py:28`、`gen_cmodel.py:62` | → `uvm_tools.tool_uvm.gen_uvm` |
| `uvm_tools/tool_jinja_render/main.py:13` | → `gen_uvm`（同一个包内，可容忍） |
| `lib/compile.py:12`、`llm_refine.py:13`、`loopback.py:15` | → `regression_tools.regression_framework` |
| `coverage_tools/main.py:203` | → `lib.llm_custom_logic`（跨界 + LLM） |

**(d) 契约层是装饰性的** ——
这一条最值得警惕，因为它**看起来是有的**：

| 契约 | 声称 | 事实 |
|---|---|---|
| 输入 schema | 12 份 `schema.yaml` | 只被 `base.py:395-399` 引用，且 5 个角色路径里 **3 个指向不存在的文件**（`spec_tools` / `uvm_tools` / `testcase_tools` 的 `schema.yaml` 均不在盘上） |
| 输出校验 | `BaseAgent.validate_output` | `base.py:403` 与 `:410` 两处 `except Exception: return True, []` —— **读不到/读失败即放行**，等于没校验 |
| casemodel 的 `schema.yaml` | 自述"三处不一致时以 `agent/registry.py` 为准，有测试固定" | `agent/` 目录与 `tests/test_surfaces.py` **都已被删除**，注释指向空气 |
| 风险分级 | `ToolRisk` 三档 | 见重构方案 §3.1：`ToolSandbox` 从不因 risk 拒绝 |
| 落盘回执 | `ToolAuditor` | 仅内存，`export_audit_log()` 无调用点 |

---

## 3. 按严重度排序的问题

| # | 问题 | 证据 | 级别 |
|---|---|---|---|
| 1 | **测试发现不到工具**：`pyproject.toml` 的 `testpaths = ["tests"]`，全仓 45 个测试文件里 **32 个在 `src/` 下**，`pytest` 裸跑一个都不收集 | `pyproject.toml` pytest 段；`find src -name "test_*.py" \| wc -l` → 32 | **P0** |
| 2 | 悬空引用：`tool_hub.py:455` 的 `_LC_TOOL_MODULES` 仍挂着已删除的 `src.tools.reuse_tools.main`；`testcase_tools` 有 4 处引用 | `tool_hub.py:455`；`agents/verify/main.py:123`；`governance/quality_guard.py:279`；`agents/base.py:397` | **P0** |
| 3 | `lib/` 里的 LLM 代码与向上依赖，让"纯工具"这条线从根上不成立 | `lib/llm_refine.py:21`；`lib/llm_custom_logic.py:107`；`lib/uvm_context.py:40` | **P1** |
| 4 | 一个工具要维护 N 个面，且面是手写的：casemodel 有 1 份 `api.py` + 3 份包装 | `agents/verify/casemodel/{langchain_tools,registry}.py` | **P1** |
| 5 | 入口命名三选一（`main.py` / `cli.py` / `api.py`），调用方得先读源码才知道怎么进 | 见 §2.1 表 | **P1** |
| 6 | 契约层失效（§2.3d）：schema 指向不存在的文件、校验失败即放行 | `agents/base.py:395-410` | **P1** |
| 7 | 工具之间跨界 import，把"换一个工具"变成"改一堆工具" | `cmodel_tools/*.py`；`lib/*.py` | **P2** |
| 8 | 删包留下的路径混乱（`regression_framwork` 拼写目录已删、`regression_framework` 在盘上） | `git status`；`lib/compile.py:12` | **P2** |

> 注：#1 是**一行改动、最大收益**。今天任何人跑 `pytest` 都会得到一个"全绿"的假象，
> 而工具层 297 + 若干条断言根本没被执行。

---

## 4. 目标架构

### 4.1 三层职责：工具 / 面 / 编排

```
        ┌──────────────────────────────────────────────┐
        │ 编排（src/layers/l2_orchestration）           │  LLM 在这里
        │ ToolHub · agents · LangGraph                 │
        └───────────────────┬──────────────────────────┘
                            │  只认 ITool / 回执
        ┌───────────────────┴──────────────────────────┐
        │ 面（src/agents/<role>/<tool>/）               │  适配 · 包装 · 三面生成
        │ langchain_tools.py · registry.py             │
        └───────────────────┬──────────────────────────┘
                            │  只调 api.run_*（dict → dict）
        ┌───────────────────┴──────────────────────────┐
        │ 工具（src/tools/<name>_tools/）               │  确定性 · 纯净
        │ api.py · domain/ · schema/ · tests/          │  ← 语义只此一份
        └──────────────────────────────────────────────┘
```

**硬规则（可机械检查，见 §7）**：

1. `src/tools/**` 不得 import `langchain*` / `PySide6` / `src.layers.*` / `src.agents.*`；
2. `src/tools/X_tools/` 不得 import `src/tools/Y_tools/`（Y ≠ X），`lib/` 见 §4.4；
3. 每个工具只有一个公开实现入口：`api.py` 里的 `run_*`，签名是 `(**可 JSON 化的参数) -> dict`；
4. 面**不许**包含语义：只做参数改名、JSON 字符串归一、风险标注，不许有 if/else 业务分支。

### 4.2 标准工具包模板

```
src/tools/<name>_tools/
├─ __init__.py         # 只 re-export api 的公开名字；不做副作用 import
├─ api.py              # 【必须有】语义唯一入口：
│                      #   def run_<verb>(yaml_text: str, ...) -> dict
│                      #   失败时返回 {"error": "..."}，不抛给调用方
├─ schema/
│   └─ <name>.schema.json   # 【必须有】JSON Schema，输入契约
├─ readme.md           # 【必须有】干什么 / 怎么用 / 与谁有契约
├─ tests/              # 【必须有】conftest.py + test_*.py，与源码同址
├─ cli.py              # 【可选】人用的命令行（argparse），只做 argv → api 的翻译
├─ domain/             # 【可选】领域对象（复杂工具才拆）
├─ repository/         # 【可选】读写与归一化
├─ <职责目录>/          # 【可选】按职责分，不按技术分
└─ templates/          # 【可选】产出文本时的模板
```

对应地，**禁止**出现在工具包内的：

| 禁止 | 理由 | 现在谁在违反 |
|---|---|---|
| `@tool` / `StructuredTool` / `BaseTool` | LLM 代码属于面 | assertion / spec / doc / coverage / uvm_tools |
| `LLMFactory` / `LLMQueryEngine` / 任何 `.invoke(llm)` | 同上，且破坏可复现 | `lib/llm_refine.py`、`lib/llm_custom_logic.py`、`coverage_tools/main.py:203` |
| `import src.layers.*` | 依赖倒置 | `lib/uvm_context.py:40` |
| `from src.tools.<别的包>` | 换一个工具会连锁改一堆 | `cmodel_tools/*`、`lib/compile.py` |
| 顶层 `print` 业务输出 | 工具不该决定输出形态 | `cmd_*` 已有，尚可 |
| 硬编码本机路径 | 破坏可复现 | `f:/questasim64_2024.1/win64` 在 ≥3 处 |

### 4.3 四条契约

工具能不能被"换掉"，取决于它对外承诺了什么。目标形态下**只有四条**：

| 契约 | 形态 | 谁检查 |
|---|---|---|
| **调用契约** | `run_*(...) -> dict`；失败 `{"error": str}`；不抛领域异常到调用方 | `api.py` + 面层 |
| **输入契约** | `schema/<name>.schema.json`，`additionalProperties: false` | 工具自己的 `tests/` |
| **产物契约** | 工具之间交换的是**文件内容**（YAML / JSON / SV 文本），不是 Python 对象 | 两侧各写一份测试（casemodel↔tool_uvm 已有范例） |
| **回执契约** | 每次调用产出 receipt：`tool_name · manifest_hash · args_summary · verified_by` | `ToolHub`（接 ADR-3） |

第四条是**把"可审计"落到工具层的唯一着力点**，也是今天唯一完全没接线的一条：
`ToolResult.verified_by`（`tool_protocol.py:211`，取值 `"eda" | "llm" | "none"`）已经定义好了
语义——**`"llm"` 不算签核级证据**——但没有任何地方消费它。

### 4.4 `lib/` 怎么处置

不是删掉，是**三分**。判据：一个文件能留在 `lib/`，当且仅当它

- (a) 是纯函数 / 纯数据，
- (b) 不 import `src.layers` 或 `src.agents`，
- (c) 不 import 任何 LLM 客户端。

| 现状 | 去向 | 依据 |
|---|---|---|
| `llm_refine.py`、`llm_custom_logic.py` | → `src/layers/l2_orchestration/context/` | LLM 基础设施本来就在那儿（`llm_factory.py`、`query_engine.py`） |
| `uvm_context.py`（thread-local `ctx` 单例） | → `src/tools/uvm_tools/`（它只服务 UVM 工具） | 不是通用 |
| `golden_library.py`、`collect_real_coverage.py`、`quality_report.py` | 归入对应工具包；若真被 ≥3 个包用，升格为独立工具包 `src/tools/<x>_tools/` | "共享"应当是一个**有契约的工具**，不是一个 py 文件 |
| `sim_log.py`、`filelist.py`、`regress_dir.py`、`static_check.py` | 留在 `lib/`，但补上 (a)(b)(c) 三条的守卫测试 | 真·共享纯函数 |
| `compile.py`、`loopback.py` | 见 §3 #7：先修跨界 import | — |

**`lib/` 的最终定位**：`lib/` = 工具层的 `domain/`，即**没有业务语义的纯工具函数**
（路径解析、文本切分、文件清单）。它**不应该有状态、不应该有 IO 副作用、更不应该有 LLM**。

### 4.5 工具之间怎么协作

两种，且只有两种：

1. **文件格式契约**（默认，用于一切"管道"）
   ```
   casemodel uvm-tests ──(一段 YAML 文本)──> tool_uvm environment.tests
   ```
   两侧各自持有"产物形状"的测试，互不 import。范例：`tests/test_uvm_tests.py`
   用 `subprocess` 断言 `api` 加载后 `sys.modules` 里没有任何 `src.tools.uvm_tools`。

2. **编排层调用**（用于运行时协作）
   Agent / 脚本自己 import 两个工具的 `api`，在**外面**组合。工具保持互不认识。

**唯一例外**：`src/workbench/` 允许同时 import 两边（它本来就是"编排"）。工具之间的
"自动管道"如果要落地，做成一个 workbench 模块，不要做成工具之间的 import。

---

## 5. 工具层 ADR

| 编号 | 决策 | 一句话理由 |
|---|---|---|
| **TADR-1** | 工具 = dict 进 dict 出的纯函数；**唯一的实现入口是 `api.py`** | 一个实现才能一个语义；多入口必然漂移（casemodel 的 `schema.yaml` 注释指向已删除的 registry 就是漂移的结果） |
| **TADR-2** | 工具的"面"一律在 `src/tools/` **之外**生成 | 让"工具能脱离 Agent/CLI/GUI 单独跑"从口号变成结构 |
| **TADR-3** | `src/tools/` 禁止出现 LangChain / LLM 客户端 / Qt | 可复现的前提是确定性；LLM 代码在工具层则复现不可能保证 |
| **TADR-4** | 工具之间只走文件格式契约；`lib/` 只放无状态纯函数 | 见 §4.5；换一个工具不该连锁改一堆 |
| **TADR-5** | schema 只有一种格式（JSON Schema）、一个位置（`schema/<name>.schema.json`）；**读不到就 fail-closed 并报错**，不许 `except: return True` | 今天的契约层是装饰性的，装饰性的契约比没有契约更危险 |
| **TADR-6** | 每个工具调用必须落盘一条 receipt（接重构方案 ADR-3） | 这是"可审计"在工具层的唯一着力点 |
| **TADR-7** | 测试与代码同址，且**默认 `pytest` 必须跑到** | 32/45 个测试文件今天不跑 |

---

## 6. 迁移路线

每一步都能独立验收，且**不改行为**（除标注处）。

### P0 · 止血（半天，纯机械）

| 动作 | 验收 |
|---|---|
| `pyproject.toml`: `testpaths = ["tests", "src"]` | `pytest --collect-only -q \| tail -1` 数量从 13 个文件涨到 45 个文件 |
| 删 `tool_hub.py:455` 的 `("src.tools.reuse_tools.main", "reuse")` | `ToolHub.bootstrap()` 日志不再出现"LangChain 工具包加载失败" |
| 处理 `testcase_tools` 的 4 处引用：要么恢复该包，要么把引用点改成显式 `NotImplementedError` 并列入 TODO | `grep -rn testcase_tools src/` 只剩注释 |
| 修 `regression_framwork` → `regression_framework` 的遗留引用 | `grep -rn framwork src/` 为空 |
| 删除 `uvm_tools/_tools_old.py`？ **先别删** —— 它仍被 `cli/commands.py:3157` 依赖。改为：把 `_build_filelist_for_tb` / `_run_compile_check` 移到有名字的模块，再删 | `grep -rn _tools_old src/` 为空 |

> P0 之后，"跑一遍测试"和"仓库里没有指向空气的路径"这两件事才第一次成立。

### P1 · 立规矩（1–2 天）

1. **写守卫测试**（放在 `tests/test_tool_layer_invariants.py`，跑在根 `tests/` 里）：

   | 不变式 | 实现 |
   |---|---|
   | 工具层无 LLM / Qt | 子进程 import 每个工具包，断言 `sys.modules` 无 `langchain*` / `PySide6` |
   | 工具之间不互相 import | `ast` 扫 `src/tools/**`，收集 `ImportFrom.module`，断言只有 `src.tools.lib` 与自身包 |
   | `lib/` 不向上依赖 | 同上，断言 `src/tools/lib/**` 无 `src.layers` / `src.agents` |
   | 每个工具包有 `api.py` / `schema/` / `readme.md` / `tests/` | 遍历 `src/tools/*_tools`，逐项断言存在 |

   casemodel 现有的两条守卫（`test_uvm_tests.py:155`、`test_repository.py:318`）推广成通用版，
   然后把包内的专用版删掉。

2. **`lib/` 三分**（§4.4）。判据写进 `lib/__init__.py` 的 docstring。

3. **契约层 fail-closed**：`base.py:395-410` 的 `except: return True` 改成读不到 schema 时
   **报错**（或至少 WARNING + 记录），并删掉 3 条指向不存在文件的映射。

### P2 · 收敛形状（3–5 天）

1. 给 5 个第一代工具补 `api.py`：把 `main.py` 里的函数原样搬进去（**不改逻辑**），
   `main.py` 变成 `from .api import ...` 的薄壳；补 `schema/<name>.schema.json`、`tests/`。
2. **一次定义、三面生成**：写一个 `src/agents/<role>/_surface.py`，从
   `api.run_*` 的函数签名 + schema 生成
   LangChain `@tool` / legacy `Tool` / `ITool` 三份包装。
   把 casemodel 手写的三份换成它，用现有 `tests/test_casemodel_agent.py` 做回归。
3. 收敛跨界 import：`cmodel_tools` 的两处 → 改经 `tool_uvm` 的 `JinjaRenderer`
   公开入口（或让 `tool_uvm` 把"渲染一段模板"做成 `api.run_render`）。

### P3 · 回执与分级（接重构方案 ADR-3）

1. `ToolResult` 的 `verified_by` / `evidence_ref` 真正写进 receipt 并落盘。
2. `vagent tool list` 增加"成熟度"列：

   | 级 | 判据 |
   |---|---|
   | **L0** | 有 `api.py`，可直接 import |
   | **L1** | L0 + `schema/*.json` + `tests/`，可独立验证 |
   | **L2** | L1 + 产物契约（与上下游有格式测试），可替换 |
   | **L3** | L2 + 回执落盘，可审计 |

   今天：`casemodel` ≈ **L2**，`tool_uvm` ≈ L1，其余 ≈ L0 或以下。
   **这个数字就是工具层重构的验收指标。**

---

## 7. 机械可查的守卫（最终形态）

| # | 规则 | 检查方式 | 今天有吗 |
|---|---|---|---|
| 1 | 工具层无 LLM / Qt | 子进程 import + `sys.modules` 断言 | 只有 casemodel 自己 |
| 2 | 工具之间不互相 import | `ast` 扫描 | ❌ |
| 3 | `lib/` 是纯的 | `ast` 扫描 | ❌ |
| 4 | 工具包结构完整 | 目录遍历断言 | ❌ |
| 5 | 工具测试默认被执行 | `testpaths` 含 `src` | ❌ |
| 6 | 每个工具名只在 `api.py` 定义一次 | grep 工具名常量 | ⚠️ 部分 |
| 7 | 无硬编码本机路径 | grep `[A-Za-z]:/` | ❌ |

> 判据：**一条规则如果没有机械检查，它就会在半年内失效。** 本仓库的"工具互不 import"
> 规矩写在三处注释里、且有测试——但只覆盖了一个包。这就是差别。

---

## 8. 不做

- **不做 MCP server**。`tool_protocol.py:5` 自述"对标 MCP"是启发式表述；在工具层形状收敛之前
  加一层网络协议，只会把不统一再复制一层。
- **不追求工具数量**。工具层的价值密度来自"每个工具可换"，不是"工具多"。
- **不做工具的自动发现 → 自动注册**。显式清单（如 `workbench/bridge/catalog.py` 的
  `BINDINGS`）是可审计的；自动发现会让"这个工具是什么时候进来的"无人可答。
- **不重写 `tool_uvm`**。它 3373 行的 `gen_uvm.py` 是已知的单体问题，但它**功能上是通的、
  有 schema、有测试**——属于"结构债"而不是"架构错"。按 P2 补 `api.py` 外壳即可，
  内部拆分另立一轮。
