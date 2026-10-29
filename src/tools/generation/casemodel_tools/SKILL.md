# casemodel_tools skill

## 什么时候用我

- 把规格/需求拆成**测试点**（维度 × 取值）；
- 生成 TP IR（`coverage/testpoints.yaml`、`methodology.json`）；
- 从 case 模型生成 UVM tests / covergroups / 覆盖率计划 / 约束草案；
- 做三模型关联（case / coverage / constraint）与完备性检查。

## 不要用我

- 想直接跑仿真/回归 → `execution/regression_tools`；
- 想看某个 bin 的 hit 数 → `checking/coverage_tools`；
- 想改测试点实现方式 → 改 case 模型的 `realization` / `stimulus`，不要改生成器。

## 正确调用方式

```bash
# 校验 / 完备性
python -m src.tools.generation.casemodel_tools.cli check   <model.yaml>
python -m src.tools.generation.casemodel_tools.cli analyze <model.yaml>

# 生成
python -m src.tools.generation.casemodel_tools.cli generate      <model.yaml>
python -m src.tools.generation.casemodel_tools.cli uvm-tests     <model.yaml>
python -m src.tools.generation.casemodel_tools.cli coverage-plan <model.yaml>

# 关联 / 约束
python -m src.tools.generation.casemodel_tools.cli associate   --cases <case.yaml> --coverage <cov.yaml>
python -m src.tools.generation.casemodel_tools.cli constraints <model.yaml>
```

Python API：

```python
from src.tools.generation.casemodel_tools.api import run_gaps, run_generate, run_testpoints
from src.tools.generation.casemodel_tools.associate import associate, build_constraint
```

## 关键概念

- **一条取值点 = 一条测试点**；`tp_id` 是整条链的主键。
- **realization 四分类**：
  - `stimulus`：落到事务字段；
  - `sequence`：多条事务时序，需要 `realization.sequences.<取值>` 给逐笔值；
  - `observe`：DUT 内部量/输出，只采覆盖；
  - `backdoor`：`uvm_hdl_force(path, value)` → 采样 → release。
- `fields[].name` 是**观测点**；`stimulus.field` 才是**驱动字段**，两者不要混。

## 常见错误

| 现象 | 原因 | 处理 |
|---|---|---|
| 属性 test 生成了但激励没变 | 维度没写 `stimulus.field` | 在模型里补 `stimulus: {field: <seq_item 字段>}` |
| `stimulus.field` 不生效 | 字段不在任何 master agent 的 seq_item | 用 `associate` 对 agent 字段；改字段名 |
| `sequence` 测试点没进回归 | 只有 `realization.sequence`，没有 `sequences` 逐笔值 | 补 `realization.sequences.<取值>: [..]` |
| `method: X` 被静默归一成空 | 方法名不在 `METHOD_TO_POLICY` | 用 `D/G/SPCL/RND/RPLY`；`associate` 边 ④ 会报 |
| 覆盖 bin 对不上 | `cover_bins` 名字与覆盖率模型不一致 | `associate` 边 ① 会报 missing bin |
| `UNMAPPED` 出现在 TP 矩阵 | 模型给的 coverpoint/bin 在报告里找不到 | 重新生成覆盖率模型 / 检查 dimension 名 |

## 产物

| 文件 | 用途 |
|---|---|
| `coverage/testpoints.yaml` / `.json` | TP IR（人读 / 机器读） |
| `coverage/methodology.json` | 阶段、计数、输入、IR sha256 |
| `coverage/coverage_plan.yaml` | 覆盖点/bin/cross/批次/种子 + `constraint_backing` |
| `coverage/constraint_status.json` | 约束逐条 backed 状态 |
| `coverage/association_report.json` | 三模型关联断点 |
