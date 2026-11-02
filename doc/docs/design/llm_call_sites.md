# 点状 LLM 与执行器 —— 全量清单

> **本文回答两个问题**：LLM 在这套系统里到底在哪些地方被调用？8 个执行器各自做什么、谁碰 LLM？
>
> 所有结论都经**代码逐点核验**（含"零调用者的死代码"与"绕过收口的旁路"），
> 不是从设计文档抄的。改动后请回来更新。
>
> 日期：2026-10-10

---

## 一、一句话结论

> **LLM 在这套系统里是"点状"的，不是"引擎"。**
> 流程由 LangGraph 的边定死、决策由规则引擎定死、工具选择由手写管线定死 ——
> LLM 只在 7 个位置被调去「生成一段代码」或「给一个假设」。
> **8 个执行器里 6 个完全不碰 LLM。**

---

## 二、8 个执行器

代码在 `src/executors/`。**它们不是"会自己思考的 agent"** ——
没有一个有 ReAct 循环，全部覆写 `execute_task` 走手写确定性管线。

| 执行器 | LLM | 核心做法 | 产物 |
|---|---|---|---|
| **front** | ❌ | 读 spec / RTL 文件，正则解出模块名与端口 | spec 摘要 |
| **design** | ✅ **2 处** | IP 拆解（规则）→ **LLM 写每个 IP 的 RTL** → `vlog` 门禁 → **LLM 写顶层** | `rtl/*.sv` |
| **model** | ❌ | **Jinja 模板**渲染 C++ 参考模型 | `model/` |
| **verify** | ❌ | **模板** + policy pack 生成 UVM 环境与用例 | `env/ tests/` |
| **ops** | ❌ | subprocess 跑编译 / 仿真 / 回归 | `regression.json` |
| **coverage** | ❌ | 收 ucdb + **规则**归因 gap（unreachable/constraint/unstimulated） | `coverage.json` |
| **debug** | ✅ **2 处** | 五阶段确定性管线（收集→分类→定位→修复→验证）+ LLM 根因分析 | debug report |
| **audit** | ❌ | 四道签核门禁（纯计算：RTL 存在 / 回归全过 / 覆盖率真实 / 模型非占位） | `report.json` |

**为什么 6 个不碰 LLM 不是"降级"**：这是 `CLAUDE.md` 的定位 ——
「LLM 只做"完形填空"，不决定整体结构」。写 C++ 参考模型用模板、生成 UVM 用模板、
覆盖率归因用规则 —— 这些本来就**不该**交给 LLM，交给它反而不可复现。

---

## 三、所有 LLM 调用点

### 3.1 唯一收口

```
                    ┌─────────────────────────────────────┐
                    │  LLMQueryEngine.query()             │
   全部 7 个点 ────►│  · token 预算检查（超限直接返回空串）  │
                    │  · 响应缓存                          │
                    │  · 重试 + provider 降级               │
                    │  · 审计（cache_key = prompt）         │
                    └──────────────┬──────────────────────┘
                                   │
                        ┌──────────▼──────────┐
                        │  llm_call.call_llm  │  ← 全项目唯一出口
                        └─────────────────────┘
                                   ▲
        ┌──────────────┬───────────┴────────┬──────────────────┐
   executors/design  tools/coverage_tools  tool_find_spec_yaml  lib/llm_refine
                        （转手给 debug 与仿真时序修复）
```

`src/tools/lib/llm_call.py::call_llm(prompt, code, errors)` 是**唯一出口**。
它进 dict 出字符串，失败一律返回**空串不抛** —— 调用方拿空串判"LLM 没给出东西"
并走确定性回退；抛异常会把"LLM 挂了"升级成"流水线挂了"。

### 3.2 七个调用点

