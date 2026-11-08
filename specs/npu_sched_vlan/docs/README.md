# docs — spec-first 文档索引

本工程从 `docs/specs/cmdsched.md` 出发，产出 CMD_SCH target plan。执行层尚未接入；当前只有 spec target plan，没有运行证据。

| 文档 | 作用 | 状态 |
|---|---|---|
| `specs/cmdsched.md` | CMD_SCH 架构 spec（需求源） | 输入 |
| `specs/README.md` | spec 抽取输入、hash/版本、换 spec 流程 | 输入 |
| `verification/CMDSCHED_README.md` | target plan 索引、状态、落地顺序 | 目标计划 |
| `verification/CMDSCHED_spec_analysis.md` | spec 分析：需求/架构/接口/Feature List/约束/异常/性能/风险 | 分析 |
| `verification/CMDSCHED_vplan.md` | 验证计划：feature 树、专题、TP、契约、planned case、签核 | 目标计划 |
| `verification/CMDSCHED_cases.csv` | 12 个 planned case | 计划层 |
| `verification/CMDSCHED_case_trace.md` | contract → case → TP 追溯 | 生成视图 |
| `verification/CMDSCHED_matrix.md` | feature × 专题矩阵 | 生成视图 |
| `contract/C01_contract_matrix.md` | 契约矩阵字段、状态、三权分立 | 方法 |
| `appendix/X00_id_anchor_spec.md` | ID 正则、锚点、命名规则 | 规范 |

## 阅读顺序

1. `specs/cmdsched.md` — 真实架构 spec
2. `specs/README.md` — spec 抽取输入和换 spec 流程
3. `verification/CMDSCHED_spec_analysis.md` — spec 分析结论
4. `verification/CMDSCHED_vplan.md` — 验证范围/策略/feature 树/TP/case
5. `verification/CMDSCHED_README.md` — 状态、命令、落地顺序
6. `contract/C01_contract_matrix.md` — 契约字段与状态
7. `appendix/X00_id_anchor_spec.md` — 代码锚点规则

> 当前所有契约是 `assume`，所有 TP/case 是 `planned`；没有 VCS/UVM/URG 证据，不可签核。
