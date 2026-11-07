# data — spec-first 编辑源

当前工作区只保留 spec target plan 需要的契约矩阵和占位视图；cg/cp/cross/constraint/batch/asset/exemption 等执行层数据尚未落地。

| 文件/目录 | 属性 | 谁写 | 说明 |
|---|---|---|---|
| `contract_matrix/*.csv` | 输入 | 人 | 42 条 spec 契约，13 列固定，当前全部 `assume` |
| `case_plan_view.html` | 生成占位视图 | `gen_planned_case_view.py` | 12 个 planned case，PLACEHOLDER / NOT RUN，不是证据 |

## 契约矩阵

- 按 class 分文件：`if/func/data/perf/cfg/res/exc/dbg/lp`；
- 42 行，无 active、无 exempt；
- `check_artifact` 为占位（`spec_<class>_artifact`），待真实 SVA/Checker/SCB/coverage 资产；
- `gate=gate_matrix`，但当前没有执行门禁；assume 只校验 assumption；
- 字段语义见 `contract_matrix/README.md` 和 `../docs/contract/C01_contract_matrix.md`。

## 规则

- 契约矩阵是权威源；case/TP 只引用 `contract_id`，不复制字段。
- 新增/修改契约需 owner 评审。
- 当前没有真实证据；任何 `active` 状态都必须先补 case、声明资产和运行证据。
- 生成/校验脚本只读 `docs/specs` 和 `contract_matrix`，不修改输入。
