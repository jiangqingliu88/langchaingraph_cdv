# 用例级覆盖率闭环与波形可追溯（方案设计）

> 状态：**已落地**。P0：逐用例取证 / `case_tp.json` / `waves/manifest.json` /
> audit 门 / `coverage case-report` + `wave show`；P1：`coverage/tp_bitmap.json`
> + 覆盖率接口 `tp_seen` 位图 + `[TP_HIT]` 日志 + 工作台「测试点」列 / 波形归属；
> P2：TP IR `timing.expect_cycles` + env 逐拍判窗 `[TP_TIMING]`（序列型只
> `TP_TIMING_WARN`，不否决）；P3：PATH 组（`path_groups:` → TP → 计划/证据）、
> 跨组 cross 实现架构、**TP Cov 四层证据视图**（`coverage/tp_cov_evidence.json`
> + `功能覆盖率 → TP Cov 证据` 页 + `vagent coverage tp-evidence`）。
> 关联：`docs/design/multi_dimensional_tp_ir.md`（TP IR v2）、
> `ARCHITECTURE.md` §7（方法论）、`src/tools/common/lib/collect_real_coverage.py`
> （`tp_matrix` 现状实现）、`src/tools/checking/coverage_tools/cov_api.py`
> （逐用例覆盖库）。
> 触发问题：**"每个用例要有自己的覆盖率组、对应覆盖点 100% 才算这个功能点
> sign off；现在看波形时序不对，也不知道波形对应哪个测试点。"**

---

## 0. 一句话

把"覆盖率达标"从**全局聚合**改成**逐用例取证**：

```text
一条用例（test + seed）
   │ 只统计它自己那份 ucdb
   ▼
它名下测试点（tp_id）的**全部覆盖仓**必须命中 100%
   │ 且 SCB / 断言 / illegal_bin 干净
   ▼
该 tp_id 记 SIGNED_OFF（带 signed_off_by = <task>@<seed>）
   │ 同一份 task 目录里必须有波形
   ▼
波形 ↔ 用例 ↔ 测试点 三者可互查
```

现状是"**合并库里有这个 bin**"就算命中 —— 那只能证明"某条用例打到过"，
既不能证明"这条用例证明了这个功能点"，也接不上波形。

---

## 1. 现状取证（为什么必须改）

以 `specs/npu_sched` 最近一次端到端 run 为样本：

| 现象 | 证据 | 后果 |
|---|---|---|
| 覆盖率只算**合并库** | `collect_real_coverage._tp_matrix()` 读 `coverage_cvg.txt`（267 条用例合并） | `TP-NPUSCH-D_QUEUE-0` 显示 `hits: 2559`，但**不知道是哪条用例打到的** |
| `tp_matrix` 行没有用例字段 | `rows[]` 只有 `tp_id/dimension/coverpoint/bin/hits/status/stage` | 无法回答"这个功能点由谁证明" |
| 波形与 TP 无关联 | 波形是 `waves/<task>.db`，TP IR 里有 `execution.test`，中间**没有落任何映射文件** | 打开波形只能看到模块名，看不到"这条波形在证明哪个 TP" |
| 逐用例覆盖库没被消费 | `regression_run/<stage>/build_*/test_<task>/cov/<test>/questa.db` 实测 **267 份**（30–99 KB/份），只用于最后合并 | 花掉的仿真成本没有变成"逐用例证据" |
| 时序无从校对 | TP IR 只声明 `status_rule.pass`（`UVM_ERROR=0 and mismatched=0`） | 波形里的握手时序对不对**没有任何判据**，只能人眼看 |

**结论**：缺的不是数据，是**契约**——"用例 → 覆盖仓 → 测试点 → 波形"这条链
没有任何一处是显式写下来的。

---

## 2. 目标与判据（Definition of Done）

一条 `tp_id` 只有在**同一条用例、同一次 seed 运行**里同时满足下列全部，才记
`SIGNED_OFF`：