| # | 位置 | 谁触发 | 让它做什么 | 产物形态 |
|---|---|---|---|---|
| 1 | `executors/design/main.py`<br>`_llm_write_ip` | design 阶段，**每个 IP 一次** | 写该 IP 的 SystemVerilog 功能逻辑 | 完整 `.sv` |
| 2 | `executors/design/main.py`<br>`_llm_write_top` | design 顶层集成 | 例化所有 IP + 按端口名连线 | 完整 `.sv` |
| 3 | `tools/coverage_tools/main.py`<br>`llm_generate_gap_stimulus` | 覆盖率有 gap | 写 sequence body 里的驱动代码 | 代码片段 |
| 4 | `tools/uvm_tools/tool_find_spec_yaml/main.py`<br>`_llm_classify_protocols` | 生成 UVM env 时 | 把 DUT 端口按协议分类 | JSON dict |
| 5 | `executors/debug/main.py`<br>`_llm_regenerate_file` | 模板 `auto_fix` **无匹配** | 重写出错的那份文件 | 完整文件 |
| 6 | `lib/llm_refine.py`<br>`llm_refine_sim_timing` | 仿真出时序问题 | 诊断 + 出修正版 | `===FILE:x===` 分块 |
| 7 | `executors/debug/main.py`<br>`_llm_analyze` | Phase 6：**还有未归类的错误** | 给根因假设（JSON 输出） | JSON（**不改任何东西**） |

### 3.3 三类调用点的性质不同

| 类 | 点 | 性质 |
|---|---|---|
| **生成** | #1 #2 #3 #4 | "给我造一段之前不存在的东西" —— 规则/模板穷举不了，才交给 LLM |
| **修复** | #5 #6 | "改一段已经存在的东西" —— 模板修复失败后的兜底 |
| **只读分析** | #7 | **只给假设，不改任何文件**。它落到 `debug_result["llm_analysis"]` |

**#1 / #2 是全项目最重的两个点**：它们决定了你的 DUT 长什么样 ——
所以围栏也最厚（`_is_valid_rtl()` 检查 module 声明 + 端口闭合 `);` + `endmodule`，
残缺就丢；prompt 细到"每个 reg 只能在一个 always_ff 里赋值"。

---

## 四、为什么叫"点状" —— 在代码里可验证

| 谁决定 | 怎么决定 | 证据 |
|---|---|---|
| **流程**（下一步走哪个阶段） | LangGraph 的**边** | `graph.py:109-164` 的 `add_conditional_edges`，写死 |
| **决策**（覆盖率不够时做什么） | 规则引擎的**硬编码优先级链** | `decision_engine.py` 的 `decide()`；`HARD_ACTIONS` 连 RL 都不许碰 |
| **工具**（调哪个工具） | 各执行器手写管线直接 `call_tool(...)` | 例：`debug/main.py` 的 Phase 1 |
| **LLM 做什么** | 只在上面 7 个位置被调，且都是"生成/修一段代码或给个假设" | 见 §3.2 |

所以 **LLM 是流程上的一个个"点"，不是驱动流程的"引擎"**。

---

## 五、收口前后的对照（这次改了什么）

改之前有**两条同义路径**，其中一条绕过治理：

| | 改之前 | 改之后 |
|---|---|---|
| 出口 A | `llm_custom_logic._call_llm_raw` → **经 query_engine** ✅ | `llm_call.call_llm` → 经 query_engine ✅ |
| 出口 B | `llm_refine.call_llm` → `LLMFactory + llm.invoke()` **裸调** ❌ | 已删除，转调 A |
| 出口 C | `debug._llm_analyze` → `self.llm.ainvoke()` **裸调** ❌ | 已改为经 query_engine |

