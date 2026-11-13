# humanview —— 人维护的文档/表格 → 机器可执行契约

## 定位（方案 B）

```text
xlsx（PM/DV lead 手写测试点表）    ← 真源：该测什么、评审、diff
    │  aivm_ir.bridge.import_ontology()
    ▼
casemodel.yaml                     ← 执行契约：怎么测（过 JSON Schema 硬门禁）
    │
source_map.json                    ← 双向出处 + xlsx/casemodel 双哈希（防漂移）
    ▼
现有 TP IR → test / covergroup / tp_matrix / 签核
```

**职责分层**：xlsx 决定"该测什么"，casemodel 决定"怎么测"。
不让 xlsx 直接驱动执行——表里没有激励字段、约束语义和信号归属，硬解析等于猜。

## `case_ir`（CCAT / CASE 身份层）

案例模型的 `cases:` 段（人声明）或按结构合成（`source=synthesized`）→
`CaseDoc`（分类树 + 用例 + `test/维度 → case_id` 反查）。

- **TST / EVD 不是实体**：id 由 `test + seed` 派生（`tst_id_of` / `evd_id_of`），一处生成；
- 生成期注入：`verify` 把 `case_id/tst_id` 写进 TP IR，回归目录写进
  `task_meta.json`（`regression_task_v2`），证据聚合写 `evd_id/cell_ids`；
- 校验：`validate_case_doc()`（ID 唯一、引用存在、CASE 落得到执行实例）。

配套：`coverage_tools/cell_matrix.py`（`CELL = CG × P`，四色状态）、
`coverage_tools/evd.py`、`case_associate_view/gates.py`（blocker/warning/info）。
设计与落地状态见 `docs/design/architecture_transformation_plan.md`。

## `aivm_ir`（ontology + M1 计划编译器）

- `xlsx_loader` / `xlsx_writer`：表 ↔ `Ontology` 往返；
- `ir_core`：`TestPointIR` / `CoverageCell`（一格一候选覆盖点）/ 枚举化分类；
- `validate`：约束提取、分类自洽、覆盖驱动一致性；
- `plan_compiler_m1`：三通道出计划（cover_bin / config_enum / directed_case）；
- `bridge`：`bind_cells` → `to_casemodel` → `import_ontology` / `verify_import`。

## 用法

```bash
# xlsx 自带维度轴时直接导入；没有轴就补一份 sidecar（见 example/axes.example.yaml）
vagent case-model import-xlsx NPU.xlsx --module npu_cmdsched --axes axes.yaml
vagent case-model verify-import NPU.xlsx \
       specs/npu_cmdsched/casemodel.yaml specs/npu_cmdsched/source_map.json \
       --axes axes.yaml
```

**轴声明 sidecar**（`aivm_axes_v1`）：真实 xlsx 只写 TP 行与格子文本，loader 不建
维度；sidecar 把格子拆成验证轴，组合格才变成真正的交叉仓。

```yaml
schema: aivm_axes_v1
tps:
  IF02:
    dimensions:
      - id: start_order
        values:
          - {value: s0_first, raw_text: "start_id0 先于start_id1"}
          - {value: s1_first, raw_text: "start_id0 后于start_id1"}
      - id: done_order
        values:
          - {value: d0_first, raw_text: "done_id0先于done_id1"}
          - {value: d1_first, raw_text: "done_id0后于done_id1"}
```

轴里声明、但该 TP 的格子里**没出现**的值会被记账（`unmatched`）并丢弃 ——
表是"该测什么"的真源，不凭空多出覆盖点。

```python
from src.tools.humanview.aivm_ir import load_xlsx_to_ontology
from src.tools.humanview.aivm_ir.bridge import import_ontology

onto = load_xlsx_to_ontology("NPU.xlsx")
result = import_ontology(onto, "specs/npu_cmdsched",
                         module_name="npu_cmdsched", source_path="NPU.xlsx")
```

## 映射规则（实现见 `aivm_ir/bridge.py`）