| # | 判据 | 数据来源 |
|---|---|---|
| 1 | 该用例**自己**的 ucdb 里，TP 名下的**全部**仓命中 | `cov/<test>/questa.db` → `vcover report -cvg` |
| 2 | 该用例的 `illegal_bins` 零命中 | 同上 |
| 3 | 该用例 `UVM_ERROR == 0` 且 SCB `mismatched == 0` | `sim_vsim.log` |
| 4 | 绑定到该 TP 的断言未触发 | `[DUT_CHK]` 收口行 |
| 5 | 该 task 目录存在波形，且能反查到 `tp_id` | `waves/<task>.db` + `waves/manifest.json` |
| 6 | （行为/序列类 TP）时序窗口与 `expect_window` 一致 | 见 §3.6，P2 落地 |

**不是**要求"整条用例把整个 covergroup 跑满 100%"。整个 covergroup 的
corner 仓分散在不同用例里，要求单条用例 100% 会造出**不可能达标的门**。
100% 的**作用域是该 TP 拥有的仓集合**（proof obligation）。

---

## 3. 核心设计

### 3.1 三级闭环

```text
                    ┌──────────────────────────────┐
                    │ TP IR (testpoints.yaml)      │
                    │  tp_id                       │
                    │  coverpoint / bin(s)         │
                    │  execution.test / stage      │
                    │  status_rule.evidence        │
                    └──────────────┬───────────────┘
                                   │ 反查：test → [tp_id…]
                                   ▼
┌────────────────────────────────────────────────────────────────┐
│ 回归任务表（regression.yaml / task meta）                       │
│   task: tp_npusch_d_queue_0_seed_6001                         │
│     test: npu_sched_env_d_queue_p0_test                        │
│     seed: 6001   stage: p1   tp_ids: [TP-NPUSCH-D_QUEUE-0]     │
└──────────────┬─────────────────────────────────────────────────┘
               │ 跑一次
               ▼
┌────────────────────────────────────────────────────────────────┐
│ 用例目录 regression_run/p1/build_<build>/test_<task>/          │
│   cov/<test>/questa.db      ← 这一条用例的覆盖库（独立）        │
│   waves/<test>.db           ← 这一条用例的波形                  │
│   sim_vsim.log              ← UVM_ERROR / mismatched / TP_HIT   │
└──────────────┬─────────────────────────────────────────────────┘
               │ 逐用例解析（**不合并**）
               ▼
  coverage/case_cov/<task>.json    一条用例一份覆盖切片
  coverage/case_tp.json            用例 ↔ TP 证据表
  waves/manifest.json              波形 ↔ 用例 ↔ TP
               │
               ▼
  coverage/tp_matrix.json（扩展）  tp_id → status / signed_off_by
               │
               ▼
  audit 门禁：TP_NOT_SIGNED_OFF / TP_WAVE_MISSING / TP_ILLEGAL_BIN
```

### 3.2 "每条用例一个覆盖率组"到底落在哪

两种实现，**默认 B1，B2 只在需要波形可读时开**：

| | B1 逻辑覆盖组（默认） | B2 物化覆盖组（可选） |
|---|---|---|
| 做法 | 复用现有 `cg_npu_sched_in/out/dut`，在**该用例的 ucdb**上切片评估 | 在 env 覆盖率组件里为每个 TP 生成 `covergroup cg_tp_<id>` + `option.per_instance` |
| 代码量 | 0 行新增 SV | 每个 TP 一组，70 个 TP ≈ 上千行 |
| 证据强度 | 一样：100% 的仓 = 该用例自己打到的 | 一样 |
| 波形可见性 | 靠 §3.5 的 `tp_seen` 位图 | 报告里直接多一个 covergroup |
| 结论 | **默认走这条** | 只对用户点名要"波形里能看见覆盖组"的 TP 开 |

> 关键点：覆盖率"按组"是为了**归属清晰**，不是为了多造一层 SV。
> 切片评估同样能回答"这条用例证明了哪些仓"，而且不引入第二条真源。

### 3.3 100% 的作用域：proof obligation

