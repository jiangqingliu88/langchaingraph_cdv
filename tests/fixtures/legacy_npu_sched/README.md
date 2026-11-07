# Legacy NPU scheduler fixtures

These files were the old `specs/npu_sched/` casemodel and DUT:

- `casemodel.yaml` — case 属性模型（12 覆盖点 / 7 交叉 / 11 批次）
- `npu_sched.sv` — 旧 DUT（端口表 / 覆盖率接口用）

`specs/npu_sched/` 已改为 AI VPlan spec-first 项目（`docs/specs/*.csv` +
`data/contract_matrix/`），不再有 `casemodel.yaml`。这里保留的是**回归测试夹具**，
用于继续覆盖 casemodel 代码路径，不是项目输入，也不会被执行流程读取。

新流程请使用 `vagent vplan build specs/npu_sched`。
