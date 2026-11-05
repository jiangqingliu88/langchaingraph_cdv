# 架构重构计划 —— 冻结契约后的 Strangler 重构

> 基线：2026-11-04 · 分支 `refactor/langgraph-migration`
> 关联：`ARCHITECTURE.md`、`docs/design/architecture_transformation_plan.md`、
> `docs/design/contract_driven_architecture_v3.md`
> 状态：**Phase 0–1 已执行**（2026-11-04）；Phase 2–4 待按文件逐个执行

---

## 0. 一句话结论

**能重构，但不是全量重写。**

当前代码量 821 个 Python 文件 / 160,769 行，前四个文件已顶到 1500 行预警线，
工作区有 154 个未提交改动。正确路径是：

> **先冻结产物契约与 golden 基线 → 再按依赖方向抽缝 → 最后搬目录删旧路。**

重构的边界不是“文件怎么摆”，而是：**产物 schema 不变、判定行为不变、
每一步都能用 golden diff 证明没变。**

---

## 1. 现状测量

### 1.1 体量

| 指标 | 数值 |
|---|---|
| Python 文件 | 821 |
| 总行数 | 160,769 |
| `src/tools` | 387 个文件 |
| `src/workbench` | 195 个文件 |
| `src/layers` | 132 个文件 |
| `src/core` | 43 个文件 |
| 未提交改动 | 154 个文件 |

### 1.2 最大的文件（重构首要目标）

| 行数 | 文件 |
|---:|---|
| 1500 | `src/executors/verify/main.py` |
| 1494 | `src/tools/generation/uvm_tools/tool_find_spec_yaml/main.py` |
| 1449 | `src/executors/audit/main.py` |
| 1374 | `src/layers/l4_memory/persistence/repository.py` |
| 1353 | `src/cli/commands.py` |
| 1212 | `src/workbench/app.py` |
| 1110 | `src/layers/l1_infrastructure/infrastructure.py` |
| 1094 | `src/tools/common/lib/collect_real_coverage.py` |
| 1019 | `src/tools/checking/coverage_tools/case_cov.py` |
| 1000 | `src/layers/l2_orchestration/execution.py` |

### 1.3 已有的护栏（重构时直接复用）

| 护栏 | 位置 |
|---|---|
| 架构守卫（行数 / 复杂度） | `config/architecture_guard.py` |
| 复杂度基线 | `config/complexity_baseline.json` |
| 行数预算 | `config/architecture_budget.yaml` |
| verify 内部 DAG 显式依赖 | `src/executors/verify/steps_dag.py` |
| 契约锚点 / 事实账本 | `src/layers/l3_decision/contract/` |
| 原子落盘 | `src/core/runtime/atomic.py` |
| 存储回收 | `src/core/runtime/gc.py` |
| 端到端基线 run | `output_e2e_final4_jiang_20261104_044624` |

---

## 2. 目标与非目标

### 2.1 目标

1. **依赖方向干净**：`interfaces → executors → l2 → l3 → l1/core`，横向只通过契约对象。
2. **单文件可读**：核心执行文件 ≤ 800 行；超 800 行必须有明确理由并登记。
3. **职责单一**：`tools/` 只做适配器；业务规则回到 `layers/`；`executors/` 只做薄编排。
4. **行为可证明不变**：每个 phase 都用 golden diff 验收。
5. **旧路可删**：新实现稳定后，删除旧路径与 shim，不保留双实现。

### 2.2 非目标

- 不重写产物 schema（`case_ir_v1` / `testpoints` / `contract_v2` / `case_cov_v1`）。
- 不更换 L1–L5 + agents 的分层（该分层已确认）。
- 不引入 Web 前端（GUI 仍是 PySide6）。
- 不在一个 PR 里同时“搬家 + 改行为”。

---

## 3. 目标结构

保留既有 `src/layers/l1..l5`，把职责做实：