TP IR 现有字段已经够用：

```yaml
tp_id: TP-NPUSCH-D_DEP-RAW
coverpoint: cp_dep_type
bin: raw                      # 单仓
# 或（交叉/多仓 TP）
bins: [raw_waw, raw_war]      # 多仓：全部命中才算
status_rule:
  pass: UVM_ERROR=0 and mismatched=0
  evidence: bin cp_dep_type.raw
```

判定伪码：

```python
owned   = tp.bins or [tp.bin]                       # proof obligation
hit     = {b for b in owned if per_case_hits[(tp.coverpoint, b)] > 0}
illegal = per_case_illegal_hits(tp.coverpoint)      # 一票否决
ok      = (len(hit) == len(owned)) and not illegal
```

### 3.4 TP 状态机

```text
 PENDING ──生成用例──► PLANNED ──owner case 跑通──► EXERCISED
                                                       │
                                proof obligation 100% ─┤
                                + SCB/断言/illegal 干净 ┤
                                + 波形存在且可反查     │
                                                       ▼
                                                  SIGNED_OFF
     任何一步失败 → MISS / UNOBSERVED / BACKDOOR_MISS / UNSIGNED（保留原因）
```

现有 `tp_matrix.counts` 的四态（HIT / MISS / OBSERVED / UNOBSERVED /
BACKDOOR_HIT / PENDING_BACKEND）**保留**，只是把"命中"的**统计域**从合并库
改成"该 TP 的 owner case"。新增 `signed_off` / `signed_off_by` 两个字段。

### 3.5 波形 ↔ 测试点

波形本身是二进制，没法直接写入字符串。用**三种手段叠加**，从粗到细：

1. **文件层**：`waves/manifest.json` 显式写死映射（唯一真源）：

```json
{
  "schema": "wave_manifest_v1",
  "task": "tp_npusch_d_queue_0_seed_6001",
  "test": "npu_sched_env_d_queue_p0_test",
  "seed": 6001,
  "stage": "p1",
  "tp_ids": ["TP-NPUSCH-D_QUEUE-0"],
  "coverpoints": [{"cp": "cp_queue_level", "bins": ["empty"], "status": "SIGNED_OFF"}],
  "wave": "waves/tp_npusch_d_queue_0.db",
  "log": "sim_vsim.log",
  "sim_time_ns": {"end": 200.1},
  "backend": "questa-qwavedb"
}
```

2. **波形内**：覆盖率接口新增 `tp_seen` 位图。它**不是端口**（端口是 bind 到
   DUT 信号的；`tp_seen` 没有对应的 DUT 信号），而是接口体内的一个变量，由
   env 覆盖率组件在仓命中时置位：

```systemverilog
// coverage/<dut>_cov_if.sv（自动生成）
logic [69:0] tp_seen;   // 位序 = coverage/tp_bitmap.json 的 entries[].bit
```

   第 *i* 位在对应 TP 的仓**首次命中**时置 1，**之后保持为 1**（不做逐拍清零）——
   波形里看的是"到这一刻为止点亮了哪些测试点"。位序 = `testpoints.yaml` 的
   序号，**一旦发布不重排**（历史波形靠它对号）。

3. **日志内**：env 覆盖率组件在 TP 仓**首次**命中时打一行，带仿真时间：

```text
[TP_HIT] tp=TP-NPUSCH-D_QUEUE-0 cp=cp_queue_level bin=empty t=%0t
```

> 三者的顺序是"权威 → 方便"：`manifest.json` 是签核材料，`tp_seen` 是给人看
> 波形用的，`[TP_HIT]` 是给 grep / 日志分析用的。任何一处缺失不影响另外两处。

### 3.6 时序判据（"时序都不对"怎么变成机器可判）

TP IR 的行为域已经有 `temporal` / `sequences`，缺的是**期望窗口**。扩展：

