# SignOffAI 重构到 DeepSeek Harness 方案

> 版本: v0.1 | 日期: 2026-08-17 | 状态: 方案评审
> 前置: [PROJECT_ANALYSIS.md](../../PROJECT_ANALYSIS.md)（旧架构分析）、`docs/design/harness_feature_design.md`（IC 验证测试台架设计，与本方案中的 "Harness" 是不同概念）

---

## 一、背景与动机

2026-08-17 的代码审计发现，SignOffAI 存在三个结构性问题：

| # | 问题 | 证据 |
|---|------|------|
| 1 | **自建 AI 编排层过度膨胀且与 LLM 耦合** | 七 Agent + L1-L5 五层约 39,000 行，其中 L2 编排（execution/governance/decision）、L3 决策、L4/L5 记忆占大头；核心价值（EDA 集成、证据链）只占小部分 |
| 2 | **LLM 代码生成不稳定被评分体系掩盖** | vlog 编译是唯一门禁（语法级，非功能级）；失败被静默降级（丢弃 IP、neutralize gap seq、a+b 模板参考模型）；debug agent 对"无日志"返回 95 分；audit 永远 success=True |
| 3 | **文档、测试、代码三者脱节** | README 描述 11 Agent + src/web（不存在）；测试 import 已删除模块（37 failed）；venv 开箱即坏；`.env.example`/`pyproject.toml` 乱码 |

**结论**：SignOffAI 真正有价值、值得保留的是三样东西——

1. **领域知识**：UVM 模板、覆盖率归因、回归框架、签核规则（散落在 Agent 提示词与工具里）
2. **EDA 工具链集成**：QuestaSim 编译/仿真/覆盖率、vlog 门禁、ucdb 哈希固化（L1 基础设施）
3. **证据链**：file_audit 哈希链、manifest、签核证据包

而**自建的 AI 编排层（LLM 工厂、决策引擎、Governor、经验库）与 DeepSeek Harness（DSH）原生能力高度重叠**，属于重复造轮子，且质量不如 DSH 的成熟实现（LLM 路由/重试/降级、subagent 生命周期、workflow 编排、goal 治理、人工审批）。

**本方案的目标**：把 SignOffAI 重构为 **"DSH 编排 + Markdown 知识（Skill）+ Python 工具后端"** 三层结构——领域知识与 Agent 提示词固化为 Markdown Skill 文档，闭环流水线改为 DSH workflow 编排，Python 代码瘦身为纯工具执行层。

---

## 二、重构目标与原则

### 2.1 目标

- **T1**：`dsh --profile headless "verify specs/apb_uart/apb_uart_spec.md --target 80"` 一条命令跑通 规格→RTL→UVM→回归→覆盖率→签核 闭环
- **T2**：删除自建 AI 编排层（约 60% 的 Python 代码退役），领域知识 100% 可维护于 Markdown
- **T3**：失败必须响亮——EDA 缺失/LLM 产出被否决时明确 FAIL，不再出现"无日志=95 分"式假通过
- **T4**：每条 Skill 有验收 checklist；工具层有 pytest；闭环有端到端冒烟测试

### 2.2 原则

| 原则 | 说明 |
|------|------|
| **铁律保留** | 三条铁律（EDA 是唯一真理 / 覆盖率库版本固化 / LLM 只读降采样文本）不因重构而放松，写进新的 CLAUDE.md |
| **工具层先冻结** | 能跑的 EDA 集成（vlog/vsim/ucdb 路径）先冻结，只做接口契约化，不重写内部逻辑 |
| **知识全量下沉 Markdown** | 一切提示词、模板选择规则、决策规则、验收标准，从 Python 代码搬进 SKILL.md |
| **单一事实源** | 文档（README/架构/产品介绍）以当前代码为准重写，禁止再出现"文档描述不存在的模块" |
| **说真话优先** | 评分与真实产物绑定（RTL 存在且过功能仿真、覆盖率来自真实 ucdb、参考模型非模板），不达标就 FAIL |

---

## 三、概念映射（SignOffAI → DSH）

