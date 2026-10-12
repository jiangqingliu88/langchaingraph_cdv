# 验证闭环 —— 流程与输入件

> 这份文档回答两个问题：**这条闭环怎么走**，以及**它要吃什么**。
> 所有路径都是仓库里真实存在的；标「缺口」的地方是现在还没接上的，不是设计意图。

---

## 一、一句话心智模型

**它不是"帮你写 UVM 的 AI"，它是一条闭环流水线。**

你把一份规格丢进去，它自己跑：设计 → 搭环境 → 编译仿真 → 收覆盖率 → 判断差多少 →
决定下一步 → 回到编译再跑一轮，直到达标或用完轮次，最后**如实给出签核结论**。

三件事贯穿全程：

| 铁律 | 含义 | 落点 |
|---|---|---|
| **一** | EDA 是唯一真理 —— vlog/vsim 的 0/1 说了算，LLM 不自我判定 | `_verify_compilation`、回归 |
| **二** | 覆盖率库 SHA256 归档，证据可复现 | `docs/coverage_archive/` |
| **三** | LLM 只读**降采样后**的文本（日志/波形摘要），不读原始大数据 | debug 阶段 |

---

## 二、闭环七段（23 个节点）

阶段的**唯一**元数据来源是 `src/layers/l2_orchestration/stages.py`；
图的拓扑在 `src/layers/l2_orchestration/graph.py`。**界面不另抄一份**——
工作台的「流程视图」页就是读这份表画的。

| 段 | 节点 | 读什么 | 写什么 |
|---|---|---|---|
| ① 流程控制 | `init`、`round_bump` | — | `planning` 里程碑；轮次自增 |
| ② 设计与建模 | `design`、`model` | **规格**（`spec_text`） | `spec.json`、`rtl/*.sv`、`model/*_ref_model.sv`（注：`verify` 会再把 `spec.json` 存一次，供 `find_spec_yaml` 读） |
| ③ 验证构建 | `verify`、`env_arch_check` | `spec.json`、`rtl/`、**case 模型** | `agents/`、`env/`、`inputs/yaml/uvm/*.yaml`、`bench/` |
| ④ 编译与仿真 | `ops` | 上一步的 env + RTL | `build/`、`sim/`、回归结果 |
| ⑤ 覆盖率与调试 | `coverage`、`debug_functional` | 仿真日志、ucdb | `coverage/`、覆盖率摘要 |
| ⑥ 决策与收敛 | `decide` → `governor` → `approval` → `record_decision` → `apply_*` | 覆盖率差距、里程碑 | 决策记录；**回到 ④ 再来一轮** |
| ⑦ 审查与签核 | `audit`、`finalize` | 全过程的产物 | `report.json`、`docs/{manifest,evidence_chain,file_change_chain}.json` |

**⑥ 是回边。** `decide` 判断"差多少、该怎么补"，然后走七个 `apply_*` 之一：

```
apply_converge          达标收敛 → 离开循环
apply_compile_retry     编译重试
refactor_rtl            重构 RTL
apply_update_model      更新参考模型
apply_directed_test     生成定向测试
apply_relax             放宽约束
apply_expand_seeds      扩大随机种子
```

「不达标 → 再来一轮」就是这个流程的全部意义。**流程视图**里那条虚线画的就是它。

---

## 三、★ 关键输入件

按"要不要给"分三档。**只有第一档是必需的**。

### 3.1 必需（不给就跑不了）

| 输入件 | 位置 | 谁吃 | 说明 |
|---|---|---|---|
| **规格** | 任意路径，如 `specs/apb_uart/apb_uart_spec.md` | `design` agent | Markdown。**顶部可以带一段 HTML 注释元数据块**，解析器优先读它（`src/tools/spec_tools/main.py:30`） |

规格的元数据块写法（真实例子，`specs/apb_uart/apb_uart_spec.md`）：

```markdown
# APB UART 模块
<!--
  module: apb_uart
  level: BT
  data_width: 8
  baud_rates: [9600, 19200, 38400, 57600, 115200]
  fifo_depth: 16
  requirements: [REQ_APB_UART_001]
-->
```