```yaml
tp_id: TP-NPUSCH-D_SEQ-LOAD_MAC
realization: {kind: sequence}
timing:
  expect_cycles: {min: 2, max: 12}     # 从 load 提交到 mac 发射
  start: load_submit                   # 窗口起点（DUT 信号名）
  end: issue_valid                     # 窗口终点（= sample 亦可）
  sample: issue_valid                  # 观测点（end 缺省时用它）
  tolerance: 0                         # 严格相等时可省
```

**落地口径**：`start` / `end` 必须是 DUT 信号名（env 检查组通过覆盖率接口读，
verify 会把它们作为 `extra_signals` 引成接口端口）。缺任一 → `checkable=False`，
生成期在 `tp_bitmap.json.notes` 里说清，**不生成一个永远不报的空检查**。

env 检查组逐拍求值，超窗即 `UVM_ERROR [TP_TIMING]`，并写进
`case_cov/<task>.json → timing_ok`。**没有 `timing` 块的 TP 不判时序**——
不编一个假期望，也不把"没声明"当成"通过"（与现有 `DUT 检查跳过` 同一口径）。

---

## 4. 产物清单

| 文件 | 归属 | 内容 | 谁写 |
|---|---|---|---|
| `coverage/case_cov/<stage>/<task>.json` | 新增 | 单用例：TP 的仓命中/未命中、覆盖率%、illegal、timing_ok、日志引用 | `collect_real_coverage` |
| `coverage/case_tp.json` | 新增 | 用例 ↔ TP 证据表（正查/反查都能查） | 同上 |
| `waves/manifest.json` | 新增 | 波形 ↔ 用例 ↔ TP | `ops`（回归收尾）|
| `coverage/tp_matrix.json` | 扩展 | 行新增 `owner_case` / `signed_off` / `signed_off_by` | 同上 |
| `coverage/tp_matrix.json#counts` | 扩展 | 新增 `SIGNED_OFF` / `UNSIGNED` | 同上 |
| `signoff_evidence.json#case_coverage` | 扩展 | 证据包新增一节 | `signoff_package` |
| `caveats.json` | 扩展 | `TP_NOT_SIGNED_OFF` / `TP_WAVE_MISSING` / `TP_TIMING_WARN` | `audit` |

`case_cov/<task>.json` 形状：

```json
{
  "schema": "case_cov_v1",
  "task": "tp_npusch_d_queue_0_seed_6001",
  "test": "npu_sched_env_d_queue_p0_test",
  "seed": 6001,
  "ucdb": "cov/npu_sched_env_d_queue_p0_test/questa.db",
  "tp": [{
    "tp_id": "TP-NPUSCH-D_QUEUE-0",
    "coverpoint": "cp_queue_level",
    "owned": ["empty"],
    "hits": {"empty": 2559},
    "pct": 100.0,
    "illegal_hits": [],
    "status": "SIGNED_OFF"
  }],
  "uvm_errors": 0,
  "scb": {"total": 40, "matched": 40, "mismatched": 0},
  "assertions": {"rules": 4, "fired": 0},
  "timing_ok": null
}
```

---

## 5. 实现落点（按文件，按依赖顺序）

### P0 —— 逐用例取证 + 映射（不改 SV，1 天内可跑通）

1. `src/tools/checking/coverage_tools/cov_api.py`
   - 只复用 `materialize_ucdb()`（已存在：`questa.db → _ucdb/<test>.ucdb`，
     **功能覆盖率必须走这一步，否则 ucdb 里的 cg 数据会静默丢失**）。
2. `src/tools/common/lib/collect_real_coverage.py`（解析器都在这里，别另起一套）
   - 新增 `_case_cov_matrix(od)`：扫 `regression_run/*/build_*/test_*/`，
     逐目录 `materialize_ucdb` + `vcover report -cvg`，
     复用现成的 `_parse_cvg_bin_hits()` 得到 `{cp: {bin: hits}}`；**不合并**；
   - 扩展 `_tp_matrix()`：行加 `owner_case` / `signed_off` / `signed_off_by`；
     `counts` 加 `SIGNED_OFF` / `UNSIGNED`。