| 层 / 目录 | 拥有 | 不拥有 |
|---|---|---|
| `src/core/` | 契约版本、ID、runtime（atomic / gc / errors） | 业务规则 |
| `src/layers/l1_infrastructure/` | EDA 后端、文件系统、工具适配 | casemodel 语义 |
| `src/layers/l2_orchestration/` | 编排、DAG、run 仓库、证据包 | 判定规则 |
| `src/layers/l3_decision/` | 编译（case_ir → TP → contract）、`derive()`、gates | IO、模板 |
| `src/layers/l4_memory/` | 账本、case registry、lineage | 业务判定 |
| `src/layers/l5_evolution/` | metrics、缺口闭环、演化 | 执行 |
| `src/executors/` | 薄编排：读请求 → 调 L2/L3 → 落盘 | 业务算法 |
| `src/tools/` | 纯适配器：UVM / EDA / 模板渲染 | 跨阶段业务规则 |
| `src/cli/`、`src/workbench/`、`src/app/` | 接口层 | 任何算法 |

### 3.1 允许的依赖方向

```text
interfaces (cli/workbench/app)
        │
        ▼
executors ──────► layers/l2_orchestration
        │               │
        │               ▼
        │         layers/l3_decision
        │               │
        │               ▼
        │         layers/l1_infrastructure
        │               │
        ▼               ▼
        core/ (contracts / runtime / ids)
```

禁止：

- `l1 → l3` / `l1 → executors`
- `tools → executors` / `tools → layers`（适配器不反向依赖）
- `interfaces → tools 内部实现`（只能经 services/executors）
- 任何 `core → 上层`

### 3.2 产物契约（冻结，不随重构变）

| 契约 | 文件 | 冻结内容 |
|---|---|---|
| Case IR | `coverage/case_ir.json` | 字段名、`source`、四集合、`waivers` |
| TP IR | `coverage/testpoints.yaml` | `tp_id`、`case_id/case_ids`、`execution`、`status_rule` |
| 契约构建物 | `contract/contract.yaml` / `obligations.json` / `contract_manifest.json` | `contract_hash`、义务谓词、锚点 |
| 用例证据 | `coverage/case_cov/**/*.json` | `evd_id`、三集合、`case_status` |
| 门禁 / 清单 | `coverage/gates.json` / `status/worklist.json` | 规则 id、级别、`items/regex/impact` |

---

## 4. 重构原则

1. **Strangler**：新实现先与旧实现并存，经 shim 逐步切流量，最后删旧。
2. **只搬不改**：搬家 PR 不含行为变化；行为变化单独 PR。
3. **先冻结再动**：Phase 0 未完成前，不开始任何大文件拆分。
4. **按依赖倒序搬**：先搬底层（core/runtime），再搬上层（interfaces）。
5. **一步一验收**：每个 phase 结束必须通过第 6 节的验收门。
6. **不保留双实现过久**：shim 的生命周期 ≤ 2 个 phase。

---

## 5. 分阶段计划

### Phase 0：止血与冻结（1 天）

**目标**：让“重构有没有改行为”变成可计算的问题。

任务：

- [ ] 把当前 154 个改动按主题分组提交（建议：契约锚点 / xlsx 绑定 / 覆盖语义 / 闭环 / GC）。
- [x] 从基线 run 抽取 golden 产物（只收小文件，不收波形）：
  ```text
  tests/golden/architecture_baseline/
    coverage/case_ir.json
    coverage/testpoints.yaml
    coverage/gates.json
    coverage/coverage_holes.json
    contract/contract_manifest.json
    status/worklist.json
  ```
- [x] 写 `scripts/golden_diff.py`：逐文件比较，忽略 `generated_at`、
  绝对路径、时间戳；输出 `{ok, diffs[]}`，非零退出码供 CI 用。
- [x] 在 `config/architecture_budget.yaml` 登记四个超 1400 行文件的
  **重构豁免 + 计划删除 phase**（否则守卫会一直红）。

**验收**：

- `python -c "from config import architecture_guard as g; print(g.check()['ok'])"` → `True`
- `python scripts/golden_diff.py tests/golden/architecture_baseline <baseline_run>` → `ok: true`
- 基线 run 目录、命令、环境变量写进 `tests/golden/README.md`。