| xlsx / AIVM | casemodel |
|---|---|
| `Category` | `sub_objects` 一级节点 |
| `TestPointIR`（A 列一行） | `sub_objects` 叶子 + 一条 `themes` |
| `Dimension` / `DimensionValue` | `dimensions[].fields`（一值一仓；`sample` 不写，不冒充可驱动） |
| `CONSTRAINT_COMBO` + 轴声明（二维） | `cross_matrix` 的显式 `bins[{name, when}]`，一格一仓（**真交叉**） |
| `CONSTRAINT_COMBO`（无维度轴） | **场景维度** `D_<tp>_scenario`（一格一仓，不冒充交叉） |
| `CONFIG_ENUM` | 独立枚举维度，一值一仓 |
| `DIRECTED_CASE` | 独立 `case` 维度 + `method: D` + `theme.test` |
| `test_num` / `test_name` / `checks` | `theme.repeat` / `theme.test` / `theme.checks` |
| `legality` / 原文 | `source_map.json`（不硬造 illegal bin） |

## 三条纪律

1. **不静默丢格**：绑不上、超过二维、无 material 的格子进 `source_map.dropped`；
2. **生成的 casemodel 必须过 `run_validate`（0 error）** 才写盘；
3. **双哈希**：`source_map.inputs.xlsx_sha256` / `outputs.casemodel_sha256`，
   `verify-import` 比对，单边改动会被查出来。

## 当前边界

- 真实 xlsx **不自带维度建模**（loader 不建 `Dimension`）→ 没给轴声明时
  组合格退化成场景维度；给了 `--axes` 才是真交叉覆盖（`example/axes.example.yaml`）；
- 中文自由文本的分类仍是启发式（`CellType.classify`），新增表格式要补规则；
- `M1` 只出计划，不生成 UVM/覆盖率库；
- 继承的 `load_xlsx_to_ontology` 圈复杂度 52/59，已登记基线（改动前先拆）。

## 测试

```bash
python -m pytest src/runtime_plane/tools/humanview/aivm_ir/tests -q
```

- `test_bridge.py`：绑定 / 映射 / 丢弃 / 双哈希 / CLI 端到端（合成 + 真表）；
- `test_xlsx_example.py`：示例表 64 TP 对齐、重复 id 不合并、往返守恒、M1 编译。

## `covg_ir` / `sva_ir` / `scb_ir`（方法学 IR）

三份**人维护的 YAML IR**，对应同目录 `arch.md` 的三套方法学：

| 包 | 回答 | 必填骨架 | CLI |
|---|---|---|---|
| `covg_ir` | 功能组 × 生命周期路径的纵横矩阵 | 组有需求/覆盖点/矩阵归属；路径有 SVA+SB+定向序列；跨组交叉有实现方式 | `vagent humanview covg <yaml>` |
| `sva_ir` | 契约 → 七类 SVA → 格子/路径 | contract/class/antecedent/consequent/cover_property/bound_cells | `vagent humanview sva <yaml>` |
| `scb_ir` | 契约 → 五类 SCB → 格子 | contract/class/model/expected_source/execute_count/bound_cells | `vagent humanview scb <yaml>` |

共同纪律：

- **声明自洽 ≠ 仿真命中**：IR 只判"有没有建模、有没有 checker、有没有执行"；
  命中率仍来自 ucdb / 仿真日志；
- `covg_ir` 的矩阵格子：缺 SVA/SCB → 🔴，有 checker 但未签核 → 🟡，两边签核 → 🟢；
- `sva_ir` 的 `hit_count == 0` 是 **vacuous pass**，判 error；
- `scb_ir` 的 `execute_count == 0` 判 error；期望来源与 DUT 自身相同时告警；
- 三份 IR 都输出 `{ok, errors, warnings, metrics, details}`，并可用 `--markdown`
  生成评审视图（矩阵 / 分解树 / 缺口）。

示例（最小）：

```bash
vagent humanview covg coverage_model/covg.yaml --markdown
vagent humanview sva  coverage_model/sva.yaml  --json
vagent humanview scb  coverage_model/scb.yaml
```
