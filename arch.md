**按“case = groups[] + sva[] + scb[] + constraints[] 显式容器”来改，架构不需要推倒，只需在现有主链上做 6 处调整：把 `case_ir` 变成四集合契约，把 `case_cov` 变成四集合证据，把 `case_view` 变成四节渲染，把 `cell_matrix` 改成由集合反向填充，把门禁加集合完整性检查，把 EVD 去重键扩到 checker 级。** 逐项给落点。

## 一、总体调整原则

1. **主链不变**：`front → verify → ops → coverage → audit` 不动。
2. **只改 `coverage/` 派生层和 `verify` 的 Case IR 产物**，`ops` 的逐用例 `cov/*.db`、`waves/*.db`、`task_meta.json` 不动。
3. **`case` 成为一级契约**：`groups[] / sva[] / scb[] / constraints[]` 四集合是 `case_ir` 的必填结构。
4. **`cell_matrix` 仍是枢纽**：case 集合只做证据来源，不替代 Cell。
5. **签核仍看 `cell_matrix + gates + caveats`**：`case_view` 只呈现，不直接签核。

## 二、逐文件调整

### 1. `verify` 阶段：`coverage/case_ir.json` 改成四集合契约

**现在**：`case_ir.json` 是 CCAT 分类树 + CASE 逻辑用例。  
**改成**：每个 case 必须显式声明四集合 —— `groups / sva / scb / constraints`。

```json
{
  "case_id": "TST-CMDSCHED-DEP-001",
  "groups": [
    {"group": "CG-CMDSCHED-PATH", "cell": "CELL-CMDSCHED-PATH-P-STORED-ISSUED", "required_layers": ["functional", "path"]},
    {"group": "CG-CMDSCHED-CALC", "cell": "CELL-CMDSCHED-CALC-P-STORED-ISSUED", "required_layers": ["functional", "timing", "data"]},
    {"group": "CG-CMDSCHED-ARB",  "cell": "CELL-CMDSCHED-ARB-P-STORED-ISSUED",  "required_layers": ["functional", "data"]}
  ],
  "sva": [
    {"id": "SVA-CMDSCHED-DEP-001", "cell": "CELL-CMDSCHED-DEP-P-STORED-ISSUED", "required": true},
    {"id": "SVA-CMDSCHED-ISSUE-001", "cell": "CELL-CMDSCHED-ISSUE-P-STORED-ISSUED", "required": true}
  ],
  "scb": [
    {"id": "SB-CMDSCHED-HAZARD-001", "cell": "CELL-CMDSCHED-DEP-P-STORED-ISSUED", "required": true},
    {"id": "SB-CMDSCHED-SLOT-001", "cell": "CELL-CMDSCHED-ISSUE-P-STORED-ISSUED", "required": true}
  ],
  "constraints": ["p_th_cmdsched_dep_random"],
  "not_applicable": {"sva": [], "scb": []}
}
```

**规则**：

- `groups` 非空；
- `sva` / `scb` 可以是 `[]`，但必须显式出现，且 `not_applicable` 要写原因；
- `constraints` 列**约束 id**（`p_*` 策略名，来自 `coverage_plan.constraint_backing`
  的维度交集）；可以为空 —— 空表示"这些维度没有绑定约束策略"，不编 id；
- 每项必须带 `cell`；
- `required_layers` 决定该组要哪几层证据。

### 2. `verify` 阶段：`testpoints.yaml` 增加 `case_id` 与四集合引用

**现在**：70 条 TP 有 `tp_id/覆盖仓/test/种子/判据`。  
**改成**：每条 TP 增加：

```yaml
tp_id: TP-CMDSCHED-DEP-001
case_id: TST-CMDSCHED-DEP-001
groups: [CG-CMDSCHED-DEP]
sva: [SVA-CMDSCHED-DEP-001]
scb: [SB-CMDSCHED-HAZARD-001]
constraints: [p_th_cmdsched_dep_random]
```

这样 `case_ir` 可以从 TP 反向聚合生成，避免两处手维护。

### 3. `ops` 阶段：`task_meta.json` 增加四集合指纹

**现在**：`task_meta.json` 有 `task/test/seed/stage/tp_ids/case_id/tst_id`。  
**增加**：

