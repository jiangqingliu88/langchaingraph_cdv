# verification — CMD_SCH Spec Target Plan

本目录是从 `docs/specs/cmdsched.md` 分析得到的 **CMD_SCH 目标验证计划**。执行层尚未接入；当前没有运行证据。

## 文件

| 文件 | 内容 | 状态 |
|---|---|---|
| `CMDSCHED_spec_analysis.md` | Spec 分析：变更需求、架构、接口、Feature List、约束、异常、性能、风险 | 分析结论 |
| `CMDSCHED_vplan.md` | 验证计划：黑盒 feature 树、专题、TP、契约、planned case、签核 | 目标计划 |
| `CMDSCHED_features.csv` | 39 节点 feature 树（1 root + 9 branch + 29 leaf） | 目标数据 |
| `CMDSCHED_topics.csv` | 10 个专题 | 目标数据 |
| `CMDSCHED_testpoints.csv` | 66 个 planned 测试点 | 目标数据 |
| `CMDSCHED_contracts.csv` | 42 条 spec 契约（全部已转 `assume`） | 目标数据 |
| `CMDSCHED_cases.csv` | 12 个 planned case | 计划层 |
| `CMDSCHED_matrix.md` | feature × 专题矩阵 | 生成视图 |
| `CMDSCHED_case_trace.md` | contract → case → TP 追溯 | 生成视图 |
| `CMDSCHED_impact.md` | 最近一次输入/输出变更 | 变更报告 |

## 状态

```text
requirements: 20
features:     39
topics:       10
testpoints:   66  (planned)
contracts:    42  (assume, in data/contract_matrix)
cases:        12  (planned)
evidence:     0
signoff:      not ready
```

- 42 条 spec 契约已全部写入 `data/contract_matrix/`，状态均为 `assume`；
- 没有 active 契约、没有 exempt 契约、没有仿真证据；
- 12 个 planned case 覆盖 42/42 契约、66/66 TP；
- `data/case_plan_view.html` 是占位视图（PLACEHOLDER / NOT RUN），不是签核依据。

## 组织模型

```text
1 个主 feature
  × 10 个专题
    → 测试点（feature × 专题）
      → planned case
        → 待实现的 SVA/Checker/SCB/覆盖率
          → 待采集的 VCS/URG 证据
```

feature 树按黑盒路径/资源/并行/竞争/时序拆分；专题包括接口、时钟复位、参数配置、数据值域、数据形状、错误异常、中间复位、边界、流控反压、性能长稳。

## 生成与校验

```bash
cd demo
python scripts/gen_spec_plan.py
python scripts/gen_spec_plan.py --check
python scripts/lint_spec_trace.py
python scripts/gen_planned_case_view.py
```

输入与换 spec 流程见 `../specs/README.md`。生成器会校验 spec 哈希、需求追溯、feature 树、TP/case/契约引用和生成物一致性；spec hash 不匹配时拒绝生成。

## 与“签核”的关系

当前只有计划层：

- 没有 VCS/UVM/URG；
- 没有代码覆盖/功能覆盖/断言覆盖；
- 没有 SCB/Checker/SVA 运行日志；
- 没有波形。

因此**不可签核**。下一步应先做 `TC_CMDSCHED_RSP_001` 样板，把真实证据补进来。
