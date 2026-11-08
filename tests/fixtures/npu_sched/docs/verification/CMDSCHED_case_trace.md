# CMD_SCH planned case layer

> 来源：`docs/specs/cmdsched.md`；由 `scripts/gen_spec_plan.py` 生成。
> spec_version: `初版` · spec_hash: `5f573c6cc7bbb910…` · plan_version: `0.1.0`
> case 全部为输入声明的状态；本层用于契约 → case → TP 的追溯，不参与执行门禁，当前无真实证据。

## 汇总

- planned cases: 12
- contracts covered: 42/42
- TPs assigned: 66/66

## Case 计划

| case | batch | owner | status | contracts | TPs | covergroups | checks |
|---|---|---|---|---|---|---|---|
| `TC_CMDSCHED_BASIC_001` | 1 | dv_cmd | planned | 4 | 7 | CG_CMDSCHED_ITYPE / CG_CMDSCHED_UNIT | sva_if_hs / cfg_scb / start_done_sva |
| `TC_CMDSCHED_ITYPE_001` | 2 | dv_func | planned | 3 | 2 | CG_CMDSCHED_ITYPE | decode_checker / exc_checker |
| `TC_CMDSCHED_INSTB_001` | 3 | dv_func | planned | 2 | 3 | CG_CMDSCHED_INSTB / CG_CMDSCHED_ISSUE | issue_scb / buffer_sva |
| `TC_CMDSCHED_DEP_001` | 4 | dv_func | planned | 5 | 5 | CG_CMDSCHED_DEP / CG_CMDSCHED_ISSUE | hazard_scb / hazard_sva / sync_scb |
| `TC_CMDSCHED_HAZARD_001` | 5 | dv_func | planned | 3 | 2 | CG_CMDSCHED_DEP / CG_CMDSCHED_UNIT | unit_scb / hazard_scb |
| `TC_CMDSCHED_PARALLEL_001` | 6 | dv_func | planned | 4 | 5 | CG_CMDSCHED_UNIT | unit_scb / tmu_arb_sva |
| `TC_CMDSCHED_MEM_001` | 7 | dv_res | planned | 6 | 9 | CG_CMDSCHED_MEM | res_model_scb / tile_sva |
| `TC_CMDSCHED_RSP_001` | 8 | dv_func | planned | 8 | 12 | CG_CMDSCHED_RSP | rsp_scb / tag_checker / prio_scb |
| `TC_CMDSCHED_EXCP_001` | 9 | dv_exc | planned | 6 | 8 | CG_CMDSCHED_EXCP / CG_CMDSCHED_CSR | exc_checker / int_scb |
| `TC_CMDSCHED_PERF_001` | 10 | dv_perf | planned | 3 | 3 | CG_CMDSCHED_PERF | perf_scb / debug_scb |
| `TC_CMDSCHED_CSR_001` | P1 | dv_csr | planned | 5 | 9 | CG_CMDSCHED_CSR | cfg_checker / lp_sva |
| `TC_CMDSCHED_REL_001` | P1 | dv_env | planned | 3 | 1 | CG_CMDSCHED_CSR | lp_sva / res_model_scb |

## Contract → case / TP