```json
{
  "case_id": "TST-CMDSCHED-DEP-001",
  "group_ids": ["CG-CMDSCHED-PATH", "CG-CMDSCHED-CALC", "CG-CMDSCHED-ARB"],
  "sva_ids": ["SVA-CMDSCHED-DEP-001", "SVA-CMDSCHED-ISSUE-001"],
  "scb_ids": ["SB-CMDSCHED-HAZARD-001", "SB-CMDSCHED-SLOT-001"],
  "constraint_ids": ["p_th_cmdsched_dep_random"],
  "case_ir_sha": "<sha256>"
}
```

`case_ir_sha` 用于哈希链，保证证据对应的是哪个版本的 case 契约。

### 4. `coverage` 阶段：`case_cov/<stage>/<task>.json` 改成四集合证据

**现在**：单用例的仓命中 / illegal / SCB / 断言 / timing / 波形。  
**改成**：

```json
{
  "case_id": "TST-CMDSCHED-DEP-001",
  "evd_id": "EVD-CMDSCHED-...",
  "constraints": ["p_th_cmdsched_dep_random"],
  "groups": [
    {
      "group": "CG-CMDSCHED-PATH",
      "cell": "CELL-CMDSCHED-PATH-P-STORED-ISSUED",
      "functional": {"status": "PROVEN", "bins_hit": ["direct_full"], "bins_miss": []},
      "path": {"status": "PENDING_BACKEND", "reason": "path_seq 后端未接"}
    },
    {
      "group": "CG-CMDSCHED-CALC",
      "cell": "CELL-CMDSCHED-CALC-P-STORED-ISSUED",
      "functional": {"status": "PROVEN", "bins_hit": ["..."], "bins_miss": []},
      "timing": {"status": "PROVEN"},
      "data": {"status": "PROVEN"}
    }
  ],
  "sva": [
    {"id": "SVA-CMDSCHED-DEP-001", "cell": "...", "hit": 1204, "fail": 0, "cover_property_hit": 1204, "status": "PROVEN"}
  ],
  "scb": [
    {"id": "SB-CMDSCHED-HAZARD-001", "cell": "...", "exec": 1198, "matched": 1198, "mismatched": 0, "status": "PROVEN"}
  ],
  "case_status": "PARTIAL"
}
```

**规则**：

- 三集合必须与 `case_ir` 对应，缺项标 `MISSING`；
- 每个 group 按 `required_layers` 给状态；
- `case_status` 取最差层。

### 5. `coverage` 阶段：`case_view.*` 改成三节渲染

**现在**：七张人读视图。  
**改成**：至少三节 + 一个总状态：

```text
Case: TST-CMDSCHED-DEP-001   case_status: PARTIAL

[Groups]
| group | cell | functional | timing | data | path | result |
|---|---|---|---|---|---|---|
| CG-CMDSCHED-PATH | CELL-... | PROVEN | NA | NA | PENDING | PARTIAL |
| CG-CMDSCHED-CALC | CELL-... | PROVEN | PROVEN | PROVEN | NA | VERIFIED |
| CG-CMDSCHED-ARB  | CELL-... | PROVEN | NA | PROVEN | NA | VERIFIED |

[SVA]
| id | cell | hit | fail | cover_property_hit | status |
|---|---|---|---|---|---|
| SVA-CMDSCHED-DEP-001 | CELL-... | 1204 | 0 | 1204 | PROVEN |

[SCB]
| id | cell | exec | matched | mismatched | status |
|---|---|---|---|---|---|
| SB-CMDSCHED-HAZARD-001 | CELL-... | 1198 | 1198 | 0 | PROVEN |
```

### 6. `coverage` 阶段：`cell_matrix.json` 改成三集合反向填充

**现在**：`CELL = CG × P, green/yellow/red/na`。  
**改成**：每个 Cell 的 `evidence` 来自 case 的 groups/sva/scb。

```json
{
  "cell": "CELL-CMDSCHED-DEP-P-STORED-ISSUED",
  "group": "CG-CMDSCHED-DEP",
  "path": "P-CMDSCHED-STORED-ISSUED",
  "status": "yellow",
  "evidence": {
    "groups": [{"case": "TST-CMDSCHED-DEP-001", "functional": "PROVEN"}],
    "sva":   [{"case": "TST-CMDSCHED-DEP-001", "id": "SVA-CMDSCHED-DEP-001", "status": "PROVEN"}],
    "scb":   [{"case": "TST-CMDSCHED-DEP-001", "id": "SB-CMDSCHED-HAZARD-001", "status": "PROVEN"}]
  }
}
```