| SignOffAI 概念 | 去向 | DSH 承载物 |
|----------------|------|-----------|
| 七 Agent（design/model/verify/ops/coverage/debug/audit） | 退役为角色提示词 | **Skill**（`skills/<name>/SKILL.md`）+ **subagent**（按需委派） |
| `LLMFactory` / `LLMQueryEngine` / token 预算 | 删除 | DSH 原生 LLM 路由 / 重试 / 降级 / 预算 |
| `PipelineExecutionService.run_closed_loop` | 重写 | **workflow** 脚本（`workflows/*.js`，阶段化 + 子代理并行） |
| `CoverageDrivenDecisionEngine`（8 动作） | 保留逻辑、改载体 | workflow 内确定性规则（或独立 `vagent decide` 纯函数工具） |
| `Governor`（熔断/预算/干预） | 删除自建 | workflow 的 try/catch + max_rounds 上限 + **goal 工具**（长周期）+ 人工审批门控 |
| L1 基础设施（EDA 后端/编译自愈/覆盖后端/黄金基线） | **保留** | Python 工具后端，经 CLI 暴露 |
| 证据链（file_audit/manifest/签核包） | **保留** | Python 工具后端 + `evidence-chain` Skill 的验收规则 |
| L4 记忆（debug 经验/覆盖归因/IP 库/exclude 库） | 部分保留 | sqlite 工具保留为后端；"经验"本身固化为 SKILL.md 的已验规则 |
| L5 蒸馏 | 删除 | Skill 迭代：验证过的提示词/模板直接写回 SKILL.md |
| `src/web`（不存在） | — | 不建（CLAUDE.md 铁律：禁止 Web） |
| `vagent` CLI | 保留但瘦身 | 降级为"纯工具执行器"，输入输出 JSON 化 |

---

## 四、目标目录结构

```
cdv_a/                               ← 项目根（最近的含 .git 的祖先目录）
├── CLAUDE.md                      # 工作区指令：项目定位 + 三条铁律 + 工具后端调用约定（更新现有）
├── .dsh/
│   └── skills/                    # DSH Skill 目录（项目级，rank 100：<projectRoot>/.dsh/skills）
│       ├── ic-spec-analysis/SKILL.md
│       ├── rtl-generation/SKILL.md
│       ├── uvm-env-generation/SKILL.md
│       ├── regression-ops/SKILL.md
│       ├── coverage-analysis/SKILL.md
│       ├── debug-triage/SKILL.md
│       ├── signoff-audit/SKILL.md
│       ├── evidence-chain/SKILL.md
│       └── eda-tooling/SKILL.md
├── workflows/                     # DSH workflow 脚本（JS）
│   ├── verify-closed-loop.js      # 主闭环（替代 run_closed_loop）
│   ├── signoff-package.js         # 签核证据包
│   └── multi-module.js            # 多模块并发（替代 run_multi_module）
├── tools/                         # Python 工具后端（原 src/ 瘦身后的产物）
│   ├── eda/                       # L1：EDA 后端/编译/覆盖率（基本不动）
│   ├── uvm/                       # UVM 模板 + 渲染 + 校验
│   ├── coverage/                  # 覆盖率收集/归因/gap
│   ├── debug/                     # 日志收集/分类/修复模板
│   ├── evidence/                  # 证据链/manifest/签核包
│   └── cli.py                     # vagent 瘦身版：5-6 个核心命令，--json 出口
├── specs/                         # 规格库（不变）
├── policies/                      # 策略包（不变，Skill 引用）
├── docs/                          # 文档体系（重构为与代码一致）
│   ├── design/refactor_to_deepseek_harness.md   ← 本文档
│   ├── architecture.md            # 新架构说明（替代 README 里的旧结构图）
│   └── roadmap.md
├── tests/                         # 重写
│   ├── unit/                      # 工具层 pytest（含真实 EDA 标记 @eda）
│   └── acceptance/                # Skill 验收 checklist（markdown）
└── .gitignore / .env.example      # 修正编码，统一 UTF-8
```

---

## 五、Skill 清单（含 frontmatter 草案）

DSH Skill 格式（已确认，见 `dsh-skill-filesystem` 文档）：
- 位置：项目级 `<项目根>/.dsh/skills/`（rank 100，项目根 = 最近的含 `.git` 的祖先目录）；用户级 `$DSH_HOME/skills`（rank 400）
- 形式：单层目录 `<name>/SKILL.md`，或扁平 `<name>.md`（不支持嵌套 `**/SKILL.md`）
- frontmatter：必填 `name`（必须 kebab-case）+ `description`；可选 `whenToUse` / `metadata` / `disable-model-invocation` / `user-invocable`
- 变更发现：Chokidar 监听，创建/修改自动进会话 skill 目录

