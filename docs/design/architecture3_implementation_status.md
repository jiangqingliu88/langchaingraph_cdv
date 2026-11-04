# Architecture 3.0 实施状态（已接主链）

> 日期：2026-11-04
> 目标：按 `new_architecture.md` 的 P0–P5 开工并**接到主链**。
> 原则：不建平行事实系统；不破坏现有主链；不绕过确定性门禁。

---

## 1. 能力域与落点

| 能力域 | 包 | 主链落点 | 产物 | 状态 |
|---|---|---|---|---|
| **P0 UVM IR-first** | `tools/generation/uvm_tools/generation/ir/ir_first.py` | `generators/tasks.py` 渲染入口 | `docs/ir_shadow_diff.json` | ✅ 切换开关已接到渲染；默认关闭 |
| **P1 Unified IR v3** | `layers/l3_decision/verification_ir/` | `verify/_write_testpoints` | `coverage/verification_ir.json`（含 D4 资源域） | ✅ 已接线 |
| **P2 Resource Model** | `layers/l3_decision/resource_model/` + `tools/.../generation/resource_checker.py` | `verify` 渲染前落盘；`EnvironmentRenderTask` 生成 checker | `coverage/resource_model.json`、`resource_scenarios.json`；`env/<env>_resource_checker.sv` | ✅ 已接线（有声明才生成） |
| **P3 Attribution v2** | `layers/l3_decision/attribution/` + `evidence/per_test_bins.py` | 证据流水线 `per_test_bins` → `attribution_v2` | `coverage/per_test_bins.json`、`attribution_v2.json`、`per_test_v2/*.json` | ✅ 已接线（无 vcover 时明确 unavailable） |
| **P4 Obligation Engine** | `layers/l3_decision/obligation/` | `audit/_build_architecture_v2` | `docs/obligations_v3.json` | ✅ 已接线 |
| **P5 Autonomous Closure** | `layers/l5_evolution/closure/` | `audit/_build_architecture_v2` | `status/closure_plan.json` | ✅ 已接线（无 RL） |

---

## 2. 主链顺序（新增部分加粗）

```text
verify
  case_model → TP IR → **Resource Model** → **StimulusPlan（含资源场景）**
             → Case IR → **Unified IR v3（D4 复用资源模型）** → contract build
             → env 渲染（`SIGNOFFAI_UVM_IR_FIRST=on` 时 IR 覆盖渲染 ctx）
  ↓
collect_real_coverage
  case_cov → tp_matrix → **per_test_bins（逐 test ucdb → vcover）**
           → **attribution_v2 (EXACT/WEAK/UNKNOWN)**
           → tp_evidence → evd → cell_matrix → case_view → gates
           → os_shadow → os_tp_shadow → os_authority → os_seeds
           → coverage_holes
  ↓
audit
  provenance / attribution / metrics / quality
  → **obligations_v3（PROVEN/PARTIAL/OPEN/FAILED/BLOCKED/UNKNOWN）**
  → **closure_plan（确定性动作排序，硬失败优先）**
  → architecture_v2 → 签核包
```

证据包已收录：`verification_ir.json`、`resource_model.json`、
`resource_scenarios.json`、`attribution_v2.json`、`obligations_v3.json`、
`closure_plan.json`。

---

## 3. 已验证（非 pytest）

```text
compileall: ok
import:     ok
smoke（真实 run 产物）:
  P1 IR:        IR-efb6151b69c9 / relations 238 / TP 70 / validate ok
  P2 Resource:  overlap=PARTIAL → checker_must_report_forbidden_overlap；
                agent+watch → <env>_resource_checker.sv（imp/write/connect 均渲染）
  P3 生产端:    识别 274 个逐 test ucdb；本机无 vcover → 明确 unavailable；
                fake runner 下 5 test / 500 bins / truncated=269
  P3 Attrib:    per_seed → 2 sidecar / EXACT 2 / identity 1.0 / quality True
  P4 Obligation:58 条（OPEN 34 / UNKNOWN 24 / FAILED 0）
  P5 Closure:   20 条动作 / continue=True
evidence pipeline: tp_matrix ok / attribution_v2 ok
guard:      True | import debt 0 | line/complexity 0
```

---