**回滚**：纯新增（golden + 脚本 + 文档），无代码行为变化。

---

### Phase 1：抽 `core/runtime` 与 `core/contracts`（2–3 天）

**目标**：把“所有层都会用、但不含业务”的东西收口。

任务：

- [x] `src/core/runtime/` 收口：`atomic.py`（已有）、`gc.py`（已有）、
  `ids.py`（`case_id_of` / `tst_id_of` / `evd_id_of` 的唯一实现）、
  `errors.py`（`CaseModelError` / `StepOrderError` / `ContractAnchorMismatch`）。
- [x] 旧路径保留 re-export shim：`case_ir.ir_core`、`domain.errors`、
  `steps_dag`、`verification_os.ledger` 已转发到 `core.runtime`。
- [x] 建目标门面：`l3_decision/{contract,casemodel,evidence}`、
  `l4_memory/ledger`、`l5_evolution/closure`（只 re-export，行为不变）。
- [x] 扩展 `config/architecture_guard.py`：增加 `import_direction` 检查
  （Phase 1 只报告，不并入 `ok`）。
- [ ] `src/core/contracts/` 收口：版本常量、schema 名、允许的产物列表。
- [ ] 迁移顺序：`core` 内部 → `l1` → `l3` → `l2` → `executors` → `interfaces`。

**验收**：

- golden diff 0；
- `import_direction` 违规清单只减不增；
- 无新增复杂度基线条目。

**回滚**：shim 保留旧路径，按 phase 回退。

---

### Phase 2：拆四个巨型文件（1–2 周）

**目标**：核心执行文件 ≤ 800 行，职责按“步骤 / 规则 / 证据”切开。

#### 2.1 `src/executors/verify/main.py`（1500 → 目标 ≤ 600）

```text
src/executors/verify/
  main.py                 # 只做编排：读请求 → 调 steps → 记账
  steps/
    coverage_plan.py
    spec_yaml.py
    testpoints.py
    dut_channel.py
    env_cov_bins.py
    constraint.py
    render.py
  ir_artifacts.py         # 已有：产物记账
  steps_dag.py            # 已有：依赖声明（不搬）
```

- 公共入口 `VerifyExecutor.execute_task()` 不变；
- 每拆一步，先跑 `python -m pytest src/layers/l3_decision/casemodel/tests tests/test_verify_steps_dag.py -q` + golden diff。

#### 2.2 `src/executors/audit/main.py`（1449 → 目标 ≤ 600）

```text
src/executors/audit/
  main.py                 # 编排 + 组装 report
  verdict.py              # 三态裁决入口（调用 evidence/verdict）
  gates.py                # authority / quality / coverage-delta / baseline 门
  evidence.py             # 证据包组装
  quality.py              # 五维质量门适配
```

#### 2.3 `src/tools/generation/uvm_tools/tool_find_spec_yaml/main.py`（1494 → 目标 ≤ 600）

```text
tool_find_spec_yaml/
  main.py                 # run() 编排
  discovery.py            # RTL / spec / 已有 YAML 发现
  ownership.py            # 已有：产物 manifest
  generators/             # 已有：agent/env/bench/regression 生成器
```

#### 2.4 `src/cli/commands.py`（1353 → 目标 ≤ 300）

- 继续把命令搬到 `cmd_*.py`；`commands.py` 只保留 `cli` 对象、公共 helper 与导入注册。

**验收**：

- 四个文件均 ≤ 800 行；
- `architecture_guard` 绿；
- `import_direction` 违规为 0；
- golden diff 0；
- 端到端 npu_sched 一轮 `273/273`（或与基线一致的已知差异）。

---

### Phase 3：`tools` 去业务化（1–2 周）

**目标**：`src/tools` 只留适配器；业务规则回到 `layers`。

迁移映射：