**B 和 A 是逐字节相同的两份实现** —— 报文格式、`code[:3000]` / `errors[:1000]`
的截断、``` 剥壳规则全都一样，唯一差别就是那一条走不走 `query_engine`。

后果不是"少了个优化"，是 **token 预算只管住一半流量** ——
而绕过去的那一半恰好是 #5 #6 #7，即"出错后的兜底重试"路径，
**最容易在收敛不了时反复触发**。

### 顺带删掉的死代码

| 删的 | 为什么 |
|---|---|
| `execution._llm_repair_compile_error` | **零调用者** |
| `llm_refine.llm_refine_compile_errors` | **零调用者**（只在 `generated_files.py` 的注释里被提到） |
| `llm_custom_logic` 的 `llm_generate_custom_logic` / `inject_custom_logic_sv` / `generate_fallback_drive` / `generate_fallback_sample` | **零外部调用者**；模块本身改名成 `llm_call.py`，只留收口那一个函数 |
| `uvm_tools/_tools_old.py` 的整份 `_call_llm` 副本 | 旧实现（1753 行），只被 `commands.py` 引用其两个**非 LLM** 函数 |

---

## 六、执行器的 LLM 可用性 —— 一个布尔，不是一个客户端

改之前：`BaseExecutor.initialize()` 里 `self.llm = LLMFactory.create_for_task(...)`。
**为了判一个布尔值，构造了一个完整的 `ChatOpenAI`**（pydantic 校验 + 取 key +
挂 token 回调），而它一次 `invoke` 都不会有 —— 因为真正的调用已经全走 `llm_call`。

改之后：

```python
# executors/base.py
self.llm_available: bool = False        # 不是 self.llm
...
self.llm_available = LLMFactory.is_available(settings=self.settings)
```

`LLMFactory.is_available()` **只做静态检查**，判据与 `create_llm` 的降级链**同源**：

| 情形 | 可用? | 依据（与 `create_llm` 一致） |
|---|---|---|
| `deepseek` / `openai` + 有 api_key | ✅ | 直接走 `_create_openai_compat` |
| 无 api_key | ❌ | `create_llm` 在进 provider 循环**之前**就抛 |
| `anthropic`（`langchain_anthropic` 未装） | ❌ | `_create_anthropic` 必然 ImportError |
| `custom` 无 `base_url` | ❌ | `_create_for_provider` 直接抛 |
| `custom` 有 `base_url` | ✅ | |
| 主 provider 不可用但 **fallback 可用** | ✅ | `create_llm` 逐个 try，全失败才抛 |

唯一的消费者是 debug 的 Phase 6（`if not self.llm_available: return ""`）。

回归由 `tests/test_llm_availability.py` 钉住 —— 其中一条专门验
**探测期间不构造任何客户端**（否则这次就白改了）。

---

## 七、遗留（知道但没动）

| 项 | 说明 |
|---|---|
| `llm_factory.py` 的 `llm.invoke("test")` | **探活**（连接测试），不是业务调用，不进预算是对的 |
| `llm_call.call_llm` 的报文壳 | `CODE:…ERRORS:…` 是为修复类准备的；生成类调用方传 `code=""`/`errors=""`，那层壳对它们是空转。保留是为了不改变已跑通的报文形状 |
| `uvm_tools/_tools_old.py`（1753 行） | 整份旧副本，只被 `commands.py` 引用其两个**非 LLM** 函数。删除要先把那两个函数迁走 |

---

## 八、加一个新的 LLM 调用点时的 checklist

1. **不要** `LLMFactory.create_for_task(...)` + `llm.invoke(...)` —— 那条路绕过预算/缓存/审计
2. **不要** `self.llm.ainvoke(...)` —— 同上
3. 走 `from src.tools.lib.llm_call import call_llm`
4. 拿到空串要**显式回退到确定性路径**，并把"这次回退"记进 notes 或日志 —— 不静默
5. 输出是代码的，加**契约校验**（照 `design._is_valid_rtl` 的样子）——
   LLM 的输出不可信，围栏是这一层唯一的保障
6. 改完回来更新本文件的 §3.2

---

## 九、相关文档

| 文档 | 内容 |
|---|---|
| `docs/design/architecture_optimization_plan.md` | 现状诊断 + P0–P3 路线（本文 §5 是它的 P1-4） |
| `docs/design/verification_flow.md` | 闭环拓扑（执行器之间怎么流转） |
| `CLAUDE.md` | 「LLM 只做完形填空」这条定位的原文 |
