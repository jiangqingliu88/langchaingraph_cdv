# SignOffAI — 项目状态分析（全项目）

> 生成时间：2026-09-05 · 分支 `sign_off_ensure_v0`
> 范围：整个智能体系统（agents × layers × tools × CLI × 数据/配置）

---

## 一、项目定位

SignOffAI 是 **IC 验证垂直领域的智能体**（纯 Python CLI，无 Web 前端）。目标是把
「规格 → RTL → UVM → 回归 → 覆盖率 → 签核」做成可复现、可审计、可治理的 AI 闭环。

**三条铁律**（代码落点明确）：
1. EDA 是唯一真理（`vlog` 返回 0/1，失败响亮，禁止假通过）
2. 覆盖率库版本固化（ucdb SHA256 归档）
3. LLM 只读降采样文本（空洞分析不读几十 GB 的 ucdb）

---

## 二、架构总览

两个正交维度：**五层引擎（横切能力平台）+ 七个 Agent（纵向领域角色）**。

```
L5 进化(蒸馏/成长)      ←────────── 横切引擎（所有 Agent 共享）
L4 记忆(经验库/IP库/用例库)
L3 决策(RL 决策引擎 + 知识图)
L2 调度(编排/注册/通信/证据链/治理/中间件/工具市场)
L1 基础设施(EDA 后端/编译自愈/覆盖后端/黄金基线)
     │        │        │        │        │        │        │
   design   model   verify   ops   coverage  debug   audit   ← 纵向七 Agent
```

- `layers/` = 引擎（89 文件），`agents/` = 角色（19 文件），`tools/` = 领域工具（807 文件）
- L2 的 `execution.py` 编排七 Agent 成闭环；Agent 通过 `BaseAgent` 继承 + `register_agent` 注册

**闭环流程**：`design → model → verify → [ops → coverage → decide]×N → audit`，
决策动作：`COMPILE_RETRY / REFACTOR_RTL / UPDATE_MODEL / GENERATE_DIRECTED_TEST / RELAX_CONSTRAINT / EXPAND_SEEDS / CONVERGE`。

---

## 三、各子系统成熟度（按代码规模）

| 子系统 | 规模 | 成熟度 | 说明 |
|---|---|---|---|
| **L2 编排** | 12191 行 | 🟢 最成熟 | registry/execution/context/communication(MCP+subprocess)/evidence/governance/middleware/tool_marketplace |
| **L4 记忆** | 3797 行 | 🟢 成熟 | ip_registry/testcase_registry/exclude_registry/debug_experience + SQLite persistence |
| **L3 决策** | 1603 行 | 🟡 中等 | decision_brain(RL policy/state_encoder) + knowledge graph |
| **L1 基础设施** | 1387 行 | 🟢 成熟 | eda_backend/compile_healer/coverage_backend/golden_baseline |
| **L5 进化** | 369 行 | 🟡 中等 | distillation（3 通道+验证+灰度+回滚）+ growth（动作经验/成熟修复蒸馏/跨项目迁移）|

**七 Agent**（`src/agents/`）：

| Agent | 行数 | 职责 | 状态 |
|---|---|---|---|
| design | 507 | spec→IP→RTL（LLM + vlog 门禁） | 核心闭环 |
| model | 371 | 参考模型（版本+回滚） | ⚠️ 仍产出模板占位 |
| verify | 291 | UVM 环境 + 测试 YAML + SVA | 依赖 tool_uvm |
| ops | 149 | 编译/仿真/回归 | 直接调 L1 |
| coverage | 243 | 覆盖率收集 + gap 归因 | 核心闭环 |
| debug | 544 | 日志→分类→指纹→模板修复→LLM 兜底 | 最完善 |
| audit | 123 | 四道门禁签核 | 聚焦门禁逻辑（G1-G4 完整，失败响亮） |

---

## 四、工具生态（`src/tools/`，807 文件）