以下 9 个 Skill 覆盖七 Agent 的全部领域知识。

### 5.1 ic-spec-analysis（替代 spec 分析 + spec_planner 提示词）

```markdown
---
name: ic-spec-analysis
description: 从 IC 设计规格 Markdown 提取结构化信息（design_name/interfaces/features/registers），
  输出 spec.json。用于任何"给定规格文档，产出验证所需结构信息"的任务。
---
# IC 规格分析
## 输入/输出契约
- 输入: spec.md 全文
- 输出: spec.json（design_name, interfaces[], features[], registers[], interrupts[]）
## 提取规则（确定性，禁止自由发挥）
1. design_name 优先取 <!-- module: xxx --> 注释，回退一级标题；非字母数字统一转下划线
2. interfaces 从接口表格提取，字段: name/data_width/direction/protocol/description
3. features 从 ### 章节标题提取，前 5 个 P0 其余 P1
4. registers 从寄存器表提取: offset/name/width/access/description
## 验收 checklist
- [ ] spec.json 的 design_name 非 "dut" 占位（除非规格确无名称）
- [ ] 每个接口行都映射到 interfaces（与规格表格行数一致）
- [ ] 输出可由 uvm-env-generation 直接消费
```

> 说明：现有 `src/tools/spec_tools/main.py` 的 `analyze_specification` 已是确定性正则，直接把其规则抄入 Skill 并退役 Python 版本（或保留为后端工具）。

### 5.2 rtl-generation（替代 design agent 的 LLM 写手）

```markdown
---
name: rtl-generation
description: 按 IP 库拆解 + 小 IP 粒度生成 SystemVerilog RTL，经 vlog 编译门禁；
  顶层集成优先 LLM 连线，失败回退确定性骨架。
---
# RTL 生成
## 流程
1. 从 spec.json 拆 IP（查 ip_registry 匹配，reused 直接复用库 RTL）
2. 每个新 IP: LLM 生成完整 module（端口=时钟/复位+接口信号）
3. 门禁: vlog 编译必须 PASS，否则丢弃该 IP（禁止写回）
4. 顶层: LLM 实例化连线 → 失败回退 _gen_top_module 确定性骨架
## 提示词要点（固化，勿自由发挥）
- always_ff 单驱动 / 敏感列表统一 @(posedge clk or negedge rst_n)
- 只输出 SystemVerilog 无 markdown
## 验收 checklist
- [ ] rtl/*.sv 全部通过 vlog 编译
- [ ] 顶层端口与 spec.json interfaces 一致（无悬空输出）
- [ ] 被否决的 LLM 产出有日志记录（audit 可查）
```

### 5.3 uvm-env-generation（替代 verify agent）

```markdown
---
name: uvm-env-generation
description: 用 Jinja2 模板从 spec.json 生成 UVM 环境（agent/driver/monitor/scoreboard/env/test）
  + 测试用例 YAML + SVA 断言；gap 定向激励按覆盖率缺口生成并经编译门禁。
---
# UVM 环境生成
## 流程
1. find_spec_yaml: spec.json → bench.yaml/env.yaml/regression.yaml
2. jinja_render: 模板渲染 45 个 SV 文件
3. testcase_tools: parse_test_points → map_policies_to_tests → build_scenario_yaml
4. assertion_tools: 生成 SVA（绑定到 DUT）
5. gap 模式: 按 gap 生成 _gap_seq.sv → vlog 门禁 → 不过则 neutralized 并记录
## 验收 checklist
- [ ] agents/*/ 下全部 SV 存在且 vlog 编译通过
- [ ] env/{module}_env_pkg.sv 生成，bench 顶层命名 {module}_bench_tb_top
- [ ] 命名与 compile.py 期望一致（历史坑：_bench 中缀，见 harness_feature_design.md §2.3）
```

### 5.4 regression-ops（替代 ops agent + RegressionRunner 知识）

