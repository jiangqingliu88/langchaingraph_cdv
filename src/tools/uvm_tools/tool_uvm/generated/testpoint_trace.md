# Testpoint Traceability — APB_env

Generated: 2026-09-05 19:57:01

| feature_id | id | feature | priority | tc_name | checker | func_coverage | policy | review |
|------------|----|---------|----------|---------|---------|---------------|--------|--------|
| APB_FEAT_WR | APB_TP_001 | APB back-to-back 写传输 | P0 | `APB_env_gen_test_APB_TP_001` | sb:apb_scb | apb_write_b2b_cross; apb_wr_err_cp | apb_policy_b2b | approved |
| APB_FEAT_ERR | APB_TP_002 | 错误响应注入 | P1 | `APB_env_gen_test_APB_TP_002` | sb:apb_scb; assert:assert_pslverr_ack | apb_err_resp_cp |  | reviewed |

## By Feature

### APB_FEAT_ERR

- `APB_TP_002` [P1] 错误响应注入 → `APB_env_gen_test_APB_TP_002`（reviewed）

### APB_FEAT_WR

- `APB_TP_001` [P0] APB back-to-back 写传输 → `APB_env_gen_test_APB_TP_001`（approved）

## Review Log

- 2026-09-05 张三: 通过（APB_TP_001） — 检查器与覆盖点齐全