3. `src/tools/execution/regression_tools/`（任务表生成）
   - 生成 task 时把 `tp_ids` 写进 meta：从 TP IR 的 `execution.test` 反查
     （一个 test 可能挂多个 TP）。
4. `src/executors/ops/main.py`（回归收尾）
   - 写 `waves/manifest.json`：task 目录里 `waves/*.db` + task meta + TP 反查。
5. `src/executors/audit/main.py`
   - 新 gate `tp_signed_off`：`drivable` 里非 `SIGNED_OFF` 的进 caveat
     `TP_NOT_SIGNED_OFF`；`SIGNED_OFF` 却找不到波形 → `TP_WAVE_MISSING`。

### P1 —— 波形里看得见（改 SV 模板）

6. `src/tools/generation/uvm_tools/tool_uvm/templates/environment_templates/env_cov.sv.j2`
   - 按 TP 序号生成位图置位逻辑（仓命中即置位，保持为 1）；
   - `tp_seen` 作为**接口体变量**（不是端口）进覆盖率接口，`render_cov_interface`
     按 `tp_bitmap_width` 生成 `logic [N-1:0] tp_seen;`；
   - 首次命中打 `[TP_HIT] tp=… cp=… bin=… t=%0t`。
7. `src/executors/verify/main.py`
   - 生成 TP 序号表 `coverage/tp_bitmap.json`（位序 → tp_id），位序一旦发布
     不重排（重排会让历史波形对不上号）。

### P2 —— 时序判据

8. `src/tools/generation/casemodel_tools/domain/model.py` + `framework/serialize.py`
   - TP IR 支持 `timing.expect_cycles`；
9. `env_cov.sv.j2` + `checker_rules`：逐拍判窗，超窗报 `[TP_TIMING]`。

### UI / CLI（可与 P0 并行）

10. `src/cli/cmd_coverage.py`（新增子命令）
    - `vagent coverage case-report -o <run> --tp TP-…`：打印该 TP 的取证链；
    - `vagent wave show -o <run> --task <task>`：打印 manifest 并给打开命令。
11. `src/workbench/modules/ops/regression_artifacts.py`
    - 回归表格加列 **测试点**（`tp_ids` 截断显示，tooltip 全量）；
12. `src/workbench/modules/ops/cov_actions.py`
    - `open_wave()` 打开前先读 `waves/manifest.json`，窗口标题写
      `<test> · <tp_ids>`；manifest 缺失时退回文件名。

---

## 6. 边界与失败模式

### 6.1 100% 只在 owner case 上判

- 一个 TP 可能被多条用例"顺便"打到 —— **不算数**。签核只认 owner case
  （TP IR `execution.test`）。
- 一条用例挂多个 TP（主题级 test）→ 每个 TP 各自判，`case_tp.json` 一对多。
- owner case 缺失（TP 只有 observe 形态）→ 状态停在 `OBSERVED`，
  不升级为 `SIGNED_OFF`，并在 caveat 里点名。

### 6.2 后门与观测型

| TP 形态 | 判据 | 特别约定 |
|---|---|---|
| `backdoor` | 后门赋值后、**同一条用例内**仓命中 | 跨用例继承的命中一律不认 |
| `observe` | 仓命中 > 0（无激励差异） | 仍需同用例 + SCB/断言干净 |
| `sequence` | 仓命中 + `timing`（若有） | 时序超窗只降级为 `TIMING_WARN`，不否决 |
| `behavior`（PENDING_BACKEND） | 无执行数据 | **不进任何覆盖率分母**（沿用现状） |

### 6.3 illegal_bin 是一票否决

用例命中 `illegal_bins` 意味着"到达了模型声明的不该到达的状态"。这种用例
**即使是绿色的**也不能为任何 TP 背书 —— 记 `ILLEGAL_HIT`，该用例名下所有 TP
置 `UNSIGNED`。

### 6.4 多 seed 与幂等

- TP IR 已带 `execution.seeds`；`signed_off_by` 记**第一个**达成 100% 的
  `(task, seed)`，重跑同一 seed 结果幂等；
