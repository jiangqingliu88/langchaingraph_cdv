# CMD_SCH spec target plan — feature 拆分树 × 专题

> 来源：`docs/specs/cmdsched.md`
> spec_version: `初版` · spec_hash: `5f573c6cc7bbb910…` · plan_version: `0.1.0`
> 由 `scripts/gen_spec_plan.py` 从 `docs/specs/cmdsched_*.csv` 生成；不要手改。
> 所有测试点状态来自输入；target plan 不参与执行门禁，当前没有可执行证据。

| 编号 | feature | 接口 | 时钟复位 | 参数和配置 | 数据值域 | 数据形状 | 错误异常 | 中间复位 | 边界 | 流控和反压 | 性能长稳 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **CMDSCHED** (root) | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ | ↳ |
| 1.1 | CMD_IN (branch) | ↳ | N/A | ↳ | ↳ | ↳ | ↳ | N/A | ↳ | ↳ | N/A |
| 1.1.1 | HS | `TP_CMD_HS_001` (planned) | N/A | N/A | N/A | N/A | N/A | N/A | N/A | `TP_CMD_HS_002` (planned) | N/A |
| 1.1.2 | DECODE | N/A | N/A | `TP_CMD_DEC_003` (planned) | `TP_CMD_DEC_001` (planned) | `TP_CMD_DEC_002` (planned) | `TP_CMD_DEC_004` (planned) | N/A | N/A | N/A | N/A |
| 1.1.3 | OST2 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | `TP_CMD_OST_001` (planned) | `TP_CMD_OST_002` (planned) | N/A |
| 1.2 | SCHED (branch) | ↳ | N/A | N/A | ↳ | ↳ | ↳ | N/A | ↳ | N/A | N/A |
| 1.2.1 | SH | N/A | N/A | N/A | `TP_SCHED_SH_004` (planned) | `TP_SCHED_SH_001` (planned)<br>`TP_SCHED_SH_002` (planned)<br>`TP_SCHED_SH_003` (planned) | `TP_SCHED_SH_005` (planned) | N/A | N/A | N/A | N/A |
| 1.2.2 | DH | N/A | N/A | N/A | `TP_SCHED_DH_002` (planned) | `TP_SCHED_DH_001` (planned) | `TP_SCHED_DH_003` (planned) | N/A | N/A | N/A | N/A |
| 1.2.3 | RANGE | N/A | N/A | N/A | N/A | `TP_SCHED_RANGE_001` (planned) | N/A | N/A | `TP_SCHED_RANGE_002` (planned) | N/A | N/A |
| 1.2.4 | ISSUE | `TP_SCHED_ISSUE_001` (planned) | N/A | N/A | N/A | `TP_SCHED_ISSUE_003` (planned) | N/A | N/A | `TP_SCHED_ISSUE_002` (planned) | N/A | N/A |
| 1.3 | PAR (branch) | N/A | N/A | N/A | N/A | ↳ | N/A | N/A | ↳ | ↳ | N/A |
| 1.3.1 | MST | N/A | N/A | N/A | N/A | `TP_PAR_MST_001` (planned) | N/A | N/A | `TP_PAR_MST_002` (planned) | N/A | N/A |
| 1.3.2 | LS | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | `TP_PAR_LS_001` (planned)<br>`TP_PAR_LS_002` (planned) | N/A |
| 1.3.3 | TMU | N/A | N/A | N/A | N/A | N/A | N/A | N/A | `TP_PAR_TMU_002` (planned) | `TP_PAR_TMU_001` (planned) | N/A |
| 1.4 | MEM (branch) | N/A | N/A | N/A | ↳ | ↳ | ↳ | N/A | ↳ | N/A | N/A |
| 1.4.1 | TILE | N/A | N/A | N/A | N/A | `TP_MEM_TILE_001` (planned) | N/A | N/A | `TP_MEM_TILE_002` (planned) | N/A | N/A |
| 1.4.2 | PAGEDRAM | N/A | N/A | N/A | N/A | `TP_MEM_PD_001` (planned) | N/A | N/A | `TP_MEM_PD_002` (planned) | N/A | N/A |
| 1.4.3 | SHARE | N/A | N/A | N/A | N/A | `TP_MEM_SHARE_001` (planned) | N/A | N/A | N/A | N/A | N/A |
| 1.4.4 | RELEASE | N/A | N/A | N/A | N/A | N/A | `TP_MEM_REL_002` (planned) | N/A | `TP_MEM_REL_001` (planned) | N/A | N/A |
| 1.4.5 | LMEM | N/A | N/A | N/A | `TP_MEM_LMEM_001` (planned)<br>`TP_MEM_LMEM_004` (planned) | `TP_MEM_LMEM_002` (planned) | `TP_MEM_LMEM_003` (planned) | N/A | N/A | N/A | N/A |
| 1.5 | RSP (branch) | ↳ | N/A | N/A | ↳ | ↳ | ↳ | N/A | ↳ | ↳ | N/A |
| 1.5.1 | XD1 | `TP_RSP_XD1_001` (planned) | N/A | N/A | `TP_RSP_XD1_002` (planned)<br>`TP_RSP_XD1_004` (planned) | N/A | `TP_RSP_XD1_003` (planned) | N/A | N/A | N/A | N/A |
| 1.5.2 | PRIO | N/A | N/A | N/A | N/A | `TP_RSP_PRIO_001` (planned) | N/A | N/A | N/A | N/A | N/A |
| 1.5.3 | BP | N/A | N/A | N/A | N/A | N/A | N/A | N/A | `TP_RSP_BP_002` (planned) | `TP_RSP_BP_001` (planned) | N/A |
| 1.6 | EXC (branch) | ↳ | N/A | N/A | ↳ | N/A | ↳ | N/A | ↳ | ↳ | N/A |
| 1.6.1 | ILLEGAL | N/A | N/A | N/A | `TP_EXC_ILL_001` (planned) | N/A | `TP_EXC_ILL_002` (planned) | N/A | N/A | N/A | N/A |
| 1.6.2 | ADDR | N/A | N/A | N/A | N/A | N/A | `TP_EXC_ADDR_001` (planned) | N/A | N/A | N/A | N/A |
| 1.6.3 | INT | `TP_EXC_INT_001` (planned) | N/A | N/A | N/A | N/A | N/A | N/A | `TP_EXC_INT_002` (planned) | N/A | N/A |
| 1.6.4 | BLOCK | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | `TP_EXC_BLOCK_001` (planned) | N/A |
| 1.7 | CFG (branch) | ↳ | N/A | ↳ | N/A | ↳ | N/A | N/A | ↳ | N/A | N/A |
| 1.7.1 | START | `TP_CFG_START_002` (planned)<br>`TP_CFG_START_003` (planned) | N/A | `TP_CFG_START_001` (planned) | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| 1.7.2 | COREREG | N/A | N/A | `TP_CFG_CREG_001` (planned) | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| 1.7.3 | CSRCIMC | N/A | N/A | `TP_CFG_CSR_001` (planned)<br>`TP_CFG_CSR_004` (planned) | N/A | `TP_CFG_CSR_002` (planned) | N/A | N/A | `TP_CFG_CSR_003` (planned) | N/A | N/A |
| 1.8 | DBGPERF (branch) | ↳ | N/A | N/A | N/A | N/A | N/A | N/A | N/A | ↳ | ↳ |
| 1.8.1 | DBG | `TP_DBG_REG_001` (planned) | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| 1.8.2 | PERF | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A | `TP_PERF_CNT_001` (planned) | `TP_PERF_CNT_002` (planned) |
| 1.9 | LP (branch) | N/A | ↳ | N/A | N/A | N/A | N/A | ↳ | ↳ | N/A | N/A |
| 1.9.1 | ICG | N/A | `TP_LP_ICG_001` (planned) | N/A | N/A | N/A | N/A | N/A | `TP_LP_ICG_002` (planned) | N/A | N/A |
| 1.9.2 | RST | N/A | `TP_LP_RST_002` (planned) | N/A | N/A | N/A | N/A | `TP_LP_RST_001` (planned) | N/A | N/A | N/A |

## 图例

- 无后缀：`covered`
- `(planned)` / `(exempt)` / `(out_of_scope)`：输入声明的状态
- `↳`：父 feature 的专题由子 feature 汇总
- `N/A`：该 feature 不适用该专题
- `**GAP**`：适用但无测试点

## 统计

- spec 需求：20
- feature 节点：39
- 测试点：66
- 专题：10
- spec 契约：42（已推进）
- planned case：12
- 未被 TP 使用的 spec 契约：0