```markdown
---
name: regression-ops
description: 编译 + 仿真 + 回归执行。封装 vlog/vsim 命令链、UVM 库路径、seed 控制。
  工具失败时必须返回可诊断的错误（区分 EDA 缺失 / 编译错 / 仿真错）。
---
# 回归执行
## 命令链（QuestaSim）
- 编译: vlog -work build/work -cover sbceft -f filelist.f（UVM 库路径从配置读）
- 仿真: vsim -c -coverage +UVM_TESTNAME=... -sv_seed <seed> {module}_bench_tb_top
## 失败分类（铁律：失败必须响亮）
- vlog 找不到 → EDA_MISSING（升人工，禁止进入 debug 假通过路径）
- 编译 Error → COMPILE_FAIL（带 file:line，走编译自愈）
- 仿真 UVM_ERROR → SIM_FAIL（带日志路径）
## 验收 checklist
- [ ] 回归结果 JSON: {compile, passed, failed, total, stderr, log_path}
- [ ] EDA_MISSING 时不会产生"0 错误"的假 clean 信号
```

### 5.5 coverage-analysis（替代 coverage agent + 覆盖率归因）

```markdown
---
name: coverage-analysis
description: 收集真实覆盖率（vsim -coverage → ucdb → 报告），按语义归因 gap
  （unreachable/constraint/unstimulated），产出 coverage.json + gap 向量 + 覆盖地图。
---
# 覆盖率分析
## 流程
1. 收集: simulate_with_coverage（子进程隔离，EDA 崩溃不拖垮主流程）
2. 归因: build_coverage_gaps(覆盖率, 约束, toggle 明细) → gap 向量
3. 版本固化: ucdb SHA256 + coverage_summary.txt（铁律二）
4. LLM 空洞分析只读降采样文本，绝不读 ucdb（铁律三）
## 验收 checklist
- [ ] coverage.overall_pct 来自真实 ucdb（非估算）
- [ ] gap.reason ∈ {unreachable, constraint, unstimulated}
- [ ] coverage_db.sha256 非空
```

### 5.6 debug-triage（替代 debug agent，修正假通过）

```markdown
---
name: debug-triage
description: 失败根因诊断。收集仿真/编译日志 → 分类 → 指纹去重 → 模板修复 → LLM 兜底重写
  → EDA 重验。关键铁律：没有日志 = 无法诊断（N/A），绝不等于"无错误"。
---
# 失败诊断
## 铁律（修正历史 bug）
- 输入为空（无 sim log 且无 compile log）→ 返回 status=NO_EVIDENCE，阻断下游，禁止给 95 分
- 只有 EDA 缺失导致的失败 → 返回 EDA_MISSING 分类，不进入代码修复路径
## 流程
1. collect_sim_log / collect_compile_log → all_errors
2. all_errors 为空且 EDA 可用 → clean（此时才允许高分）
3. _classify_error 12 类 + 指纹去重
4. auto_fix 模板 → 不中则 LLM 重写出错文件 → 重跑验证
## 验收 checklist
- [ ] 无日志时 status ∈ {NO_EVIDENCE, EDA_MISSING}，score 为 0
- [ ] 修复必须经 rerun 验证（PASS 才记为 verified）
```

### 5.7 signoff-audit（替代 audit agent）

```markdown
---
name: signoff-audit
description: 签核判定。回归全过 + 覆盖率达标（含 Exclude 调规后的有效覆盖率）
  才 APPROVED；任何缺失（无 RTL/无覆盖率/参考模型是模板）→ NEEDS_FIX 且必须 FAIL。
---
# 签核审计
## 判定规则
- 前置门禁（全部满足才可能 APPROVED）:
  [ ] rtl/*.sv 存在且 vlog 通过
  [ ] coverage.overall_pct 来自真实 ucdb
  [ ] 参考模型非 a+b 模板（有黄金模型哈希比对）
  [ ] failed == 0
  [ ] effective_coverage >= target
- 任一不满足 → NEEDS_FIX，且 AgentResult.success = False（历史 bug：永远 success=True）
## 验收 checklist
- [ ] 0% 覆盖率 + 无 RTL 时，阶段状态为 FAIL（不是 passed score=40）
```

### 5.8 evidence-chain（替代自建证据链知识）