| contract | status | cases | TP count | TPs |
|---|---|---|---|---|
| `C-CFG-CIMC-001` | 已转 assume | TC_CMDSCHED_ITYPE_001, TC_CMDSCHED_CSR_001 | 1 | TP_CFG_CSR_002 |
| `C-CFG-CSR-001` | 已转 assume | TC_CMDSCHED_EXCP_001, TC_CMDSCHED_CSR_001 | 3 | TP_CMD_DEC_003, TP_CFG_CREG_001, TP_CFG_CSR_001 |
| `C-CFG-SPAD-EXCL-001` | 已转 assume | TC_CMDSCHED_CSR_001 | 1 | TP_CFG_CSR_004 |
| `C-CFG-TILE-RLS-001` | 已转 assume | TC_CMDSCHED_MEM_001, TC_CMDSCHED_CSR_001 | 1 | TP_CFG_CSR_003 |
| `C-DATA-RMW-001` | 已转 assume | TC_CMDSCHED_RSP_001 | 1 | TP_MEM_LMEM_002 |
| `C-DATA-SYNC-001` | 已转 assume | TC_CMDSCHED_DEP_001 | 1 | TP_SCHED_SH_004 |
| `C-DATA-TAG-001` | 已转 assume | TC_CMDSCHED_RSP_001 | 2 | TP_RSP_XD1_002, TP_RSP_XD1_003 |
| `C-DATA-VS-001` | 已转 assume | TC_CMDSCHED_RSP_001 | 1 | TP_MEM_LMEM_001 |
| `C-DBG-REG-001` | 已转 assume | TC_CMDSCHED_PERF_001 | 1 | TP_DBG_REG_001 |
| `C-EXC-ADDR-001` | 已转 assume | TC_CMDSCHED_EXCP_001 | 2 | TP_MEM_LMEM_003, TP_EXC_ADDR_001 |
| `C-EXC-BLOCK-001` | 已转 assume | TC_CMDSCHED_EXCP_001 | 1 | TP_EXC_BLOCK_001 |
| `C-EXC-CLEAR-001` | 已转 assume | TC_CMDSCHED_EXCP_001 | 1 | TP_EXC_INT_002 |
| `C-EXC-ILLEGAL-001` | 已转 assume | TC_CMDSCHED_ITYPE_001, TC_CMDSCHED_EXCP_001 | 2 | TP_CMD_DEC_004, TP_EXC_ILL_001 |
| `C-EXC-INT-001` | 已转 assume | TC_CMDSCHED_EXCP_001, TC_CMDSCHED_REL_001 | 2 | TP_EXC_ILL_002, TP_EXC_INT_001 |
| `C-FUNC-DEP-002` | 已转 assume | TC_CMDSCHED_DEP_001 | 2 | TP_SCHED_SH_001, TP_SCHED_SH_005 |
| `C-FUNC-DEP-003` | 已转 assume | TC_CMDSCHED_DEP_001 | 1 | TP_SCHED_SH_003 |
| `C-FUNC-DEP-004` | 已转 assume | TC_CMDSCHED_DEP_001 | 1 | TP_SCHED_SH_002 |
| `C-FUNC-DEP-006` | 已转 assume | TC_CMDSCHED_DEP_001, TC_CMDSCHED_HAZARD_001 | 3 | TP_SCHED_DH_001, TP_SCHED_DH_002, TP_SCHED_DH_003 |
| `C-FUNC-ISSUE-001` | 已转 assume | TC_CMDSCHED_INSTB_001 | 3 | TP_SCHED_ISSUE_001, TP_SCHED_ISSUE_002, TP_SCHED_ISSUE_003 |
| `C-FUNC-RSP-001` | 已转 assume | TC_CMDSCHED_RSP_001 | 1 | TP_RSP_XD1_004 |
| `C-FUNC-RSP-002` | 已转 assume | TC_CMDSCHED_RSP_001 | 2 | TP_RSP_XD1_001, TP_RSP_BP_002 |
| `C-FUNC-RSP-003` | 已转 assume | TC_CMDSCHED_RSP_001 | 1 | TP_MEM_LMEM_004 |
| `C-FUNC-UNIT-001` | 已转 assume | TC_CMDSCHED_BASIC_001, TC_CMDSCHED_ITYPE_001 | 4 | TP_CMD_DEC_001, TP_CMD_DEC_002, TP_CMD_OST_001, TP_CFG_START_001 |
| `C-FUNC-UNIT-002` | 已转 assume | TC_CMDSCHED_PARALLEL_001 | 1 | TP_PAR_LS_001 |
| `C-FUNC-UNIT-003` | 已转 assume | TC_CMDSCHED_PARALLEL_001 | 1 | TP_PAR_LS_002 |
| `C-FUNC-UNIT-004` | 已转 assume | TC_CMDSCHED_HAZARD_001 | 1 | TP_PAR_MST_002 |
| `C-FUNC-UNIT-005` | 已转 assume | TC_CMDSCHED_HAZARD_001, TC_CMDSCHED_PARALLEL_001 | 1 | TP_PAR_MST_001 |
| `C-IF-DONE-001` | 已转 assume | TC_CMDSCHED_BASIC_001 | 1 | TP_CFG_START_003 |
| `C-IF-HS-001` | 已转 assume | TC_CMDSCHED_BASIC_001, TC_CMDSCHED_INSTB_001 | 3 | TP_CMD_HS_001, TP_CMD_HS_002, TP_CMD_OST_002 |
| `C-IF-HS-002` | 已转 assume | TC_CMDSCHED_RSP_001 | 1 | TP_RSP_BP_001 |
| `C-IF-START-001` | 已转 assume | TC_CMDSCHED_BASIC_001 | 1 | TP_CFG_START_002 |
| `C-LP-IDLE-001` | 已转 assume | TC_CMDSCHED_CSR_001 | 2 | TP_LP_ICG_001, TP_LP_ICG_002 |
| `C-LP-RST-001` | 已转 assume | TC_CMDSCHED_REL_001 | 2 | TP_LP_RST_001, TP_LP_RST_002 |
| `C-PERF-PARAL-001` | 已转 assume | TC_CMDSCHED_PERF_001 | 1 | TP_PERF_CNT_001 |
| `C-PERF-PRIO-001` | 已转 assume | TC_CMDSCHED_RSP_001 | 1 | TP_RSP_PRIO_001 |
| `C-PERF-START-DONE-001` | 已转 assume | TC_CMDSCHED_PERF_001 | 1 | TP_PERF_CNT_002 |
| `C-PERF-TMU-001` | 已转 assume | TC_CMDSCHED_PARALLEL_001 | 2 | TP_PAR_TMU_001, TP_PAR_TMU_002 |
| `C-RES-DRAM-001` | 已转 assume | TC_CMDSCHED_MEM_001 | 2 | TP_SCHED_RANGE_002, TP_MEM_PD_002 |
| `C-RES-PAGE-001` | 已转 assume | TC_CMDSCHED_MEM_001 | 1 | TP_MEM_PD_001 |
| `C-RES-RLS-001` | 已转 assume | TC_CMDSCHED_MEM_001 | 1 | TP_MEM_REL_001 |
| `C-RES-SPAD-001` | 已转 assume | TC_CMDSCHED_MEM_001 | 1 | TP_MEM_SHARE_001 |
| `C-RES-TILE-001` | 已转 assume | TC_CMDSCHED_MEM_001, TC_CMDSCHED_REL_001 | 4 | TP_SCHED_RANGE_001, TP_MEM_TILE_001, TP_MEM_TILE_002, TP_MEM_REL_002 |
