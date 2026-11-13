# {{ module }} 验证计划（Verification Plan）

> 文档版本：`{{ plan_version }}` | 基线日期：`{{ date }}`
> 数据来源：`specs/{{ module }}/{{ module }}_spec.md`、`specs/{{ module }}/casemodel.yaml`、
> `specs/{{ module }}/case_bindings.yaml`、run 的 `coverage/case_ir.json` / `coverage/coverage_plan.yaml`

---

## 1. 引言

### 1.1 文档目的

本文档定义 `{{ module }}` 的功能验证计划：**测什么、怎么测、怎么量、何时可签核**。
目标读者：验证工程师、设计工程师、架构师、项目经理。

### 1.2 项目背景

- DUT：`{{ module }}`（{{ object_cn }}）
- 对象代号：`{{ object_code }}`
- 版本：`{{ version }}`
- 说明：{{ description }}

### 1.3 参考文档

| 文档 | 位置 |
|---|---|
| 设计规格书 | `specs/{{ module }}/{{ module }}_spec.md` |
| case 模型（怎么测/怎么量） | `specs/{{ module }}/casemodel.yaml` |
| 业务测试点表（该测什么，可选） | `{{ case_source_xlsx or "—" }}` |
| case 绑定表 | `specs/{{ module }}/case_bindings.yaml` |
| 签核策略 | `specs/{{ module }}/signoff_policy.yaml` |

---

## 2. 设计概述

### 2.1 功能描述

{{ spec_overview }}

### 2.2 接口与时钟/复位

| 接口 | 方向 | 说明 |
|---|---|---|
| {{ iface.name }} | {{ iface.direction }} | {{ iface.description }} |

- 时钟：`{{ clock }}`（{{ clock_domain }}）
- 复位：`{{ reset }}`（{{ reset_polarity }}）

### 2.3 配置空间

{{ config_space | default("本设计没有独立配置空间") }}

---

## 3. 验证策略与方法论

- **主策略**：覆盖率驱动验证（CDV）+ 契约驱动签核
- **激励**：约束随机 + 定向批次 + 边界/错误注入
- **裁决**：`derive()` 确定性判定，不接受 LLM 自证
- **契约**：`case_ir.json` → `contract/` → `obligations.json`，证据只对当前 `contract_hash` 有效
- **工具**：{{ simulator }} / UVM {{ uvm_version }} / `vagent` 流水线

---

## 4. 验证环境架构

| 组件 | 作用 | 生成/来源 |
|---|---|---|
| In Agent | 驱动 DUT 输入，monitor 产出 `{{ in_seq_item }}` | `agents/{{ in_agent }}_agent/` |
| Out Agent | 采样 DUT 输出，monitor 产出 `{{ out_seq_item }}` | `agents/{{ out_agent }}_agent/` |
| **Pred** | 参考模型：输入事务 → 期望输出事务 | `inputs/yaml/uvm/util_comp.yaml` |
| **Scoreboard** | expected（pred） vs actual（out monitor） | `in_order_scoreboard` |
| env_cov | covergroup / cross 采样 | `env/{{ module }}_env_coverage.sv` |
| DUT Checker | 逐拍规则检查（**不是事务 scoreboard**） | `inputs/yaml/uvm/env_cov_bins.yaml#dut_checker` |
| Coverage IF | bind 进 DUT 的覆盖率接口 | `coverage/{{ module }}_cov_if.sv` |

**接线（必须）**

```text
{{ in_agent }}_agent_ap    → {{ module }}_pred.in_export
{{ module }}_pred.out_port → {{ module }}_scb.expected_export
{{ out_agent }}_agent_ap   → {{ module }}_scb.actual_export
```

---

## 5. 待验证功能点（Features / CASE / TP）

### 5.1 业务用例（xlsx 投影，`source=xlsx`）

| CASE ID | 名称 | 分类路径 | 绑定维度 | 绑定测试 | 优先级 | 状态 |
|---|---|---|---|---|---|---|
| {{ case.id }} | {{ case.name }} | {{ case.category_path }} | {{ case.dimensions }} | {{ case.tests }} | {{ case.priority }} | {{ case.status }} |

### 5.2 覆盖维度 → TP

| 维度 | 取值/bin | TP 数 | 实现方式 | 覆盖率目标 |
|---|---|---:|---|---:|
| {{ dim.key }} | {{ dim.bins }} | {{ dim.tp_count }} | {{ dim.realization }} | {{ dim.goal }}% |

### 5.3 绑定缺口（必须清零）

- `case_without_binding`：{{ unbound_cases }}
- 未绑定维度：{{ unbound_dimensions }}

---

## 6. 测试用例计划

### 6.1 属性测试（一条 = 一个 UVM_TEST = 一个维度取值）

| 维度 | 取值 | 测试类 | 分级 | 种子 |
|---|---|---|---|---|
| {{ batch.dimension }} | {{ batch.value }} | {{ batch.test }} | {{ batch.priority }} | {{ batch.seeds }} |

### 6.2 批次测试（一条 = 一个批次/专题）

| 批次 | 专题 | 维度 | 方法 | 策略 | 优先级 |
|---|---|---|---|---|---|
| {{ batch.name }} | {{ batch.theme }} | {{ batch.dimensions }} | {{ batch.method }} | {{ batch.policy }} | {{ batch.priority }} |

---

## 7. 覆盖率计划

| 覆盖类型 | 目标 | 说明 |
|---|---:|---|
| 功能覆盖率（functional） | {{ target }}% | covergroup / coverpoint / cross |
| 断言覆盖率 | 100% | 每条断言至少被触发一次（非 vacuous） |
| SCB / DUT checker | 100% | `mismatched=0`，且证据粒度明确 |
| 代码覆盖率 | {{ code_target }}% | 行 / 分支 / 条件 / FSM |

**闭合分母**：`required − waived − ignored`；`waived` 必须来自带审批人的 waiver。
**排除**：`ignore_bins` 与 waiver 分开审计，不混用。

---

## 8. 回归测试策略

- 分级：`loopback → p0 → p1 → p2 → p3`
- 种子：批次声明 `count + explore`；属性测试按 TP 种子
- 最小重跑：`incremental/plan.json` → `worklist.impact_suggested`
- 失败处理：blocker 进 `gates.json`；缺口进 `coverage_holes.json`
- 通过标准：stage 100% 通过，无 UVM_ERROR/FATAL，无假 pass

---

## 9. 签核标准

- 契约：`contract_hash` 已冻结并锚定到账本
- 证据：所有义务 `PROVEN`，无 `stale_contract` 证据
- 覆盖：功能/断言/SCB 达到目标，所有缺口有 waiver 或已关闭
- 门禁：`gates.json` blocker = 0（含 `case_without_binding`）
- 对账：`status/authority_diff.json` 差异 = 0
- 回归：签核回归连续 {{ n }} 次 100% 通过
- 文档：本计划、验证报告、签核清单均已批准

---

## 10. 风险与规避

| 风险 | 影响 | 规避 |
|---|---|---|
| 没有真实 pred / reference model | scoreboard 无法判 | 无 pred 不生成 env；禁止 TODO 假比对 |
| `MODEL_UNAVAILABLE` | 缺少独立功能正确性检查 | 策略显式接受或补 reference model |
| 绑定表未填 | CASE 落不到执行实例 | `case_without_binding` blocker |
| 覆盖率 NA 滥用 | 分母被稀释 | waiver 必须有 owner/approver/reason/expires |
| 约束/契约变更 | 旧证据失效 | `stale_contract` 证据作废，不静默复用 |