不给元数据块也能跑——解析器会回退到从 `#` 一级标题和正文里提取，**但抓到的模块名/接口会差一些**。

### 3.2 可选（给了就改变行为）

| 输入件 | 位置 | 谁吃 | 不给了会怎样 |
|---|---|---|---|
| **运行参数** | 命令行 / GUI 表单 | `RunRequest` | 有默认值（目标 95%、5 轮、审批 threshold） |
| **人工节点声明** | `config/ide/manual_nodes.yaml` | `Runtime.manual_nodes` → `n_approval` | 走**兜底名单**：`REFACTOR_RTL` / `UPDATE_MODEL` 仍会要人批，但只有这两个 |
| **设计风格策略包** | `policies/{baseline,low_power,pipeline}/` | `verify` agent 注入 spec | 回退 `baseline` |
| **case 模型** | `spec["case_model"]` → 运行目录 `inputs/casemodel.yaml` → `config/casemodel/<模块>.yaml` | `verify` agent 的测试点分解（`_find_case_model`） | **跳过测试点分解**，日志明说"没有 case 模型" |
| **黄金参考模型库** | `model_library/`（索引 `INDEX.yaml`） | `model` agent 按 spec 特征匹配 | 未命中 → **诚实占位模型**（`audit` 会拦） |
| **预置 RTL + 黄金模型** | 输出目录里的 `rtl/`、`model/` | `--verify-only` 模式（bypass ②） | 不给就没东西可验 |

**运行参数**（`vagent verify --help` 的原文）：

```
--target FLOAT                 覆盖率目标
--max-rounds INTEGER           最大闭环轮次
--approval [interactive|auto|threshold]   默认 threshold：仅高危动作询问
--design-style TEXT            baseline / pipeline / low_power
--full-regression              全量回归（默认增量，只跑未 passed）
--verify-only                  验证专注模式：bypass design/model
```

`case 模型`的格式（功能组织树 + P0/P1/P2 专题 + 维度约束组合）见
`config/casemodel/examples/cpu_pipeline.yaml` 与 `docs/design/constraint_policy_guide.md`。

### 3.3 环境前提

| 前提 | 位置 | 不给会怎样 |
|---|---|---|
| **LLM** | `.env` 的 `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL` | agent 初始化失败 → **退化到模板路径**（design/model 靠模板，verify 编不出东西） |
| **QuestaSim** | `f:/questasim64_2024.1`（或 `QUESTA_HOME`） | 编译/仿真起不来 —— 铁律一没有裁判 |
| **署名** | `PLATFORM_USER_NAME` | 回落到系统登录名（写进证据链的"谁改的/谁批的"） |

### 3.4 不是闭环输入的（别搞混）

| 文件 | 它其实是给谁的 |
|---|---|
| `config/workbench.yaml` | **工作台界面清单**（GUI 有哪些页），不是一次运行的输入 |
| `config/regression/*.yaml` | **独立的回归工具**（`python regression.py --config ...`），闭环不走它 |
| `config/trend/trend.yaml` | 界面只读展示用的数据源 |
| `config/ide/manual_nodes.yaml`（编辑界面） | 文件本身是闭环输入，但「人工节点」页只是它的编辑器 |

---

## 四、中间产物链（为什么输入件重要）

一段的产出是下一段的输入。**卡住运行的几乎总是这条链上的某个中间件**：

```
规格 spec.md
   └→ spec.json ──────────────────┐
        └→ rtl/*.sv                │
        └→ model/*_ref_model.sv    │
                                   ↓
        inputs/yaml/uvm/{agent,env,bench}.yaml ─→ gen_uvm 渲染 → agents/ env/ bench/
        inputs/yaml/case_table.json（casemodel 分解测试点）
                                   ↓
                            inputs/filelists/filelist.f ─→ vlog ─→ build/
                                   ↓
                              sim/ ─→ coverage/ ─→ 决策 ─→ 回到上面再来一轮
                                   ↓
        docs/{run_events.jsonl, manifest.json, evidence_chain.json, file_change_chain.json}
        report.json
```

