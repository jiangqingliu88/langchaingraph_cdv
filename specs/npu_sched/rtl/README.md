# RTL — CMDSCHED DUT

`npu_sched.sv` 是验证用的模型化 DUT：

- 端口与内部信号对齐 `docs/specs/cmdsched.md` 的接口表；
- 编码顺序与 `data/execution_model.yaml` 的 `values:` 顺序一致（改一边 = 改 bin 含义）；
- 只用于 `vagent vplan execute` 的 UVM/回归；不是量产 RTL。

它是执行层输入，不是规划层源数据。规划源仍是 `docs/specs/*.csv` +
`data/contract_matrix/`。