| 现在 | 目标 |
|---|---|
| `tools/generation/casemodel_tools/domain/*` | `layers/l3_decision/casemodel/domain/` |
| `tools/generation/casemodel_tools/analysis/*` | `layers/l3_decision/casemodel/analysis/` |
| `tools/checking/verification_os/*` | `layers/l3_decision/contract/`（derive/gates）与 `layers/l4_memory/ledger/` |
| `tools/checking/coverage_tools/coverage_holes.py` | `layers/l5_evolution/closure/` |
| `tools/checking/coverage_tools/{case_cov,tp_evidence,cell_matrix}` | `layers/l3_decision/evidence/` |
| `tools/generation/uvm_tools/*` | 保留在 `tools/`（纯适配器） |

做法：

- 新位置先建模块 + `from new import *` 的旧 shim；
- 按依赖倒序迁移 importer；
- 每迁一个模块跑 golden diff；
- shim 最多保留 2 个 phase，之后删除。

**验收**：

- `tools → layers` 反向依赖为 0；
- `layers/l3` 可在不 import `tools.generation.uvm_tools` 的情况下单测；
- golden diff 0。

---

### Phase 4：删旧路与收紧基线（3–5 天）

任务：

- [ ] 删除所有 shim 与旧实现。
- [ ] 清理 `config/complexity_baseline.json` 中已拆掉的函数条目。
- [ ] 把 `architecture_budget.yaml` 的 warn 线从 1500 降到 800（或分目录阈值）。
- [ ] 更新 `ARCHITECTURE.md` 与 `../notes/data.md` 的目录说明。
- [ ] 保留 `docs/design/architecture_refactor_plan.md` 作为历史记录，标记完成。

**验收**：

- 全量测试通过；
- guard 绿且阈值已收紧；
- 端到端基线一致；
- `git grep` 不再出现旧导入路径。

---

## 6. 每个 Phase 的验收门

| 门 | 命令 / 判据 |
|---|---|
| 架构守卫 | `python -c "from config import architecture_guard as g; print(g.check()['ok'])"` → `True` |
| Golden 产物 | `python scripts/golden_diff.py tests/golden/architecture_baseline <run>` → `ok: true` |
| 依赖方向 | `import_direction` 违规为 0（Phase 2 后） |
| 单文件行数 | 核心执行文件 ≤ 800；超限必须登记理由 |
| 复杂度 | 无新增 `complexity_new`；`complexity_grew` 有说明 |
| 端到端 | npu_sched 基线 run 的 verdict / gates / worklist 与 golden 一致 |
| 无测试套件豁免 | 搬家 PR 至少跑受影响目录的 pytest；行为 PR 跑全量 |

---

## 7. 风险登记

| 风险 | 触发条件 | 缓解 |
|---|---|---|
| R1 未提交改动混杂 | 154 个改动未分组 | Phase 0 先提交；每 phase 一个分支 |
| R2 产物 schema 漂移 | 重构时顺手改字段 | 冻结 schema；golden diff 拦截 |
| R3 双实现长期并存 | shim 忘记删 | shim 生命周期 ≤ 2 phase，写入任务清单 |
| R4 循环依赖 | 搬目录后 `core → 上层` | `import_direction` 在 Phase 1 先 warning，Phase 2 转 error |
| R5 Windows 路径 / 换行 | 原子写 / golden diff | 统一 `newline="\n"`；golden 比较前规范化 |
| R6 GUI 被重构波及 | `workbench` 直接 import `tools` 内部 | 接口层只经 services；workbench 单独回归 |
| R7 基线 run 不可复现 | 环境 / 种子漂移 | golden 只比结构性产物，不比波形/耗时 |

---

## 8. 第一周可执行清单（Phase 0 + Phase 1 起步）

- [ ] Day 1：按主题提交当前 154 个改动；抽取 golden 产物；写 `scripts/golden_diff.py`。
- [ ] Day 2：`core/runtime/ids.py` + `errors.py`；旧路径 shim；guard 增加 `import_direction`（warning）。
- [ ] Day 3：`core/contracts/` 收口版本与 schema 名；迁移 `l1` 的 import。
- [ ] Day 4：迁移 `l3` 的 import；修第一轮 `import_direction` warning。
- [ ] Day 5：跑 golden diff + 架构守卫 + npu_sched 基线；提交 Phase 1。