| 分类 | 文件数 | 说明 |
|---|---|---|
| **uvm_tools** | 700 | 最大：`tool_uvm`（生成器）+ 10 个 check/generate 工具（compile/env_arch/health/loopback/static/find_spec_yaml/jinja_render/quality_report/read_file/write_file/sc_red）+ `tool_uvmtestgen` |
| regression_tools | 51 | 回归框架 |
| lib | 23 | 公共库（含 `golden_library`） |
| debug_tools | 9 | 调试 |
| assertion_tools | 7 | 断言 |
| spec_tools | 7 | 规格 |
| coverage_tools | 6 | 覆盖率 |
| doc_tools | 5 | 文档 |
| reuse_tools | 4 | 复用 |
| cmodel_tools | 2 | C 参考模型 |

**tool_uvm**（本会话重点改造）：已从「单 agent 平铺」演进为 **AXI-VIP/UVMF 风格**——
master/slave 完全分离、事件驱动 Slave、RAL、bind harness、pragma custom 注入、渲染前语义校验、编译门禁、测试点生成。详见 `tool_uvm/PROJECT_STATUS.md`（本文件已并入）。

---

## 五、测试状态

```
tests/          102 passed, 1 skipped  ✅（本会话修复 2 个 golden_bench 失败）
tool_uvm/       32 passed ✅
tool_uvmtestgen 依赖 openpyxl（已入 pyproject.toml + requirements.txt，装完即可跑）
```

本会话修复的测试失败：
- `test_golden_bench.py` 2 个 —— 裸 `jinja2.Environment` 用子目录 searchpath，无法解析
  `{% include "base_templates/..." %}`；改为复用 `JinjaRenderer`（含 `now`/`trademark`/`copyright_year` globals）。

---

## 六、已知问题（README 列出，本会话核实）

| # | 问题 | 当前状态 |
|---|---|---|
| 1 | **真实参考模型（golden）**：model agent 产出模板占位，audit 拒签 | ⏳ 未完全解决。`model_library/` 已有 5 个黄金模型（apb_slave/fifo16/irq_gen/uart_rx/uart_tx），但 model agent 尚未接库（`find_spec_yaml._gen_apb_register_model` 是雏形） |
| 2 | MCP 工具层断链（tool_worker 引用 `regression_tool`） | ✅ 疑似已解决（grep 未再找到该引用；ops/coverage 直接调 L1） |
| 3 | `env_arch_check` 无 EDA 报 `[WinError 2]` | ✅ 已解决（现有 EDA_MISSING 前置检查） |

---

## 七、本会话改动总结（tool_uvm 全链路）

- interface 层重写为 AXI-VIP 风格（1-8 层 + loopback + filelist/Makefile）
- master/slave 完全分离 + 事件驱动 Slave + RAL + 错误注入/乱序预留
- `is_master`/`is_active`/`protocol`/`reset_active_low`/`custom_code` 字段
- pragma custom 注入 + merge + banner + clean + semantic check + gate
- env/bench 同步到 master/slave（派生 `seq_item_type`/`config_type`/`sequence_type`）
- env 切 UVMF 风格（sb_type/trans_type + analysis_components + tlm_connections）
- tool_uvmtestgen（xlsx → test case）
- 示例 YAML 5 件套 + testpoint xlsx + 全量生成到 `tool_uvm/generated/`

---

## 八、下一步（按优先级）

> 本会话已完成：golden 库接 model agent 的「未验证当真实」bug 修复（未验证 → 诚实占位）、
> README 已知问题同步、L5/audit 复核（已实现，非骨架/非最薄）。

1. **黄金模型 EDA 入库验证**（有 QuestaSim 时）：`scripts/model_library_verify.py` 盖章 5 个黄金模型
   （`verified=false` → `true`），使 model agent 自动产出真实参考模型、audit 通过 model_real 门禁。
   这是闭环跑通签核的最后一块（依赖 EDA，本环境无法执行）。
2. **全链路 e2e 验收**（有 QuestaSim 时）：`scripts/eda_verify_all.py` 一键验收。
3. **git 整理**：大量删除（testcase_tools/tool_testgen/tool_testrun/旧 md）未提交，需分批。
