# cases — VPlan case 契约

每个 `TC_CMDSCHED_*.yaml` 对应 `docs/specs/cmdsched_cases.csv` 的一行：

| 字段 | 含义 |
|---|---|
| `case_id` | VPlan case 身份（`TC_*`） |
| `test_name` | UVM test 类名（由执行模型生成批次 test） |
| `contract_refs` | 本 case 要证明的 `C-*` 契约 |
| `covergroups` | 覆盖组名（执行资产/后续 SV 资产） |
| `checks` | 检查资产（`sva` / `scb` / `checker`） |
| `vplan_status` | `planned` / `implemented` / `signed_off` / `blocked` |
| `seed_baseline` | 基线种子（当前每 case 1 颗，先打通链路） |
| `stimulus` | 激励 profile（当前 `random`，由执行模型展开到事务字段） |

当前全部 `planned`。执行层跑出证据后，case 才可能转 `implemented`/`signed_off`。
