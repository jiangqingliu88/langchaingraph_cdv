# CMDSCHED spec target plan — 索引

本目录下的 `CMDSCHED_*` 是从 `docs/specs/cmdsched.md` 分析得到的 **CMD_SCH 目标验证计划**。执行层尚未接入；当前没有运行证据。

| 文件 | 内容 | 状态 |
|---|---|---|
| `CMDSCHED_spec_analysis.md` | spec 分析：变更需求、架构/数据流、接口、Feature List、约束、低功耗、异常、性能、签核口径、风险 | 分析结论 |
| `CMDSCHED_vplan.md` | 目标验证计划：黑盒 feature 树、专题、测试点、契约、planned case、签核 | 目标计划 |
| `CMDSCHED_features.csv` | 39 节点 feature 树（1 root + 9 branch + 29 leaf） | 目标数据 |
| `CMDSCHED_topics.csv` | 10 个专题 | 目标数据 |
| `CMDSCHED_testpoints.csv` | 66 个 planned 测试点 | 目标数据 |
| `CMDSCHED_contracts.csv` | 42 条 spec 契约（全部已转 assume） | 目标数据 |
| `CMDSCHED_cases.csv` | 12 个 planned case | 计划层 |
| `CMDSCHED_case_trace.md` | contract → case → TP 追溯 | 生成视图 |
| `CMDSCHED_matrix.md` | feature × 专题矩阵 | 生成视图 |
| `data/case_plan_view.html` | 12 个 planned case 的占位视图（PLACEHOLDER / NOT RUN） | 占位视图 |

## 状态

- **all planned**：66 个测试点、12 个 case 全部是 `planned`；
- **all assume**：42 条 spec 契约已写入 `data/contract_matrix/`，状态全部为 `assume`，没有 active/exempt；
- **no evidence**：没有 VCS/UVM/URG，没有 JSON/log/cov/波形；
- **not signoff**：当前是目标计划，不可签核。

## 输入

| 输入 | 作用 |
|---|---|
| `docs/specs/cmdsched.md` | spec 原文，用于计算哈希 |
| `docs/specs/cmdsched_requirements.csv` | 20 条需求 → feature 映射 |
| `docs/specs/cmdsched_features.csv` | 39 节点 feature 树 |
| `docs/specs/cmdsched_topics.csv` | 10 个专题 |
| `docs/specs/cmdsched_contracts.csv` | 42 条 spec 契约 |
| `docs/specs/cmdsched_testpoints.csv` | 66 条测试点 |
| `docs/specs/cmdsched_cases.csv` | 12 个 planned case |
| `docs/specs/cmdsched_spec_meta.json` | spec_version / spec_hash / plan_version |

## 生成与校验

```bash
cd demo
python scripts/gen_spec_plan.py              # 生成；spec hash 不匹配时拒绝
python scripts/gen_spec_plan.py --check      # 只校验输入/输出是否同步
python scripts/lint_spec_trace.py            # spec 追溯 + 生成物一致性
python scripts/gen_planned_case_view.py      # 生成占位 case view
```

`--allow-spec-drift` 只用于预览 spec 已变更但抽取尚未更新时的计划，矩阵会标 `SPEC DRIFT`，不能签核。

生成器/校验器会检查：

- spec 哈希与 meta 一致；
- 每条 requirement 的 feature 存在且至少被一个 TP 覆盖；
- 每个 leaf feature 被 requirement 引用，且每个适用专题都有 TP；
- feature 树 parent/编号/路径/层级合法；
- TP 的 feature/topic/contract/status/priority 合法；
- 12 个 planned case 覆盖 42/42 契约、66/66 TP，所有 TP 的 `case_plan` 存在；
- 生成的 CSV/矩阵/case trace 与输入一致。

## 建议落地顺序

1. 选 `TC_CMDSCHED_RSP_001` 做首个真实样板：case YAML → UVM test → VCS → URG → evidence。
2. 补 SVA/Checker/SCB/coverage 资产和锚点，把对应 assume 契约转 active。
3. 接真实覆盖率门禁（CP/cross/illegal/代码覆盖/断言覆盖）。
4. 复制到其余 11 个 planned case。
5. 补 P1 可靠性/形式化/低功耗/长稳。

## Spec 分析要点

- 核心风险是路径上的资源/依赖/竞争/时序：scoreboard 在途表、SHazard/DHazard、tile/page/dram、OST=2、ins_buffer 乱序发射、TMU 竞争、xd=1 乱序返回。
- 关键口径：典型 1 instr/cycle；代码覆盖 100%；功能覆盖 >95% 且未覆盖逐条豁免；回归 100% pass。
- 待决项：NIU AXI ID、跨 cluster noc、cfg/drv/pre 计数器 TODO、功耗/电源域范围。
