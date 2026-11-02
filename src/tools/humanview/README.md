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
python -m pytest src/tools/humanview/aivm_ir/tests -q
```

- `test_bridge.py`：绑定 / 映射 / 丢弃 / 双哈希 / CLI 端到端（合成 + 真表）；
- `test_xlsx_example.py`：示例表 64 TP 对齐、重复 id 不合并、往返守恒、M1 编译。