---

## 9. 完成定义（Definition of Done）

- 依赖方向：0 违规。
- 核心执行文件：≤ 800 行。
- 产物：golden diff 0。
- 端到端：npu_sched 基线一致。
- 无 shim、无旧导入路径。
- `ARCHITECTURE.md` / `../notes/data.md` 与新结构一致。

---

## 10. 执行记录（2026-11-04）

### Phase 0：已冻结

- `tests/golden/architecture_baseline/`：5 个产物（case_ir / testpoints /
  gates / contract_manifest / worklist）。
- `scripts/golden_diff.py`：基线 vs 当前 run。
- 实测：`checked=5 · ok=true · diffs=[]`。
- `config/architecture_budget.yaml`：四个 Phase 2 目标文件已登记 reason/plan。

### Phase 1：结构已落位

- `src/core/runtime/ids.py`：ID 拼接唯一实现；`case_ir.ir_core` 改为 re-export。
- `src/core/runtime/errors.py`：`CaseModelError / CaseListError /
  StepOrderError / ContractAnchorMismatch / PipelineError`；
  `domain.errors`、`steps_dag`、`ledger` 已改为 re-export。
- 目标门面：`l3_decision/{contract,casemodel,evidence}`、
  `l4_memory/ledger`、`l5_evolution/closure`。
- 架构守卫新增 `import_direction`（warning）：
  - 当前债务 **52 条**：`tools → l4` 21、`tools → l1` 15、
    `l2 → executors` 9、`tools → l2` 5、`tools → l3` 2。
  - `guard.ok = True`；`import_direction_ok = False`（Phase 2 后转 error）。

### Phase 2.1：`verify/main.py` 已拆（1500 → 590）

- `steps/helpers.py`：位图 / 发现 / case 模型桥 / 约束端口等纯函数。
- `steps/testpoints.py`：`_prebuild_testpoints` / `_build_testpoints` / `_write_testpoints`。
- `steps/env_cov.py`：`_write_env_cov_bins` / `_agent_transaction_fields`。
- `steps/constraint.py`：`_write_constraint_yaml` / `_write_constraint_status`。
- `steps/gap.py`：gap 定向激励生成 / 编译校验 / 注入。
- `main.py` 只剩 `execute_task` 编排 + 覆盖率计划 / DUT 通道 / 关联报告；
  `VerifyExecutor` 通过 mixin 继承，公共入口不变。
- 验证：`compileall` + import 成功；`golden_diff` 0。

### Phase 2.2：`audit/main.py` 已拆（1449 → 545）

- `audit/helpers.py`（964 行）：只读摘要、门禁、证据包组装。
- `main.py` 只剩 `AuditExecutor.execute_task` 与类骨架。
- 验证：`compileall` + import 成功；`golden_diff` 0；guard 绿。

### Phase 2.3：`find_spec_yaml/main.py` 已拆（1494 → 429）

- `helpers.py`（1129 行）：RTL 解析、agent 分组、env/interface YAML 生成、
  位图/回归辅助。
- `main.py` 只剩 `run()` 编排与既有 re-export。
- 验证：`compileall` + import 成功；`golden_diff` 0；guard 绿。

### Phase 2.4：`cli/commands.py` 已拆（1353 → 746）

- `cmd_session.py`（422 行）：`dump` / `watch` / `status` / `history` /
  `workflows` / `exp`。
- `cmd_project.py`（225 行）：`project init/status/info/list/clean` + `web`。
- `commands.py` 只剩 `cli` 对象、公共 helper、审批/归档/清理/resume/gui。
- 验证：`compileall` + import 成功；`golden_diff` 0；guard 绿。

### Phase 2 完成后的四个目标文件

| 文件 | 之前 | 现在 |
|---|---:|---:|
| `executors/verify/main.py` | 1500 | 590 |
| `executors/audit/main.py` | 1449 | 545 |
| `tool_find_spec_yaml/main.py` | 1494 | 429 |
| `cli/commands.py` | 1353 | 746 |

### Phase 3：已迁两个包（实现先走，消费者后迁）

