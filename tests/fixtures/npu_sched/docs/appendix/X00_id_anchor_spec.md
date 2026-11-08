# X00 ID 与锚点规范

## 1. ID 正则

实现见 `scripts/common/ids.py`，文档与脚本必须一致。

| 类型 | 正则 | 示例 |
|---|---|---|
| 契约 | `^C-[A-Z]+(?:-[A-Z0-9]+)*-\d{3}$` | `C-IF-HS-001`、`C-PERF-START-DONE-001` |
| case | `^TC_[A-Z0-9]+(?:_[A-Z0-9]+)*$` | `TC_CMD_BASIC_01` |
| covergroup | `^cg_[a-z0-9_]+$` | `cg_cmd_opcode` |
| coverpoint | `^cp_[a-z0-9_]+$` | `cp_opcode` |
| cross | `^cross_[a-z0-9_]+$` | `cross_opcode_len` |
| 约束 | `^CON_[A-Z0-9_]+$` | `CON_OPCODE_LEGAL` |
| 豁免 | `^EX-\d{3}$` | `EX-001` |
| 批次 | `^batch\d{2}$` | `batch01` |

## 2. 锚点格式

锚点只出现在 SystemVerilog 的 `//` 行注释中，供 `lint_sv_anchor.py` / `scan_assets.py` 解析。

| 锚点 | 位置 | 示例 |
|---|---|---|
| `// OWNER: <name>` | 每个 SV 文件 | `// OWNER: dv_func` |
| `// CASE_ID: <TC_...>` | test 文件 | `// CASE_ID: TC_CMD_BASIC_01` |
| `// CONTRACT_REFS: <id...>` | test 文件 | `// CONTRACT_REFS: C-IF-HS-001 C-FUNC-RSP-001` |
| `// CHECKS: <artifact...>` | test 文件 | `// CHECKS: sva_handshake_cmd rsp_scb` |
| `// ARTIFACT: <id>` | 检查产物文件 | `// ARTIFACT: res_scb` |
| `// CONTRACT_ID: <id>` | 检查产物/接口 | `// CONTRACT_ID: C-RES-REL-001` |
| `// AGENT: <name>` | agent 主文件 | `// AGENT: cmdsched_cmd_agent` |
| `// MODE: active|passive` | agent 主文件 | `// MODE: passive` |

多个 ID 用空格分隔；脚本会做集合比对，顺序无关。

## 3. 一致性规则

1. 一个 case 有且只有一个 test 文件，`CASE_ID` 与文件名对应。
2. test 的 `CONTRACT_REFS` 必须与 case YAML 的 `contract_refs` **集合相等**。
3. test 的 `CHECKS` 必须与 case YAML 的 `checks[].artifact` **集合相等**。
4. 每个 active 契约的 `check_artifact` 必须能在 `sv/` 找到 `ARTIFACT` 锚点，且该文件 `CONTRACT_ID` 包含此契约。
5. covergroup / coverpoint / cross 名称必须与 `data/` 中的 ID 完全一致；改覆盖结构时必须同步 SV。
6. 锚点由**人写**，`scan_assets.py` 只扫描不修改；CI 用 `--check` 比对生成结果与仓库文件。

## 4. 为什么用锚点而不是文件名

文件名会变、目录会挪，ID 不应随文件漂移。锚点让“代码里是否真的实现了这条契约/用例”成为可脚本判定的问题，也是孤儿检测与可达性分析的基础。
