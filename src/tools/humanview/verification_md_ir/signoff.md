# {{ module }} 验证签核清单（Verification Signoff Checklist）

> 模块版本：`{{ version }}` | Run：`{{ run_id }}` | 签核日期：`{{ date }}`
> 结论：`{{ verdict }}` | hard_ok：`{{ hard_ok }}`
> 数据来源：`report.json`、`coverage/gates.json`、`status/authority_diff.json`、
> `contract/contract_manifest.json`、`evidence/ledger.jsonl`、`signoff_evidence/`

**硬规则**：任一 `blocker` 未关闭 → **不得签核**。所有 `Pass` 必须能指向证据文件，
不接受"口头确认"或"应该没问题"。

---

## 1. 输入与文档

| 编号 | 检查项 | 验收标准 | 状态 | 负责人 | 日期 | 证据 |
|---|---|---|---|---|---|---|
| 1.1 | 设计规格书已冻结 | `specs/{{ module }}/{{ module }}_spec.md` 版本已确认 | {{ doc_spec }} | | | `{{ spec_path }}` |
| 1.2 | casemodel 已确认 | `specs/{{ module }}/casemodel.yaml` 可加载、无 schema 错误 | {{ doc_casemodel }} | | | `coverage/case_ir.json` |
| 1.3 | 业务用例与绑定表一致 | xlsx 投影 CASE 数 = `case_ir.counts.xlsx`；绑定缺口已清零 | {{ doc_bindings }} | | | `specs/{{ module }}/case_bindings.yaml` |
| 1.4 | 验证计划已批准 | `plan.md` 版本 `{{ plan_version }}` | {{ doc_plan }} | | | `plan.md` |
| 1.5 | 验证报告已发布 | `report.md` 结论为 `{{ verdict }}` | {{ doc_report }} | | | `report.md` |

---

## 2. 契约与模型

| 编号 | 检查项 | 验收标准 | 状态 | 负责人 | 日期 | 证据 |
|---|---|---|---|---|---|---|
| 2.1 | 契约已冻结 | `contract/contract_manifest.json` 的 `contract_hash` 与账本锚点一致 | {{ contract_frozen }} | | | `contract/contract_manifest.json` |
| 2.2 | 契约锚点存在 | `evidence/ledger.jsonl` 有 `contract_anchor`，且 `case_ir_sha256` 一致 | {{ contract_anchor }} | | | `evidence/ledger.jsonl` |
| 2.3 | 无 stale 证据 | `case_cov` 中 `error=stale_contract` 的数量 = 0 | {{ stale_evidence }} | | | `coverage/case_cov/**` |
| 2.4 | 引用闭合 | `case_closure.json` 的 `unknown_dimension` / `checker_without_tp` = 0 | {{ case_closure }} | | | `coverage/case_closure.json` |
| 2.5 | 参考模型可用 | 有真实 pred / reference model；`MODEL_UNAVAILABLE` 已按策略批准或不存在 | {{ model_ok }} | | | `model/`、`util_comp.yaml` |
| 2.6 | Pred 接线完整 | 进方向 AP → pred.in_export；pred.out_port → scb.expected；出方向 AP → scb.actual | {{ pred_wired }} | | | `inputs/yaml/uvm/env.yaml` |

---

## 3. 回归测试

| 编号 | 检查项 | 验收标准 | 状态 | 负责人 | 日期 | 证据 |
|---|---|---|---|---|---|---|
| 3.1 | 签核回归已冻结 | 回归清单 / seed 范围已冻结，不再改动 | {{ reg_frozen }} | | | `inputs/yaml/uvm/regression.yaml` |
| 3.2 | 连续通过 | 连续 `{{ n }}` 次 nightly / 签核回归 100% 通过 | {{ reg_stable }} | | | `regression_stages.json` |
| 3.3 | 无假 pass | `ERROR_PATTERN` 未被 `UVM_ERROR=0` 掩盖；无 `INVTST` / 超时静默通过 | {{ reg_no_false_pass }} | | | `regression_run/**/sim_vsim.log` |
| 3.4 | 失败已归因 | 所有失败已分类：DUT / TB / 环境 / flaky，且有关闭或 waiver | {{ reg_triage }} | | | `status/worklist.json` |