## 3.1 证据闭环（A–F 已接线）

| 阶段 | 落点 | 产物 |
|---|---|---|
| A 意图与 Claim | `l3_decision/intent/`、`l3_decision/claims/` | `coverage/intents.json`、`coverage/claims.json` |
| B 证据类别 | `verification_os.contract_model.Fact` 新字段；`derive._by_type` 过滤 | ledger 事实带 `fact_class / producer_class / claim_ids / actor` |
| B 解释与上下文 | `l4_memory/evidence_store/` | `status/interpretations.json`、`status/next_iteration_context.json` |
| C 控制平面 | `l3_decision/control_plane/` + `config/control_plane.yaml` | `docs/action_audit.jsonl`（每次工具调用一行） |
| D 门禁读数 | `case_view/gates.py`、`audit/helpers._apply_evidence_gate` | warning（默认 report）；`SIGNOFFAI_EVIDENCE_GATE=block` 才硬失败 |
| E Agent 输出 | Interpretation 默认 `HYPOTHESIS`；LLM 审计行带 `fact_class=HYPOTHESIS / producer_class=agent / claim_id` | agent 结论不能直接参与 derive |
| 证据源适配器 | `l1_infrastructure/evidence_providers.py` | `docs/evidence_sources.json`：sim/regression/debug 真实源；formal/lint/cdc/rdc/emulation **显式占位**；`proof_core_coverage=null` |
| P0 就绪读数 | `ir_first.write_audit()` + `EnvironmentRenderTask` | `docs/ir_first_audit.json`（多环境合并，默认不切换渲染） |
| 资源 checker 计划 | `EnvironmentRenderTask._write_resource_checker_plan` | `docs/resource_checker.json`（含 unsupported 操作） |
| F 闭环反馈 | `status/next_iteration_context.json` | 未决义务 + 覆盖缺口 + 被拒解释 + 已批动作 |

实测（基线 run 拷贝）：

```text
Intent 13 条（候选 13） / Claim 74 条（CANDIDATE 74）
evidence_index: ledger OBSERVED 388 / claims with_evidence 0
interpretations: 1 项 / 20 insights / 20 plan_updates
next_context: open_obligations 50 / claims_without_evidence 50
gates: PASS（claim 规则在 CONFIRMED 无证据时才告警）
control_plane: tool:vlog → AUTO/MEDIUM；edit_ledger → FORBIDDEN；未知动作 → FORBIDDEN
```

---

## 4. 语义约定（接线上必须保持）

1. **身份不另起**：`tp_id/case_id/tst_id/evd_id/cell_id` 沿用现有体系。
2. **不建平行账本**：obligation / attribution 复用 `evidence/ledger.jsonl`、
   `coverage/attribution.json`、现有 `derive()`。
3. **FAILED ≠ UNKNOWN**：显式违规（`fail>0` / `mismatched>0` / `status=FAIL`）
   → `FAILED`；没有可信判据 → `UNKNOWN`；没执行 → `OPEN`。
4. **资源不编造**：没有 `resources.yaml` 时 `resource_model` 不落盘。
5. **硬失败优先**：closure 只做确定性排序，AI 建议不能覆盖门禁。

---

## 5. 下一步（仍未做）

| 项 | 前置条件 |
|---|---|
| P0 默认开启 IR-first | 真实工程上跑出 `ir_shadow_diff=0` 且 golden 0 差异，再把默认值翻成 on |
| P3 生产端跑真机 | 在装 Questa 的环境上验证 `vcover report -cvg -details` 的逐 test 解析 |
| 资源 checker 编译验证 | `resources.yaml` 的 `watch` 表达式需按真实 seq_item 字段落地后跑一轮 vlog |
| P4/P5 进门禁 | 先观察若干轮 `obligations_v3` / `closure_plan` 读数稳定 |
| 证据闭环门禁转 block | 先观察 `claim_confirmed_without_evidence` / `unapproved_high_risk_action` 若干轮 |
| 占位适配器替换真实实现 | `evidence_providers.py` 的 formal/lint/cdc/rdc/emulation 目前是 **dummy**；工具接入后替换 provider 内部即可 |
| 形式 proof core coverage | 当前 `proof_core_coverage=null`；接证明器后按真实报告填值 |