```markdown
---
name: evidence-chain
description: 记录 Agent 产物文件（git diff + 理由）到哈希链，生成 manifest.json（输入/输出/决策/
  覆盖率版本固化），导出签核证据包 ZIP 并验证完整性。
---
# 证据链
## 操作
- file_audit.record(文件, 理由, 角色) → 哈希链落盘 evidence_chain.json
- manifest 生成: phases + rtl_hashes + coverage_db_history + exclude 效果
- 每个 LLM 阶段记录 prompt_hash / response_hash / model（可复现性，历史缺口）
## 验收 checklist
- [ ] chain_valid == True（篡改任何一条即断裂）
- [ ] manifest 含每个 LLM 阶段的 prompt/response 哈希
```

### 5.9 eda-tooling（替代 L1 探测知识）

```markdown
---
name: eda-tooling
description: 探测 EDA 后端可用性（questa/vcs/verilator），生成/选择 filelist，
  封装 compile_healer（编译错误分类 + 确定性修复 + LLM 兜底）。
---
# EDA 工具
## 探测
- 工具缺失 → 明确 EDA_MISSING（升人工，禁止进入流水线假装运行）
## 自愈
- CompileErrorAnalyzer 分类 → CompileSelfHealer 确定性修复 → LLM 兜底重写 → 重编译
## 验收 checklist
- [ ] 无 EDA 环境下运行闭环在第一步 FAIL 并给出安装指引
```

---

## 六、Workflow 编排设计（替代 run_closed_loop）

### 6.1 verify-closed-loop.js 骨架

```js
// workflows/verify-closed-loop.js
// 阶段: spec → rtl → uvm → [regress → coverage → decide]×N → signoff
const args = { specFile: args.specFile, target: args.target ?? 80, maxRounds: args.maxRounds ?? 5 };

phase("spec-analysis");
const spec = await agent(`读取 ${args.specFile}，调用 skill ic-spec-analysis 产出 spec.json 并写入 output/spec.json`, { schema: specSchema, label: "spec" });

phase("rtl-generation");
await agent(`按 skill rtl-generation 生成 RTL 到 output/rtl，spec.json 在 output/spec.json`, { label: "rtl" });

phase("uvm-generation");
await agent(`按 skill uvm-env-generation 生成 UVM 环境到 output/，spec.json 在 output/spec.json`, { label: "uvm" });

let coverage = 0;
for (let r = 1; r <= args.maxRounds; r++) {
  phase(`regress-r${r}`);
  const reg = await agent(`按 skill regression-ops 执行回归，output 目录见上下文`, { label: `regress-${r}` });
  if (reg.compile === "FAIL" && reg.errorType === "EDA_MISSING") {
    log(`EDA 缺失: 停止并升人工`);  // 失败响亮
    return { status: "BLOCKED_EDA_MISSING" };
  }
  if (reg.failed > 0) { phase("debug"); /* skill debug-triage */ continue; }

  phase(`coverage-r${r}`);
  const cov = await agent(`按 skill coverage-analysis 收集覆盖率`, { label: `cov-${r}` });
  coverage = cov.overallPct;

  // 决策（确定性规则，与旧 decision_engine 同逻辑，但改在编排层）
  const action = decide({ coverage, gaps: cov.gaps, compileError: reg.compileError });
  if (action === "CONVERGE") break;
  await applyAction(action);  // GENERATE_DIRECTED_TEST / RELAX_CONSTRAINT / EXPAND_SEEDS / REFACTOR_RTL / UPDATE_MODEL
}

phase("signoff");
const result = await agent(`按 skill signoff-audit + evidence-chain 产出 report.json 与证据包`, { label: "signoff" });
return { status: result.verdict, coverage, effectiveCoverage: result.effectiveCoverage };
```

### 6.2 决策规则迁往何处

两种方案二选一（推荐 A）：

- **方案 A（推荐）**：`decide()` 提取为 `tools/cli.py decide --obs <json>` 纯函数工具（保留 Python 里的 gap 归因/RL 权重逻辑），workflow 调用它。Python 只留"决策计算"，不留 Agent/LLM 代码
- **方案 B**：把 8 动作决策状态机重写为 JS，逻辑内联在 workflow。优点是无 Python 依赖；缺点是重复实现

### 6.3 治理映射

| 旧能力 | 新载体 |
|--------|--------|
| Governor 熔断（连败 3 次） | workflow `decide()` 里计数 + 升人工 |
| token/EDA 预算 | DSH 原生预算 + workflow 对 EDA 调用次数计数 |
| 人工审批（REFACTOR_RTL/UPDATE_MODEL） | workflow 暂停等待 + `vagent approve`（保留 CLI 审批记录，进证据链） |
| max_rounds | workflow 循环上限 |
| RL Q 表（.signoffai/rl_policy.json） | 保留为 `decide` 工具的输入（不影响正确性，只做权重提示） |

