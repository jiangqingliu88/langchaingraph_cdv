# NPU_SCHED / CMD_SCH — AI VPlan 项目

本目录是 **spec-first** 的验证计划项目根：源 spec 为
[`docs/specs/cmdsched.md`](docs/specs/cmdsched.md)（CMD Scheduler Arch Spec），
人审抽取表与 target plan 都从这里派生。DUT 名为 **CMDSCHED**，项目目录名为
`npu_sched`。

> 当前为 **规划 + 证据门禁**：42 条契约中 8 条 `active`、34 条 `assume`
> （由 gate 依据 run 证据推进）；66 个 VPlan 测试点与 12 个 case 的计划状态仍是
> `planned`。
>
> 最近一轮执行（`output_vplan_e2e_gate_jiang_20261107_130948`）：
> **90/90 回归 PASS、功能覆盖率 95.23%、签核 PASS_WITH_CAVEAT / CONDITIONAL**。
> 真实证据来自 QuestaSim；`data/case_plan_view.html` 仍是 planned 占位视图。

## 快速开始

在本目录（`specs/npu_sched/`）执行：

```bash
# 1. 从人审抽取输入生成 target plan
python scripts/gen_spec_plan.py

# 2. 校验 spec 哈希、需求追溯、生成物是否同步
python scripts/gen_spec_plan.py --check
python scripts/lint_spec_trace.py

# 3. 生成 12 个 planned case 的占位视图
python scripts/gen_planned_case_view.py
```

打开 `data/case_plan_view.html`：12 个 case 的**计划占位视图**（PLACEHOLDER）；
真实执行与覆盖率证据在 run 目录，见下方“执行层”。

也可以使用 Makefile：

```bash
make spec      # 生成 target plan
make check     # 生成物同步 + spec 追溯
make trace     # 只跑 lint
make view      # 重新生成 case 占位视图
```

## 接入 SignOffAI 流程（规划/契约层）

SignOffAI 现在能直接把本目录当作 VPlan 项目读入：**不读 casemodel.yaml**，
而是用 `docs/specs/*.csv` 与 `data/contract_matrix/*.csv` 生成内核认识的
TestPoint IR / Case IR / 执行契约。

```bash
# 方式一：显式构建规划 IR
vagent vplan build specs/npu_sched -o output_vplan_npu_sched

# 方式二：verify 识别 VPlan 项目目录（同一个规划层）
vagent verify specs/npu_sched -o output_vplan_npu_sched

# 只读查看计数与状态
vagent vplan status specs/npu_sched
```

产物（位置与正常 run 一致）：

| 产物 | 内容 |
|---|---|
| `coverage/testpoints.{yaml,json}` | 66 条 TP；`planned`、`observe-only`（VPlan 未绑定事务字段） |
| `coverage/case_ir.json` | 12 条 CASE；`C-*` 引用保存在 `feats` |
| `contract/contract.yaml` + `obligations.json` | 由 Case IR 编译的 CT/OBL（现有内核） |
| `contract/plan_link.yaml` | `C-*` ↔ TP ↔ case 的 sidecar；当前 8 `active` / 34 `assume` |
| `docs/manifest.json` | `origin=vplan`、`status=PLANNED`、`execution=PLAN_ONLY` |

**不会**产生 `report.json` / `signoff_evidence/`，因此不可签核；契约状态
也不会被自动改成 `active`。

### 执行层（UVM/回归/证据）

`rtl/npu_sched.sv` + `data/execution_model.yaml`（维度/字段/断言/SCB/行为）
+ `cases/TC_*.yaml` 组成执行输入。`vagent vplan execute` 会把 case 契约与执行
资产合成**运行期** `<run>/inputs/casemodel.yaml`（不写回项目），再交给现有
verify 内核：

```bash
# 先看派生模型与等价命令，不跑 EDA
vagent vplan execute specs/npu_sched --dry-run

# 实跑（需要 QuestaSim 在 PATH）
vagent vplan execute specs/npu_sched -o output_vplan_npu_sched \
  --max-rounds 1 --sim-mode cov

# 低内存机器：vopt 用 -O0（等价于 SIGNOFFAI_VOPT_ARGS=-voptargs=-O0）
vagent vplan execute specs/npu_sched -o output_vplan_npu_sched \
  --max-rounds 1 --sim-mode cov --low-memory
```

