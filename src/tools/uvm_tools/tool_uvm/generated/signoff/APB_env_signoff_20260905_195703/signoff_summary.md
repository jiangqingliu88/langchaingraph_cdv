# 签核证据包 — APB_env

- 打包时间: 20260905_195703
- 用例结果: 3 次执行，0 pass / 0 fail / 3 skip/other
- 输入文件: 6 个（YAML/xlsx，hash 见 manifest.json）
- 证据文件: 6 个（结果/校验/追溯，hash 见 manifest.json）

## 执行结果

- `APB_env_gen_test_APB_TP_001` seed=1: **skip**
- `APB_env_gen_test_APB_TP_001` seed=2: **skip**
- `APB_env_gen_test_APB_TP_001` seed=3: **skip**

## 校验警告

- [WARNING] tlm_connection_unknown_ref @ APB_env: tlm_connections.driver 'apb_slave.monitored_ap' references unknown 'apb_slave'
- [WARNING] policy_unknown_name @ apb_cons: policy 'apb_b2b_write' has no built-in apply body（自定义逻辑需手填）

## 追溯与证据

- 测试点 ↔ 用例 ↔ 约束/覆盖率映射: `evidence/testpoint_trace.md`
- 机器可读结果: `evidence/test_run_results.json`
- 生成/校验/merge/gate 报告: `evidence/generation_report.json`

完整 hash 清单见 `manifest.json`，任何文件被篡改均可在签核时检出。