---

## 七、工具层改造（vagent 瘦身）

### 7.1 保留的核心命令（JSON 出入口）

```
vagent spec    <spec.md> -o output/          → output/spec.json
vagent rtl     -o output/                    → rtl/*.sv + 门禁结果
vagent uvm     -o output/                    → env/ agents/ assertions/
vagent regress -o output/ --seed N           → regression.json
vagent cover   -o output/ --seed N --round R → coverage.json + gaps
vagent decide  --obs obs.json                → action.json（决策纯函数）
vagent signoff -o output/                    → report.json + 证据包
vagent approve <run_id> --reason "..."       → 审批记录（进证据链）
```

- 全部命令 `--json` 输出（已有实现），退出码语义化：0=成功 / 1=业务失败 / 2=EDA 缺失 / 3=配置错误
- 删除：`agent` 命令组（七 Agent 退役）、`exp`/`distill`（L4/L5 退役）、`govern`/`exclude`（治理迁入 workflow；exclude 状态库保留为 decide 输入）

### 7.2 退役清单（删除的模块）

| 删除 | 理由 | 替代 |
|------|------|------|
| `src/agents/*`（7 个 main.py） | 角色逻辑已入 Skill | Skill + workflow 的 agent() 调用 |
| `src/layers/l2_orchestration/agents/*`、`execution.py` | 编排层 | workflow |
| `context/llm_factory.py`、`query_engine.py`、`middleware/*` | LLM 路由 | DSH 原生 |
| `governance/*`（governor/quality_guard 部分） | 熔断/审批 | workflow + CLI approve |
| `l3_decision/brain/*`、`knowledge/*`（可先留 decide 纯函数） | 决策层 | `vagent decide` |
| `l4_memory/debug_experience.py`、`coverage_experience.py`、`l5_evolution/*` | 经验/蒸馏 | Skill 迭代固化 |
| `regression_framework/`（若独立于核心链路） | 重复实现 | 保留 eda/ 内的精简版 |

### 7.3 保留不动

- `l1_infrastructure/eda_backend.py`、`compile_healer.py`、`coverage_backend.py`、`golden_baseline.py`、`infrastructure.py`
- `tools/uvm_tools/`（模板 + 渲染 + 校验）、`tools/lib/`（filelist/compile/collect_real_coverage）
- `evidence/file_audit.py`、`manifest.py`、`governance/approval.py`（审批记录）
- `l4_memory/ip_registry.py`、`exclude_registry.py`、`testcase_registry.py`（作为工具后端的数据存储）

---

## 八、分阶段迁移路线

| 阶段 | 内容 | 产出 | 验收 |
|------|------|------|------|
| **P0 基线修复**（0.5 天） | 修 venv 路径；统一 UTF-8（.env.example/pyproject/.gitignore）；删除/修复 import 失效的 5 个测试文件；README 对齐当前 7 Agent 架构 | 测试套件可收集，README 不撒谎 | `pytest` 收集通过 |
| **P1 知识固化**（1-2 天） | 按 §5 写 9 个 SKILL.md，从七 Agent 提示词/工具 docstring 搬运规则 | `skills/` 目录 | 每个 Skill 有验收 checklist；无 Python 代码残留提示词 |
| **P2 CLI 契约化**（1 天） | vagent 瘦身到 §7.1 的 8 命令，`--json` 全通，退出码语义化 | 新 `tools/cli.py` | 8 命令冒烟通过（含 EDA 缺失时退出码 2） |
| **P3 最小闭环**（2-3 天） | 写 `workflows/verify-closed-loop.js`，用 subagent+Skill+CLI 跑通 apb_uart | workflow 可运行 | `dsh headless` 一条命令出 report.json |
| **P4 治理迁移**（1 天） | decide 纯函数化；审批/熔断/预算接入 workflow；证据链记录 LLM prompt/response 哈希 | 闭环可干预 | REFACTOR_RTL 前有人工审批；熔断后升人工 |
| **P5 退役与收敛**（1 天） | 按 §7.2 删除退役模块；重写 README/架构文档；tests 重写（unit + acceptance） | 瘦身后的仓库 | 删除量 ≥60%；全量测试通过 |