执行跑完会产出真实的 UVM/回归/覆盖率证据；run 里会写
`contract/plan_link.yaml`（C-* ↔ TP ↔ case）与 `docs/vplan_source.json`。
但契约/TP/case 状态**仍不会自动升级** —— 必须先由 gate 依据证据推进，
否则保持 `assume` / `planned`。

**验证资产由 SignOffAI 生成，不在本目录手写。** `vplan execute` 默认
`--uvm-layout vplan`：verify 的 `jinja_render` 之后就把本次生成的资产落
`<run>/sv/`（与顶层 `agents/env/bench` 同一批文件）。已有 run 可补整理/核对：

```bash
vagent vplan package-assets <run>
# → <run>/sv/{interface,agents,monitor,coverage,sva,checker,scb,seq,test,env}
# → <run>/sv/asset_registry.csv（全部 candidate，未编译/无证据）

# 清理内核顶层工作目录，只保留 sv/（默认 dry-run）
vagent vplan clean-layout <run> --apply
# 或让 execute 成功后自动清：vagent vplan execute ... --clean-legacy

# 证据索引 + 契约门禁：TP 全命中 / 回归 PASS / sv/ 资产声明齐全才可能 active
vagent vplan link specs/npu_sched <run>
vagent vplan gate specs/npu_sched [--apply]
```

## 当前内容

| 项 | 数量/状态 |
|---|---|
| spec 需求 | 20 |
| feature 节点 | 39（1 root + 9 branch + 29 leaf） |
| 专题 | 10 |
| spec 契约 | 42（8 `active` / 34 `assume`，已入 `data/contract_matrix/`） |
| 测试点 | 66（全部 `planned`） |
| planned case | 12（全部 `planned`） |
| 真实证据 | 最近 run：90/90 PASS、功能覆盖率 95.23%、3 条 caveat |
| 签核 | run 级 `PASS_WITH_CAVEAT` / `CONDITIONAL`；项目级仍有 34 条 `assume` |

## 目录

```text
specs/npu_sched/
├── docs/
│   ├── specs/                  spec 原文 + 人审抽取表 + spec 哈希
│   ├── verification/           CMDSCHED target plan / matrix / case trace
│   ├── contract/               契约矩阵说明
│   └── appendix/               ID/锚点规范
├── data/
│   ├── contract_matrix/        42 条 spec 契约（8 active / 34 assume）
│   └── case_plan_view.html     12 个 planned case 的占位视图
├── schemas/                    contract / case JSON Schema（供后续落地）
├── scripts/
│   ├── gen_spec_plan.py        生成 target plan
│   ├── lint_spec_trace.py      spec 追溯 / 生成物一致性
│   ├── gen_planned_case_view.py 生成占位 case view
│   └── common/                 ID 正则 / Schema 子集
├── requirements.txt            仅标准库
└── VERSION
```

## 文档入口

| 文档 | 作用 |
|---|---|
| `docs/specs/README.md` | spec 抽取输入、hash/版本、换 spec 流程 |
| `docs/verification/CMDSCHED_README.md` | target plan 索引、状态、落地顺序 |
| `docs/verification/CMDSCHED_spec_analysis.md` | spec 分析结论 |
| `docs/verification/CMDSCHED_vplan.md` | 验证计划：feature 树、专题、TP、契约、case、签核 |
| `docs/verification/CMDSCHED_cases.csv` | 12 个 planned case |
| `docs/verification/CMDSCHED_case_trace.md` | contract → case → TP 追溯 |
| `data/contract_matrix/README.md` | 42 条 spec 契约与当前状态 |
| `scripts/README.md` | 生成/校验脚本 |

## 边界

- 执行使用 QuestaSim（不是 VCS/URG）；最近 run 有仿真 log、UCDB 与覆盖率报告。
- `case_plan_view.html` 是占位视图，不是签核依据。
- 换 spec 必须先更新 `docs/specs/cmdsched_*.csv` 和 `cmdsched_spec_meta.json`，
  再运行生成/校验；spec hash 不匹配时生成器会拒绝。
- 契约状态只允许按证据推进：`assume` 需要有 case、`// ARTIFACT:` 锚点、运行时
  激活和证据才能转 `active`；只改 CSV 状态不算。
- 下一步：处理剩余 34 条 `assume` 契约（2 条 TP 未命中、资产/检查未齐），
  再用 `vagent vplan gate --apply` 依据证据推进，而不是手改 CSV。
