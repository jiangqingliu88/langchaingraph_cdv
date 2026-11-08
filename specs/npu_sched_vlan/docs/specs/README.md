# specs — Spec 抽取输入

`cmdsched.md` 是架构 spec 原文。本目录其余文件是**人审后的机器可读抽取输入**，由 `scripts/gen_spec_plan.py` 消费，生成 `docs/verification/CMDSCHED_*`。

| 文件 | 内容 | 规模 |
|---|---|---|
| `cmdsched.md` | CMD_SCH 架构 spec 原文 | 2565 行 |
| `cmdsched_requirements.csv` | 需求抽取：req_id、spec 章节、描述、feature_ids、P 级 | 20 |
| `cmdsched_features.csv` | feature 拆分树（含 parent/level/no/适用专题） | 39 |
| `cmdsched_topics.csv` | 10 个专题 | 10 |
| `cmdsched_contracts.csv` | 候选契约（已推进：40 assume + 2 合并） | 42 |
| `cmdsched_testpoints.csv` | 测试点（全部 planned） | 66 |
| `cmdsched_cases.csv` | planned case 计划（contract/CG/checks/owner） | 12 |
| `cmdsched_spec_meta.json` | spec 版本、spec 哈希、plan 版本 | — |

## 换 spec 的流程

1. 更新 `cmdsched.md`。
2. 更新抽取输入：`requirements`、`features`、`contracts`、`testpoints`、`cases`、`topics`。
3. 重新计算 spec 哈希，更新 `cmdsched_spec_meta.json`：

```bash
python - <<'PY'
import hashlib, json
from pathlib import Path
p = Path('docs/specs/cmdsched.md')
meta_path = Path('docs/specs/cmdsched_spec_meta.json')
meta = json.loads(meta_path.read_text(encoding='utf-8'))
meta['spec_hash'] = hashlib.sha256(p.read_bytes()).hexdigest()
meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(meta['spec_hash'])
PY
```

4. 重新生成 target plan：

```bash
python scripts/gen_spec_plan.py
```

5. 校验 spec 追溯和生成物一致性：

```bash
python scripts/lint_spec_trace.py
```

6. 评审 `docs/verification/CMDSCHED_impact.md` 的新增/删除/变更项。

## 哈希与版本

- `spec_hash`：`cmdsched.md` 的 SHA-256。哈希不一致时，`gen_spec_plan.py` 默认拒绝生成，避免静默产出旧计划。
- `spec_version`：人工维护的 spec 版本。
- `plan_version`：target plan 版本；契约/TP 结构变化时递增。
- 预览 spec 漂移时可临时使用 `--allow-spec-drift`，生成结果会在矩阵头部标 `SPEC DRIFT`，不能用于签核。

## 校验内容

`lint_spec_trace.py` 检查：

- spec 哈希与 meta 一致；
- 每条 requirement 的 feature 存在且至少被一个 TP 覆盖；
- 每个 leaf feature 被至少一条 requirement 引用，且其每个适用专题都有 TP；
- feature 树 parent/编号/路径/层级合法；
- TP 的 feature/topic/contract/status/priority 合法；
- planned case 的 contract/CG/check/owner/status 合法，所有契约被至少一个 case 引用，所有 TP 的 `case_plan` 存在且匹配；
- 生成的 `CMDSCHED_features.csv`、`CMDSCHED_topics.csv`、`CMDSCHED_testpoints.csv`、`CMDSCHED_contracts.csv`、`CMDSCHED_cases.csv`、`CMDSCHED_matrix.md`、`CMDSCHED_case_trace.md` 与输入一致。

注意：`CMDSCHED_impact.md` 是变更报告，不是可复现源，不参与一致性检查；没有新差异时会保留上一次变更记录。
