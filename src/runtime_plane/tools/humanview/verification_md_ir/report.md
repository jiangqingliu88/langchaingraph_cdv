# {{ module }} 验证报告（Verification Report）

> 文档版本：`Final` | 生成日期：`{{ date }}`
> Run：`{{ run_id }}` | RTL：`{{ rtl_version }}`
> 数据来源：`report.json`、`coverage/`、`status/`、`contract/`、`signoff_evidence/`

---

## 1. 执行摘要

- **总体结论**：`{{ verdict }}`（{{ verdict_meaning }}）
- **签核状态**：`{{ signoff_status }}` | hard_ok：`{{ hard_ok }}`

| 指标 | 目标 | 实际 | 状态 |
|---|---:|---:|---|
| 回归通过率 | 100% | {{ pass_rate }} | {{ pass_rate_status }} |
| 功能覆盖率 | {{ target }}% | {{ functional_pct }}% | {{ functional_status }} |
| CASE Gate blocker | 0 | {{ gate_blockers }} | {{ gate_status }} |
| 状态权威对账 | 0 差异 | {{ authority_diff }} | {{ authority_status }} |
| TP 影子对账 | 0 差异 | {{ tp_shadow_diff }} | {{ tp_shadow_status }} |

- **有效 caveat**：{{ effective_caveats }}

---

## 2. 项目与验证概述

| 项 | 值 |
|---|---|
| module | `{{ module }}` |
| run_id | `{{ run_id }}` |
| RTL 版本 | `{{ rtl_version }}` |
| contract_hash | `{{ contract_hash }}` |
| case_ir_sha256 | `{{ case_ir_sha }}` |
| 验证计划 | `plan.md`（本包） |

---

## 3. 回归测试结果

### 3.1 分级统计

| Stage | Total | Passed | Failed | Blocked at |
|---|---:|---:|---:|---|
| loopback | {{ s.total }} | {{ s.passed }} | {{ s.failed }} | {{ s.blocked_at }} |
| p0 | {{ s.total }} | {{ s.passed }} | {{ s.failed }} | {{ s.blocked_at }} |
| p1 | {{ s.total }} | {{ s.passed }} | {{ s.failed }} | {{ s.blocked_at }} |
| p2 | {{ s.total }} | {{ s.passed }} | {{ s.failed }} | {{ s.blocked_at }} |
| p3 | {{ s.total }} | {{ s.passed }} | {{ s.failed }} | {{ s.blocked_at }} |

### 3.2 最小重跑建议

- `status/worklist.json#items`：{{ worklist_items }}
- `impact_suggested`：{{ impact_tests }}（confidence={{ impact_confidence }}）
- skipped（无回归 test）：{{ worklist_skipped }}

---

## 4. 覆盖率分析

### 4.1 功能覆盖

| 覆盖组 | 目标 | 实际 | required | waived | ignored |
|---|---:|---:|---:|---:|---:|
| {{ group.name }} | {{ group.goal }}% | {{ group.pct }}% | {{ group.required }} | {{ group.waived }} | {{ group.ignored }} |

- 闭合分母：`required − waived − ignored`
- `coverage_holes.json`：{{ hole_counts }}

### 4.2 断言与 Checker

| 类型 | 总数 | 通过 | 未触发/vacuous | 失败 |
|---|---:|---:|---:|---:|
| SVA | {{ sva_total }} | {{ sva_pass }} | {{ sva_vacuous }} | {{ sva_fail }} |
| SCB（事务比对） | {{ scb_total }} | {{ scb_pass }} | {{ scb_not_exec }} | {{ scb_fail }} |
| DUT 规则检查 | {{ dut_total }} | {{ dut_pass }} | {{ dut_not_exec }} | {{ dut_fail }} |

> **注意**：`[SCB_DUT]` / `[SCB SB-*]` 如果来自 `env_cov` 的 DUT checker，
> 它属于**逐拍规则检查**，不是事务级 scoreboard，报告中必须标
> `evidence_kind=dut_rule_checker`。

### 4.3 CELL 矩阵

| CELL | 颜色 | 证据层 | 原因 |
|---|---|---|---|
| {{ cell.cell_id }} | {{ cell.color }} | {{ cell.layers }} | {{ cell.reasons }} |

---

## 5. 用例证据（CASE / TST / EVD）

- CASE 数：{{ case_count }}（声明 {{ declared }} / 合成 {{ synthesized }} / xlsx {{ xlsx }}）
- TST 实例：{{ tst_count }}（`test @ seed`）
- EVD：{{ evd_count }}
- CELL：{{ cell_count }}（green {{ green }} / yellow {{ yellow }} / red {{ red }} / na {{ na }}）

| CASE | 执行次数 | 功能覆盖 | SVA | Scoreboard/Checker | PATH | 结论 |
|---|---:|---|---|---|---|---|
| {{ case.id }} | {{ case.runs }} | {{ case.coverage }} | {{ case.sva }} | {{ case.scb }} | {{ case.path }} | {{ case.status }} |

---

## 6. 缺口与缺陷

### 6.1 覆盖缺口（`coverage_holes.json`）

| TP | 维度/bin | 动作 | owner_test | seeds |
|---|---|---|---|---|
| {{ hole.tp_id }} | {{ hole.dimension }}/{{ hole.bin }} | {{ hole.action }} | {{ hole.owner_test }} | {{ hole.seeds }} |

### 6.2 门禁 blocker（`gates.json`）

| 规则 | 目标 | 级别 | 说明 |
|---|---|---|---|
| {{ gate.rule }} | {{ gate.target }} | {{ gate.level }} | {{ gate.message }} |

### 6.3 未关闭事项

- caveats：{{ caveats }}
- 豁免：{{ waivers }}
- legacy / stale：{{ legacy }}

---

## 7. 结论与建议

- **是否满足签核标准**：{{ meets_criteria }}
- **建议**：{{ recommendation }}
- **经验教训**：{{ lessons }}