- 扩种（`seed_offset`）只增加证据，不改变既有 `signed_off_by`。

### 6.5 性能

逐用例解析 ≈ 用例数 × `vcover report`（量级估计：267 条在分钟级；
**落地时以实测替换这个估计**，不预先写死承诺）。提供 `--case-cov-sample N`：超过 N 条时只解析
"signed_off 尚未达成的 TP 的 owner case"，其余沿用合并库结论并标注
`EVIDENCE_SAMPLED`。**采样必须说出来**，不能静默降级。

### 6.6 与现有门禁的关系

- `coverage_metric=functional` 的闭环收敛判据**不变**（合并库、全局口径）；
- 本方案新增的是**逐 TP 的签核门**，比"整体 95%"更细，二者不互相替代；
- `SIGNED_OFF` 不进闭环收敛公式，避免"闭环为了收敛去凑 TP"。

---

## 7. 用 npu_sched 验收（可执行清单）

基线来自 `output_e2e_npu_sched_20261103d_jiang_20261103_013546`：

| 检查项 | 期望 |
|---|---|
| `case_cov/**/*.json` 条数 | = 产出覆盖库的用例数（本次合并口径 267；不含 build 任务） |
| `case_tp.json` 覆盖的 tp_id | 70/70（含 PENDING_BACKEND 的 7 条，状态如实） |
| 可激励 TP `drivable_pct`（owner case 口径） | 37/37 = 100% |
| 后门 TP `backdoor_pct` | 10/10 = 100% |
| 观测型 `observed` | 14/22（现状如此；未达成列进 caveat，不造假） |
| `tp_matrix.signed_off` | ≥ 47（37 可激励 + 10 后门） |
| `waves/manifest.json` 条目 | = 有波形的 task 数 |
| 每条 `SIGNED_OFF` 的 TP 都能反查到波形 | 100% |
| `caveats.json` | 只允许 `TP_NOT_SIGNED_OFF` / `TP_WAVE_MISSING` / `TP_TIMING_WARN`，且逐条列明 tp_id |
| 断链检查 | `case_tp.json` 里不存在指向不存在 task 的 tp_id |

验收命令（落地后）：

```bash
vagent coverage case-report -o output_e2e_npu_sched_... --tp TP-NPUSCH-D_DEP-RAW
# tp=TP-NPUSCH-D_DEP-RAW
#   owner : npu_sched_env_d_dep_pRAW_test @ p1
#   task  : tp_npusch_d_dep_raw_seed_4001
#   bins  : cp_dep_type.raw  hits=37  pct=100.0  SIGNED_OFF
#   scb   : total=40 matched=40 mismatched=0
#   assert: 4 rules, 0 fired
#   wave  : .../test_tp_npusch_d_dep_raw_seed_4001/waves/tp_npusch_d_dep_raw.db
#           visualizer -wavefile <db>
```

---

## 8. 明确不做的

- **不**为每条用例复制一份 covergroup（B2 只在点名需要时开）——会产生第二
  条真源与上千行样板 SV；
