# {{ module }} 验证计划差距审计报告

> **审计对象**：`{{ plan_doc }}`（v{{ plan_version }}）
> **DUT 范围**：`{{ rtl_scope }}`
> **审计方法**：{{ audit_method }}
> **发布日期**：`{{ date }}`
> **作者**：{{ author }}

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| {{ plan_version }} | {{ date }} | {{ author }} | {{ change_note }} |

---

## 0. 摘要

{{ audit_summary }}

| 模块组 | Gap 数 | 对应原计划章节 |
|--------|-------:|----------------|
| {{ group.name }} | {{ group.gap_count }} | {{ group.plan_section }} |
| **合计** | **{{ total_gaps }}** | |

### 0.1 P0 关键发现（{{ p0_count }} 条须立即合入计划与设计 review）

| Gap ID | 模块 / 文件 | 未覆盖行为 | 影响 | 建议动作 |
|---|---|---|---|---|
| {{ gap.id }} | `{{ gap.file }}` | {{ gap.behavior }} | {{ gap.impact }} | {{ gap.action }} |

### 0.2 报告组织

{{ report_organization }}

---

## 1. {{ group_1.name }} Gaps（{{ group_1.req_range }} 修订）

### 1.1 {{ sub_1_1.name }}

| Gap ID | 模块 / 文件 | 未覆盖行为 | 原计划章节 | 优先级 | 建议（feature / coverage / assertion / test） |
|---|---|---|---|---|---|
| {{ gap.id }} | `{{ gap.file }}` | {{ gap.behavior }} | {{ gap.plan_section }} | {{ gap.priority }} | {{ gap.suggestion }} |

### 1.2 {{ sub_1_2.name }}

| Gap ID | 模块 / 文件 | 未覆盖行为 | 原计划章节 | 优先级 | 建议 |
|---|---|---|---|---|---|
| {{ gap.id }} | `{{ gap.file }}` | {{ gap.behavior }} | {{ gap.plan_section }} | {{ gap.priority }} | {{ gap.suggestion }} |

---

## 2. {{ group_2.name }} Gaps（{{ group_2.req_range }} 修订）

| Gap ID | 模块 / 文件 | 未覆盖行为 | 原计划章节 | 优先级 | 建议 |
|---|---|---|---|---|---|
| {{ gap.id }} | `{{ gap.file }}` | {{ gap.behavior }} | {{ gap.plan_section }} | {{ gap.priority }} | {{ gap.suggestion }} |

---

## 3. {{ group_3.name }} Gaps（{{ group_3.req_range }} 修订）

| Gap ID | 模块 / 文件 | 未覆盖行为 | 原计划章节 | 优先级 | 建议 |
|---|---|---|---|---|---|
| {{ gap.id }} | `{{ gap.file }}` | {{ gap.behavior }} | {{ gap.plan_section }} | {{ gap.priority }} | {{ gap.suggestion }} |

---

## 4. {{ group_4.name }} Gaps（{{ group_4.req_range }} 修订）

| Gap ID | 模块 / 文件 | 未覆盖行为 | 原计划章节 | 优先级 | 建议 |
|---|---|---|---|---|---|
| {{ gap.id }} | `{{ gap.file }}` | {{ gap.behavior }} | {{ gap.plan_section }} | {{ gap.priority }} | {{ gap.suggestion }} |

---

## 5. {{ group_5.name }} Gaps（{{ group_5.req_range }} 修订）

| Gap ID | 模块 / 文件 | 未覆盖行为 | 原计划章节 | 优先级 | 建议 |
|---|---|---|---|---|---|
| {{ gap.id }} | `{{ gap.file }}` | {{ gap.behavior }} | {{ gap.plan_section }} | {{ gap.priority }} | {{ gap.suggestion }} |

---

## 6. 设计 Review 建议清单

| 编号 | 建议 | 触发依据（Gap ID） | 责任方 | 状态 |
|---|---|---|---|---|
| R-{{ n }} | {{ review_suggestion }} | {{ gap_ids }} | {{ owner }} | {{ status }} |

---

## 7. 后续动作

1. 把 P0 gap 合入 `{{ plan_doc }}` 的 Feature List / Coverage Plan。
2. 把 gap 转成 `case_bindings.yaml` 的 `dimensions` / `cells` / `tests`。
3. 在 `casemodel.yaml` 补对应维度 / bin / cross / assertion。
4. 重新生成 `case_ir.json` → `contract/`，由 Case Gate 验证缺口是否闭合。
5. 在验证报告的「未覆盖项」章节逐条标记 `closed / waived / rejected`。