**这些中间件是可以人工审查和编辑的** —— 工作台的「产物审查」页就是干这个的
（左边按段列出产物、标出 schema 不符的那几份，右边编辑，保存会记进证据链）。

---

## 五、人工介入的四处

AI 判不了、只有人能判完的地方：

| 位置 | 界面 | 为什么必须是人 |
|---|---|---|
| **中间产物审查** | 产物审查 | 生成的 UVM 配置对不对，得对着规格看 |
| **覆盖率豁免** | 覆盖率豁免 | "这个洞是不是结构不可达"是**设计知识**；批准会改动覆盖率分母 |
| **高危动作审批** | 验证流程的审批条 | 改 RTL / 改参考模型会让已有签核证据失效 |
| **签核签署** | 签核判定 | 门禁是机器算的，**签名得是人** |

四处共用同一个骨架：**一份产物 + AI 预判 + 人的一个动作 + 一次记账**。

高危动作审批走**检查点**：运行停在 `interrupt()` 上，**关掉程序、明天再批也能接着跑**，
批完从断点重入。审批 payload 里带产物清单，所以人能看到自己在批准什么文件。

---

## 六、两条入口

同一套引擎、同一份证据。

| 场景 | GUI（`run_gui.bat`） | CLI |
|---|---|---|
| 起一次运行 | 验证流程 → 填规格 → 选预设 → 启动 | `vagent verify spec.md --target 90 --max-rounds 5` |
| 一站式 | —— | `vagent plan spec.md` |
| 看进度 | 流程视图 / 验证流程 | `vagent watch` |
| 看历次 | 运行历史 | `vagent runs` / `vagent history` |
| 审查产物 | 产物审查 | `vagent evidence check`（对账） |
| 审批 | 审批条（可关掉明天再批） | `vagent runs approve <run> -m "理由"` |
| 签核 | 签核判定 | `vagent signoff <run>` / `vagent archive <run>` |
| 复现 | —— | `vagent dump <run> --step <n>` |

---

## 七、现状与已知缺口（诚实）

**链路是通的**：运行能端到端走到 `finalize`，能停下来等人、能带产物审批、能重入续跑、
能记账、能对账、能用完轮次后如实签核。

**但"能跑绿"还差一截**，缺口按阻塞程度排：

| # | 缺口 | 性质 |
|---|---|---|
| 1 | `templates/interface_templates/port_config.sv.j2` 把 `uvm_field_*` 宏放在字段声明**之前** | 模板顺序，与 UVM 惯例相反 → Questa 判未定义变量 |
| 2 | `templates/environment_templates/env_pkg.sv.j2` import 了 `_typedefs_pkg` / `_sc_pred_env_pkg`，**没有任何模板生成它们** | 模板引用了不存在的包 |
| 3 | `bench_templates/tb_top.sv.j2` 渲染出 `import _test_pkg::*`（`env_name` 渲染时为空） | 渲染回填缺失 |
| 4 | `apb_uart_env_gen_test.sv` 生成的测试代码有语法错 | 生成器 |
| 5 | **没有 spec → case 模型的桥**：设计阶段不产出 case 模型，所以测试点分解目前是"有条件生效" | 设计缺口 |
| 6 | `regression_framework` 整棵树只剩 `.pyc`（sourceless）；`testcase_tools` 已删但消费者曾未跟上 | 半途重构 |

前 4 条是**同一条链上的生成器 bug**，修完才能编译通过；
第 5 条决定了 case 模型这个输入件**现在是可选的、不是常态生效的**。

---

## 附：相关文档

- `docs/design/gui_pipeline_architecture.md` —— 工作台外壳与模块契约
- `docs/design/agent_gui_business_architecture.md` —— 界面业务架构（九条业务线）
- `docs/design/golden_model_library.md` —— 黄金参考模型库
- `docs/design/constraint_policy_guide.md` —— case 模型 / 约束策略
- `docs/design/tool_layer_architecture.md` —— 工具层
- `docs/决策闭环架构.md` —— 决策与收敛
