# scripts — spec-first 生成与校验

所有脚本以 `specs/npu_sched/`（项目根）为工作目录运行，仅使用 Python 标准库。

| 脚本 | 输入 | 输出 | 退出码 | 作用 |
|---|---|---|---|---|
| `gen_spec_plan.py` | `docs/specs/cmdsched_*.csv` + `cmdsched_spec_meta.json` | `docs/verification/CMDSCHED_*.csv`、`CMDSCHED_matrix.md`、`CMDSCHED_case_trace.md`、`CMDSCHED_impact.md` | 0/1 | 生成 target plan；`--check` 校验同步；spec hash 不匹配时拒绝 |
| `lint_spec_trace.py` | spec 抽取输入 + 生成的 CMDSCHED_* | 终端报告 | 0/1 | spec hash/需求追溯/feature 树/TP/case/生成物一致性 |
| `gen_planned_case_view.py` | `docs/specs/cmdsched_cases.csv` + testpoints/contracts/features | `data/case_plan_view.html` | 0/1 | 生成 12 个 planned case 的占位视图（PLACEHOLDER / NOT RUN，不写 evidence） |

## 命令

```bash
cd demo
python scripts/gen_spec_plan.py
python scripts/gen_spec_plan.py --check
python scripts/lint_spec_trace.py
python scripts/gen_planned_case_view.py
```

## common

| 文件 | 作用 |
|---|---|
| `common/ids.py` | ID 正则（contract/case/cg/cp/cross 等），供未来 lint/data 脚本复用 |
| `common/schema_util.py` | 无第三方依赖的 JSON Schema 子集校验，供未来 `lint_data.py` 复用 |

## 规则

- 脚本只读 `docs/specs` / `data/contract_matrix`，不修改输入。
- `gen_spec_plan.py` 默认拒绝 spec hash 不一致；`--allow-spec-drift` 仅用于预览，矩阵会标 `SPEC DRIFT`。
- `gen_planned_case_view.py` 只生成占位 HTML，不写 `evidence/json`、不写 `reports/`，不参与任何门禁。
- 当前没有 `run_demo.py` / `sim_stub.py` / 执行门禁脚本；执行层尚未接入。
