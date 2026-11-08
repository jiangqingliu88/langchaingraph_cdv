# data — spec-first 编辑源

当前工作区包含 spec target plan、契约矩阵和 CSV 执行资产；运行时模型只在
`vplan execute` 的临时目录里组装，不落 case-model YAML。

| 文件/目录 | 属性 | 谁写 | 说明 |
|---|---|---|---|
| `contract_matrix/*.csv` | 输入 | 人 | 42 条 spec 契约，13 列固定，当前 8 `active` / 34 `assume` |
| `case_plan_view.html` | 生成占位视图 | `gen_planned_case_view.py` | 12 个 planned case，PLACEHOLDER / NOT RUN，不是证据 |
| `dimensions.csv` / `assertions.csv` / `scoreboards.csv` | 执行资产（CSV） | 人 | 维度/字段/断言/SCB；见 `execution_assets.README.md` |
| `cross_matrix.csv` / `behavior.csv` / `config_space.csv` | 执行资产（CSV） | 人 | 交叉覆盖 / 行为域 / 配置空间（复杂字段用 JSON 列） |
| `sub_objects.csv` / `execution_meta.csv` | 执行资产（CSV） | 人 | 功能子对象树 / object 与 sampling 元数据 |

## 契约矩阵

- 按 class 分文件：`if/func/data/perf/cfg/res/exc/dbg/lp`；
- 42 行：8 `active` / 34 `assume`，无 exempt；
- `check_artifact` 为占位（`spec_<class>_artifact`），待真实 SVA/Checker/SCB/coverage 资产；
- `gate=gate_matrix`，但当前没有执行门禁；assume 只校验 assumption；
- 字段语义见 `contract_matrix/README.md` 和 `../docs/contract/C01_contract_matrix.md`。

## 规则

- 契约矩阵是权威源；case/TP 只引用 `contract_id`，不复制字段。
- 新增/修改契约需 owner 评审。
- `active` 由 `vagent vplan gate --apply` 依据 run 回归/TP/资产证据推进，不手改。
- 生成/校验脚本只读 `docs/specs` 和 `contract_matrix`，不修改输入。