- **不**要求单条用例把整个 covergroup 跑满 100%——那是不可达的门；
- **不**在闭环收敛公式里加 TP 权重——收敛是"整体够不够"，签核是"逐点证没证"；
- **不**从波形反推覆盖率——`questa.db` 才是覆盖率真源，波形只做定位与复核。
核心判断

  问题不在数据缺失，在契约缺失。 这次
  run 里其实每样东西都齐了 —— 267
  份逐用例 questa.db、267 份
  waves/<task>.db、TP IR 里的
  execution.test / status_rule.evidenc
  e——但没有一处把「用例 → 覆盖仓 →
  测试点 → 波形」写下来，所以最后只能
  靠合并库说"这个 bin 被打到过"。

  方案要点

  1.
  覆盖率从"全局聚合"改成"逐用例取证"
  _tp_matrix() 现在读的是 267
  条用例合并后的 coverage_cvg.txt（TP-
  NPUSCH-D_QUEUE-0 显示 hits:
  2559，但不知道是谁打的）。改成逐目录
  解析，在每条用例自己那份 ucdb 上判。

  2. "100%" 的作用域要说清楚
  不是"单条用例把整个 covergroup
  跑满"——那是不可能达标的门（corner
  仓分散在不同用例里）。100%
  的作用域是该 TP 拥有的仓集合（proof
  obligation），"每条用例一个覆盖率组"
  是逻辑概念，不是真去复制 70 个
  covergroup（会给上千行样板
  SV、多一条真源）。

  3. TP 状态机新增 SIGNED_OFF
  在同一条用例、同一次 seed
  里同时满足：自己那份 ucdb 里 TP
  名下仓全中 + 无 illegal_bin +
  UVM_ERROR=0 + SCB mismatched=0 +
  绑定断言未触发 +
  有波形可反查。signed_off_by =
  <task>@<seed>。

  4. 波形可追溯（三处叠加）
  - waves/manifest.json ——
  权威映射（task/test/seed/tp_ids/cove
  rpoint/bin/wave 路径）；
  - 覆盖率接口加 tp_seen
  位图（复用刚加的
  extra_signals），打开波形就能看到这
  一拍点亮了哪几个测试点；
  - env 组件首次命中打 [TP_HIT] tp=…
  cp=… bin=… t=…ns。

  5. 时序从"人眼看"变成"机器判"
  TP IR 行为域已有
  temporal/sequences，缺期望窗口。加
  timing.expect_cycles {min,max}，env
  逐拍判窗，超窗报 [TP_TIMING]。没声明
  timing 的 TP 不判——不编假期望，也不
  把"没声明"当"通过"。

  落地路径

  - P0（不改 SV）：逐用例解析 +
  case_cov/*.json + case_tp.json +
  - P0（不改 SV）：逐用例解析 + case_cov/*.json +
  case_tp.json + waves/manifest.json + audit
  门禁；
  - P1：tp_seen 位图 + [TP_HIT] 日志 +
  工作台"测试点"列、波形窗标题带 tp_id；
  - P2：时序窗口。

  文档里还写了验收清单（可拿这次 run
  当基线：可激励 37/37、后门 10/10、观测
  14/22）、失败模式（后门跨用例继承不认、illegal
  一票否决、多 seed
  幂等、采样必须说出来），以及明确不做的四件事。

  需要的话我可以按 P0 先落地，跑一遍 npu_sched
  验证 case_tp.json 能出来。
---

## 9. 四层证据与 PATH 组（评审口径）

### 9.1 四层证据不是"一个用例覆盖了"的并列条件

覆盖率报告里的 bin 命中只回答**第一层**："这个场景发生过吗"。一个**功能契约**
要被判定为验证完成，需要四类证据（**按契约判定，不按单个用例判定**）：

| 层 | 回答 | 由谁证明 | 只命中/通过意味着什么 | 不证明什么 |
|---|---|---|---|---|
| 功能覆盖 | 场景发生过吗？ | coverpoint / cross bin | 激励和状态到达 | 不证明时序、数据、路径正确 |
| 时序断言 | 时序行为对吗？ | SVA / `[DUT_CHK]` | 握手、start/done/rls、反压保持正确 | 不证明数据结果或整条路径 |
| 数据比对 | 数据/资源结果对吗？ | scoreboard | 数据、tag、SPAD/寄存器不丢不重 | 不证明没声明要查的字段 |
| 路径覆盖 | 整条生命周期走通了吗？ | PATH 组 | `cmd_hs → … → rsp/rls` 的完整路径发生且绑定检查通过 | 功能组 100% 不能替代 |

**一个用例可以只提供其中一部分**，多个用例合起来构成完整证据链。所以：
`bin 命中 ≠ 功能已验证`；`只跑通 SVA`、`只命中功能 bin` 都不能单独签核功能。

落地产物：`coverage/tp_cov_evidence.json`（`tp_cov_evidence_v1`）。每个 TP 一节
`evidence_layers`，四层各自带 `status / proves / source`；`contract_status` 只在
`functional + timing + data` 全部 `PROVEN`（路径型契约还要 `path PROVEN`）时才判
`VERIFIED`。任一层 `NOT_APPLICABLE`（模型没声明检查/比对）→ 只能 `PARTIAL`，
**不把"没声明"当"通过"**。

工作台：`功能覆盖率 → TP Cov 证据` 页（左表四层状态，右栏完整证据链）；
CLI：`vagent coverage tp-evidence -o <run> [--tp …]`。

### 9.2 PATH 组：功能组之外的第二条度量轴

`path_groups:` 按**指令生命周期**切，不按功能切：

```yaml
path_groups:
  - id: CG_CMDSCHED_PATH
    name: 端到端指令路径
    sample: path_seq
    coverpoint: cp_path_issue_lifecycle
    bins:
      - name: direct_full
        sequence: [cmd_hs, no_dep, direct, start, done, rls, rsp]
        checks: [SVA-START-DONE-ID, SCB-RSP-DATA]
        requirement: Feat-10
        timing: {expect_cycles: {min: 2, max: 12}, start: a, end: b}
```

- **一条 bin = 一条 TP**（`TP-<obj>-PATH-<bin>`），进同一份 TP IR / 矩阵 / 证据视图；
- `checks` 是**这条路径必须同时绑定的 SVA/SCB 检查项** —— PATH 组证明"路径走通"，
  checker 证明"走通且走对"；
- 执行后端（序列 → UVM + `path_seq` 采样）在 P1b：当前如实标 `PENDING_BACKEND`，
  不进功能覆盖率分母，也**不宣称路径已验证**；
- 实现：`domain/paths.py`（模型）→ `framework/paths.py`（编译成 TP）→
  `coverage_plan` 的 `paths` 段（计划/追溯）→ `tp_evidence` 的 `path` 层。

### 9.3 跨组 cross 的实现架构

```
casemodel.cross_matrix / cross_groups / policy_pack.coverage_bins
        │  声明"哪两个维度要一起组合、哪些组合非法"
        ▼
CoverageModel.crosses (CrossPoint：name / dimensions / bins / illegal)
        │  渲染
        ▼
SV covergroup：cg_<agent> 的 `cross_<name>`（同 agent）
              或 cg_mixed 的 `cross_<name>`（跨 agent，重复声明各 agent 的 cp）
        │  ucdb
        ▼
vcover `-cvg -details`：cross 级百分比
        │
        ▼
tp_cov_evidence.groups.cross：name / dimensions / bin 数 / 实测 %
```

边界（评审要能说清）：

- cross 只证明**组合发生过**；组合在正确时序/数据下发生，仍由 `timing`
  （SVA/`[DUT_CHK]`）与 `data`（SCB）两层证明；
- 非法组合走 `illegal_bins`（一票否决），不混进"正常仓"；
- 跨 agent 的组合不能塞进单个 `cg_<agent>`，必须单开 `cg_mixed`（模板已实现）；
- `coverage_bins`（策略包）生成的是**语义 cross**，与模型 `cross_matrix` 同源不同层：
  前者是设计风格知识，后者是模块声明；两边名字都进证据视图，不互相冒充。

### 9.4 评审现场可直接用的回答

> "功能组的 100% 只证明每个功能契约的取值/场景都打到了；路径通不通由独立的
> PATH 组负责，且每个 PATH bin 都绑定对应的 SVA 和 scoreboard 检查项。
> 四类证据按功能契约汇聚，不按单个用例：一个用例可以只提供一部分，多个用例
> 合起来构成完整证据链。覆盖率报告里的 bin 命中率只是第一层，不单独作为功能
> 签核依据。"

如果 PATH 后端尚未接：

> "PATH 组已建模并进 TP IR / 证据视图，当前是 `PENDING_BACKEND` —— 我们不宣称
> 路径已验证；功能组 100% 只说明场景覆盖，路径证据待后端接上后补。"