**总计约 6-8 个工作日**，其中 P1 是价值最高的（知识先固化，代码随时可删）。

---

## 九、风险与对策

| 风险 | 等级 | 对策 |
|------|------|------|
| **EDA 环境依赖**（QuestaSim license/路径） | 🟡 | EDA 探测前置（eda-tooling Skill）；缺失时 workflow 第一步 FAIL + 安装指引；工具层不因编排重构而改 |
| **重构破坏能跑的 EDA 集成** | 🔴 | 工具层先冻结（P0-P2 不动 eda_backend/uvm_tools），只加 CLI 壳；P3 闭环验收跑真实仿真 |
| **LLM 生成不稳定**（用户核心痛点） | 🔴 | 三条铁律写进 CLAUDE.md + Skill 验收；功能 oracle（黄金参考模型）作为 P1 的隐藏项——参考模型库须过定向 case 仿真验证才能入库，禁止 a+b 模板 |
| **评分继续造假**（假通过回归） | 🔴 | signoff-audit Skill 前置门禁（§5.7）+ workflow 阶段 FAIL 语义化；`debug-triage` 禁止 NO_EVIDENCE 高分 |
| **Skill 漂移**（文档又滞后） | 🟡 | Skill 验收 checklist 进 pytest（解析 SKILL.md 断言关键规则存在）；CLAUDE.md 要求"改 Agent 行为 = 改 Skill 文档" |
| **DSH Skill 目录约定** | 🟢 已确认 | 项目级 `<projectRoot>/.dsh/skills`（rank 100）；格式 `<name>/SKILL.md` 单层目录或 `<name>.md` 扁平；`name` 必须 kebab-case，frontmatter 必填 name+description；不支持嵌套 `**/SKILL.md`；Chokidar 自动发现 |
| **编码历史债**（GBK 乱码文件） | 🟡 | P0 全仓 `file` 检测 + 统一 UTF-8；pre-commit 加编码检查 |

---

## 十、成功标准（验收清单）

- [ ] `dsh --profile headless "verify specs/apb_uart/apb_uart_spec.md --target 80"` 端到端跑通，report.json 的 verdict 来自真实门禁
- [ ] 无 EDA 环境：第一步 FAIL，退出码 2，给出安装指引（不再出现 "passed 7/16 + debug 95 分"）
- [ ] `pytest tests/` 全绿（unit 含真实 EDA 标记；无 import 失效）
- [ ] 自建 AI 编排层删除量 ≥60%（git diff 统计），`src/agents`、`l2 execution`、`context/llm_factory` 等目录消失
- [ ] 每个 SKILL.md 有验收 checklist，且 checklist 中的铁律（EDA 唯一真理/失败响亮/LLM 只读降采样）被 pytest 断言存在
- [ ] manifest.json 记录每个 LLM 阶段的 prompt_hash/response_hash/model（可复现性闭环）

---

## 附录 A：与现有文档的关系

| 文档 | 处置 |
|------|------|
| `CLAUDE.md` | 更新：补"工具后端调用约定 + 三条铁律 + Skill 维护规则" |
| `README.md` | 重写为当前架构（7 Agent 已退役为 Skill + workflow 描述） |
| `PROJECT_ANALYSIS.md` | 归档到 docs/archive/（描述的是已删除的旧架构） |
| `docs/design/harness_feature_design.md` | 保留（IC 验证测试台架设计与本方案正交；其中 §2.3 命名坑直接引用到 uvm-env-generation Skill 验收） |
| `SignOffAI产品介绍.md` / `ppa_vs_cov.md` / `review.md` | 归档或按新架构改写 |

## 附录 B：术语表

- **DSH / DeepSeek Harness**：本仓库所在的 AI 开发环境（launcher + profile + 工具注册表 + skill + workflow + subagent + goal）
- **Skill**：DSH 的 Markdown 指令文档（`SKILL.md`，YAML frontmatter + 正文），通过 `skill` 工具按名加载
- **Workflow**：DSH 的 JS 编排脚本，可扇出 subagent、分阶段并行
- **IC 验证 Harness**（注意区分）：UVM 测试台架 tb_top（见 harness_feature_design.md），与本方案中的 DSH Harness 无关