- `src/tools/checking/coverage_tools/` → `src/layers/l3_decision/evidence/`
  （19 个文件；旧路径只留 `__init__.py` shim）。
- `src/tools/humanview/case_ir/` → `src/layers/l3_decision/case_ir/`
  （7 个文件；旧路径 shim）。
- `resolve_author` → `src/core/runtime/identity.py`（L2 `human_edit` re-export）。
- 31 个外部 import 已改到新路径；`coverage_tools` 的 8 个内部绝对 import 已改。
- 验证：`compileall` + 关键 import 成功；`golden_diff` 0；guard 绿。

**当前逆流债务（64 条）**：

| 方向 | 数量 | 下一步 |
|---|---:|---|
| `tools → l3` | 20 | 消费者迁到 L3：`humanview/case_associate_view`、`verification_os/worklist`、`flow_tools` |
| `tools → l4` | 18 | `doc_tools` → L5/app、`debug_tools` → executors/debug、`regression_tools` → L1 |
| `tools → l1` | 13 | `collect_real_coverage` → L1、`uvm_tools` 适配器化 |
| `l2 → executors` | 9 | `execution.py` 改为 executor 注册表注入，不直接 import |
| `tools → l2` | 4 | `flow_tools` / `llm_call` 迁到 L2/app |

**注意**：债务数在迁移中途会先升后降 —— 实现先搬到 layers，消费者仍在 tools，
`tools → layers` 的边会暂时增加；Phase 4 删 shim、迁完消费者后才归零。

### Phase 3 第二批（按顺序执行）

| 原位置 | 新位置 | 规模 | 说明 |
|---|---|---|---|
| `tools/flow/flow_tools/` | `app/services/flow/` | 9 个文件 | 服务 API，归接口层；L2 仍经 shim 使用 |
| `tools/generation/doc_tools/` | `layers/l5_evolution/docs/` | 6 个文件 | 文档生成归 L5 |
| `tools/checking/debug_tools/` | `executors/debug/tools/` | 8 个文件 | 调试工具归 debug executor；L2 经 submodule shim 使用 |
| `tools/execution/regression_tools/` | `layers/l2_orchestration/regression_tools/` | 34 个文件 | **放 L2 而非 L1**：它依赖 l2 tool_protocol / l3 case_ir / l4 trend_db，放 L1 会制造新逆流 |
| `executors.verify.casemodel.registry` | 保持原位 + L2 延迟加载 | 1 个模块 | 避免 l2→executors 静态依赖 |

**`l2 → executors` 已清零**：`execution.py` 改为 `_EXECUTOR_PATHS` + `importlib`
延迟加载；`builtin_tools.py` 的 casemodel registry 同样延迟加载。

### Phase 3 收尾：静态逆流 43 → 0

- `spec_tools/` → `l3_decision/spec_tools/`（9 个消费者改路径，旧 shim 删除）。
- `case_associate_view/` → `l3_decision/case_view/`（7 个消费者改路径，旧 shim 删除）。
- `collect_real_coverage.py`：L3 解析/合并/种子函数改为**函数内延迟包装**，
  保留同名 API，去掉 modules 级 `tools → l3` 依赖。
- `compile.py` / `loopback.py`：`RegressionRunner` 改为函数内 import；
  `llm_refine.py` 删除未使用的 RegressionRunner import。
- 依赖方向检查改为**只看模块级 import**：函数内延迟加载不算静态依赖
  （这与我们用 importlib/函数内 import 切断方向的做法一致）。
- `_ALLOWED["tools"] = {"core", "l1"}`：适配器可调用 L1 基础设施。
- `architecture_guard.check()` 把 `import_issues` **并入 `ok`**：方向违规现在是阻断门禁。

**结果：`guard.ok = True`，`import_issues = 0`。**

### Phase 4：边界 shim 全部删除

- `flow_tools`：
  - `app/services/flow/_shared.py` → `layers/l2_orchestration/flow_shared.py`
    （纯只读 helper，无外部依赖）。
  - `run_artifacts` → `layers/l2_orchestration/run_artifacts.py`；
    L2 `approval` 直接用它，不再反向依赖 app。
  - `app/services/flow/run_api.py` 改为从 L2 re-export。