**状态映射**：

- 三集合全 PROVEN 且 required_layers 齐 → `green`；
- 任一项 PARTIAL/PENDING/NOT_APPLICABLE → `yellow`；
- 任一项 MISSING/UNMAPPED → `red`；
- 显式 `PENDING_BACKEND` 且已进 GAP → `na`。

### 7. `coverage` 阶段：`evd.json` 去重键扩到 checker 级

**现在**：去重键 `(run, tst, seed, cfg)`。  
**改成**：`(run, case, seed, cfg, checker_type, checker_id)`，`checker_type ∈ {group, sva, scb}`。  
这样一条 case 的多个 group/SVA/SCB 证据不会互相覆盖。

### 8. `coverage` 阶段：`gates.json` 增加三集合完整性门禁

新增门禁：

| 门禁 | 规则 | 级别 |
|---|---|---|
| `CASE_GROUPS_EMPTY` | `groups[]` 为空 | blocker |
| `CASE_SVA_UNDECLARED` | `sva` 字段缺失 | blocker |
| `CASE_SCB_UNDECLARED` | `scb` 字段缺失 | blocker |
| `CASE_SVA_NO_COVER_HIT` | `cover_property_hit=0` 且非 NA | blocker |
| `CASE_SCB_NOT_EXECUTED` | `exec=0` 且非 NA | blocker |
| `CASE_ITEM_NO_CELL` | group/sva/scb 任一缺 `cell` | blocker |
| `CASE_STATUS_OVERCLAIM` | `case_status=VERIFIED` 但存在非 PROVEN 项 | blocker |
| `CASE_IR_EVIDENCE_MISMATCH` | `case_cov` 三集合与 `case_ir` 不一致 | blocker |

### 9. `audit` 阶段：`caveats.json` 增加三集合相关 caveat

新增：

- `CASE_GROUP_PARTIAL`；
- `CASE_SVA_VACUOUS`；
- `CASE_SCB_NOT_EXECUTED`；
- `CASE_PATH_PENDING_BACKEND`；
- `CASE_IR_EVIDENCE_MISMATCH`。

`report.json` 的 `verdict` 仍由 `cell_matrix + gates + caveats` 决定，不由 `case_view` 决定。

## 三、目录与产物变化清单

```text
coverage/
├── case_ir.json                  # 改：三集合契约
├── case_cov/<stage>/<task>.json  # 改：三集合证据
├── case_view.{json,md,html}      # 改：三节渲染
├── cell_matrix.json              # 改：三集合反向填充
├── evd.json                      # 改：checker 级去重
├── gates.json                    # 改：加 8 条三集合门禁
└── ...                           # 其余不变
```

`ops` 侧只加 `task_meta.json` 的三集合指纹和 `case_ir_sha`，不改 `cov/*.db`、`waves/*.db`。

## 四、实施顺序

1. **先改 schema**：`case_ir` 三集合 schema、`case_cov` 三集合 schema。
2. **再改 `verify`**：`testpoints.yaml → case_ir.json` 生成器，强制三集合和 `cell`。
3. **再改 `ops`**：`task_meta.json` 加三集合指纹和 `case_ir_sha`。
4. **再改 `coverage`**：`case_cov` 三集合证据、`case_view` 三节、`cell_matrix` 反向填充、`evd` 去重键。
5. **最后改门禁**：`gates.json` 加 8 条规则，`audit` 加 caveat。
6. **回归验证**：拿一次已有 run 重跑 `evidence_pipeline --only coverage`，确认不重跑仿真能重建 `case_cov / case_view / cell_matrix / gates`。

## 五、一句话

**主链不动，只把 `case_ir` 和 `case_cov` 改成 `groups[] / sva[] / scb[]` 三集合契约与证据，`case_view` 按三节渲染，`cell_matrix` 由三集合反向填充，`evd` 去重键扩到 checker 级，`gates` 加 8 条三集合完整性门禁；`ops` 只加三集合指纹和 `case_ir_sha`。这样现有架构就能同时支撑“一个 case 多覆盖组证据视图”和“Cell 枢纽签核”。**