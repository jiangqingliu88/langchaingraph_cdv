# execution_model.yaml — 执行资产

这份文件不是旧的 `casemodel.yaml` 项目输入，而是 VPlan 的执行资产层：

- `dimensions` / `fields`：事务/观测字段与取值（12 个维度，含枚举/区间/边界）；
- `assertions` / `scoreboards` / `behavior`：断言、比对与队列行为；
- `cross_matrix`：覆盖交叉；
- `sampling` / `object` / `object_code`：DUT 绑定与 TP 命名。

它**不含** `themes` / `cases`：批次与测试名在 `cases/*.yaml`（VPlan case 契约），
`vagent vplan execute` 会把两者合成运行期 `<run>/inputs/casemodel.yaml`，
只写进 run，不写回项目。

状态纪律：case 仍是 `planned`，契约仍是 `assume`；执行产出证据后，还需要
`vplan gate` 才能推进状态。
