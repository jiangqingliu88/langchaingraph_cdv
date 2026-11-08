# schemas — JSON Schema（保留供后续落地）

当前 spec-first 流程直接读取 CSV/YAML 抽取表，**暂不经过 JSON Schema 校验**。这两个 schema 保留给后续真实 case/data 落地时使用。

| 文件 | 约束对象 | 未来使用方 |
|---|---|---|
| `contract.schema.json` | `data/contract_matrix/*.csv` 的每一行（13 列） | 未来的 `lint_data.py` |
| `case_contract.schema.json` | 未来的 `cases/TC_*.yaml` | 未来的 `lint_data.py` |

`scripts/common/schema_util.py` 提供无第三方依赖的 Schema 子集：`type`、`required`、`properties`、`additionalProperties:false`、`enum`、`pattern`、`items`、`minItems`、`minimum`。

规则：字段变更必须同步 `data/`、未来的 `cases/`、生成脚本与 schema，并同步更新 `scripts/common/ids.py` 中的正则。当前 CI 以 `gen_spec_plan.py --check` / `lint_spec_trace.py` 为准。
