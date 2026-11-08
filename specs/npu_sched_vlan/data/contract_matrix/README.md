# contract_matrix — CMD_SCH spec 契约矩阵

当前共 **42 条 spec 契约**（8 `active` / 34 `assume`），来自 `docs/specs/cmdsched_contracts.csv`；`active` 由 `vagent vplan gate --apply` 依据 run 的回归/TP/资产证据推进（run `output_vplan_e2e_gate_jiang_20261107_130948`）。

| 文件 | class | 数量 | 例子 |
|---|---|---|---|
| `if.csv` | if | 4 | C-IF-HS-001、C-IF-HS-002、C-IF-START-001、C-IF-DONE-001 |
| `func.csv` | func | 13 | C-FUNC-UNIT-*、C-FUNC-DEP-*、C-FUNC-ISSUE-001、C-FUNC-RSP-* |
| `data.csv` | data | 4 | C-DATA-TAG-001、C-DATA-RMW-001、C-DATA-SYNC-001、C-DATA-VS-001 |
| `perf.csv` | perf | 4 | C-PERF-TMU-001、C-PERF-PRIO-001、C-PERF-PARAL-001、C-PERF-START-DONE-001 |
| `cfg.csv` | cfg | 4 | C-CFG-CSR-001、C-CFG-CIMC-001、C-CFG-TILE-RLS-001、C-CFG-SPAD-EXCL-001 |
| `res.csv` | res | 5 | C-RES-TILE-001、C-RES-PAGE-001、C-RES-DRAM-001、C-RES-SPAD-001、C-RES-RLS-001 |
| `exc.csv` | exc | 5 | C-EXC-ILLEGAL-001、C-EXC-ADDR-001、C-EXC-INT-001、C-EXC-CLEAR-001、C-EXC-BLOCK-001 |
| `dbg.csv` | dbg | 1 | C-DBG-REG-001 |
| `lp.csv` | lp | 2 | C-LP-IDLE-001、C-LP-RST-001 |

## 状态

```text
active:  0
assume:  42
exempt:  0
```

- 所有 `check_artifact` 为占位（`spec_<class>_artifact`）；
- 没有真实 SVA/Checker/SCB/coverage 资产；
- 没有 case 绑定和运行证据；
- 当前没有执行门禁。

## 规则

- 13 列顺序固定，字段见 `../README.md` 和 `docs/contract/C01_contract_matrix.md`。
- `contract_id` 全局唯一，正则见 `docs/appendix/X00_id_anchor_spec.md`。
- 转 `active` 必须同时具备：case 引用、`// ARTIFACT:` 锚点、运行期激活、证据；仅改状态不算生效。
- 当前没有 exempt；如后续需要豁免，必须写入 `data/exemption.csv` 并有理由/审批/有效期。
- 修改契约需 owner 评审；case/TP 只引用，不复制字段。