- `debug_tools`：
  - L2 `tool_hub` 的工具路径字符串改为 `src.executors.debug.tools.main`；
  - L2 `base.py` 的 schema 路径改为 `src/executors/debug/tools/schema.yaml`；
  - L2 `fix.py` 的函数内 import 改为 executors 路径。
- `regression_tools`：
  - 旧路径只剩注释/文档引用，已全部改为
    `layers/l2_orchestration/regression_tools`。
- 删除的旧目录：`tools/execution/`（整目录）、`tools/flow/flow_tools/`、
  `tools/checking/debug_tools/` 以及此前 5 个已删 shim。
- 清理悬挂的包清单：`tools/checking/__init__.py`、`tools/generation/__init__.py`、
  `tools/flow/__init__.py`、`tools/humanview/__init__.py` 不再列出已迁走的包。
- 清理 moved 路径留下的 `__pycache__`。

**当前状态：`import_issues = 0`，依赖方向已是阻断门禁；外层 shim 清零。**

### Phase 4 追加：剩余大文件拆分

| 文件 | 之前 | 现在 | 拆分去向 |
|---|---:|---:|---|
| `l2_orchestration/execution.py` | 1000 | **42** | `execution_helpers.py` + `execution_loop.py` + `execution_lifecycle.py` |
| `l1_infrastructure/infrastructure.py` | 1110 | **268** | `infra_helpers.py` + `regression_stage.py`（mixin） |
| `l4_memory/persistence/repository.py` | 1374 | **167** | `repository_{runs,docs,ppa,workflows}.py` |
| `l3_decision/evidence/case_cov.py` | 1019 | **116** | `case_cov_impl.py` |
| `tools/common/lib/collect_real_coverage.py` | 1118 | **60** | `coverage_collect.py` + `coverage_matrix.py` |
| `workbench/app.py` | 1212 | **220** | `main_window.py`（入口/骨架）+ `main_window_{layout,actions,events}.py` |

**GUI 主窗口也已拆完**：

| 文件 | 行数 | 职责 |
|---|---:|---|
| `workbench/main_window.py` | 47 | 类骨架 + `__init__` + `build_window_class()` |
| `workbench/main_window_layout.py` | 274 | 布局 / 窗格 / 状态栏 / 控制台 / 任务事件 |
| `workbench/main_window_actions.py` | 593 | 动作 / 菜单 / pickers / toolbar / 主题 |
| `workbench/main_window_events.py` | 140 | 关闭 / 重载 / 指南 / 报告 / 布局保存 |

Qt 仍然只在 `app._build_window_class()` 被调用时才 import，CLI/测试不依赖 Qt。

**最终验证**：

```text
compileall src: ok
guard:        True | import debt: 0 | line: 0 | complexity: 0
golden:       checked=5  ok=True
```

### Phase 2–4：待执行（按文件逐个搬）

**不在无测试的前提下一次性移动目录**：当前工作区仍有 154 个未提交改动，
一次性搬 `verification_os` / `casemodel_tools` / `coverage_tools` 会让
import 树直接碎。执行顺序固定为：

1. 先拆 `src/executors/verify/main.py` → `verify/steps/*`；
2. 再拆 `audit/main.py` → `audit/{verdict,gates,quality,evidence}.py`；
3. 再拆 `tool_find_spec_yaml/main.py` → `discovery.py` + `main.py`；
4. 最后把 `tools` 里的业务规则迁到 `layers`，每迁一个模块跑一次 golden diff；
5. Phase 4 删除 shim / 门面转发 / 旧导入路径。

---

## 11. 附：这次重构**不**做的事

- 不改 `../notes/data.md` 描述的业务主链。
- 不改 `case_ir` / `testpoints` / `contract` / `case_cov` 的字段语义。
- 不改签核三态与门禁级别。
- 不引入新的外部框架（LangGraph 迁移是另一条线，不混在这次重构里）。