---

## 4. 覆盖率

| 编号 | 检查项 | 验收标准 | 状态 | 负责人 | 日期 | 证据 |
|---|---|---|---|---|---|---|
| 4.1 | 功能覆盖率 | 达到 `{{ target }}%`；闭合分母 = `required − waived − ignored` | {{ cov_functional }} | | | `sim/coverage/coverage_result.json` |
| 4.2 | 断言覆盖率 | 所有 SVA 非 vacuous（`cover_property_hit > 0`） | {{ cov_sva }} | | | `coverage/tp_cov_evidence.json` |
| 4.3 | SCB / Checker | `mismatched=0`；聚合证据与逐条证据分开标注（`evidence_kind`） | {{ cov_scb }} | | | `coverage/case_cov/**` |
| 4.4 | CELL 矩阵 | 无 red CELL；yellow 均有原因与处置 | {{ cov_cell }} | | | `coverage/cell_matrix.json` |
| 4.5 | 缺口已闭环 | `coverage_holes.json` 内 `stimulus_gap` / `signoff_gap` 均已处理或 waiver | {{ cov_holes }} | | | `coverage/coverage_holes.json` |
| 4.6 | 覆盖率未回退 | 相对基线 `functional_pct` 未下降 | {{ cov_delta }} | | | `docs/engineering_metrics.json` |

---

## 5. 证据链与对账

| 编号 | 检查项 | 验收标准 | 状态 | 负责人 | 日期 | 证据 |
|---|---|---|---|---|---|---|
| 5.1 | 状态权威对账 | `authority_diff.json` case/tp 差异 = 0 | {{ authority_diff }} | | | `status/authority_diff.json` |
| 5.2 | TP 影子对账 | `tp_shadow.json` mismatched = 0 | {{ tp_shadow }} | | | `status/tp_shadow.json` |
| 5.3 | 账本哈希链 | `ledger.verify_chain.ok = true`；无断链/篡改 | {{ ledger_ok }} | | | `evidence/ledger.jsonl` |
| 5.4 | EVD 完整 | 所有签核 TP 都有 `evd_id` 且能回溯到 `task@seed` | {{ evd_ok }} | | | `coverage/evd.json` |
| 5.5 | 证据包可校验 | `signoff_evidence/manifest.json` 逐文件 sha256 + `package_hash` 校验通过 | {{ package_ok }} | | | `signoff_evidence/` |
| 5.6 | 离线 replay | `evidence replay <pkg>` 重算三态与在线一致 | {{ replay_ok }} | | | `signoff_evidence/replay/replay.py` |

---

## 6. 门禁 / 豁免 / 风险

| 编号 | 检查项 | 验收标准 | 状态 | 负责人 | 日期 | 证据 |
|---|---|---|---|---|---|---|
| 6.1 | CASE Gate | `gates.json` blocker = 0 | {{ gates_ok }} | | | `coverage/gates.json` |
| 6.2 | 绑定门禁 | `case_without_binding` = 0 | {{ gate_binding }} | | | `coverage/gates.json` |
| 6.3 | Waiver 完整 | 每条 waiver 有 `owner/approver/reason/expires`；无过期 | {{ waiver_ok }} | | | `coverage/case_ir.json#waivers` |
| 6.4 | 质量门 | `verification_quality.json` 五维状态符合策略 | {{ quality_ok }} | | | `docs/verification_quality.json` |
| 6.5 | 剩余风险 | 所有未关闭风险已评审，并有书面处置 | {{ risk_ok }} | | | `caveats.json` |

---

## 7. 签核

> 以下签名表示：本人已核对上述条目，并对本条目的证据与结论负责。

| 角色 | 姓名 | 结论 | 签名 | 日期 |
|---|---|---|---|---|
| 设计负责人 | | {{ sign_design }} | | |
| 验证负责人 | | {{ sign_verify }} | | |
| 架构师 | | {{ sign_arch }} | | |
| 项目经理 | | {{ sign_pm }} | | |

**最终结论**：`{{ verdict }}`（{{ verdict_meaning }}）

**附**：
- 验证报告：`report.md`
- 验证计划：`plan.md`
- 证据包：`signoff_evidence/`（`manifest.json` / `replay/`）
