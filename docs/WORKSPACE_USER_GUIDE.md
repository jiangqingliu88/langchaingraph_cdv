# 工作区 / 沙箱 Harness 用户指南

适用版本：2026-11-10（workspace zones + harness 落地后）

这份指南回答三件事：

1. **main / staging / proposal / gate 是什么**，为什么不能直接改签核区；
2. **两条用法**：自己改 staging 后交 proposal，或让 LLM harness 在沙箱里自动跑；
3. 失败时**怎么查、怎么恢复**，以及它和 VPlan 主流程的关系。

> 一句话：**沙箱里随便干，出门交 proposal，门卫是 gate，过了才 promote 进 main。**

---

## 0. 先分清两个 gate

项目里有两个都叫 gate 的东西，别混：

| 名字 | 命令 | 管什么 |
|---|---|---|
| **Workspace Gate** | `workspace gate` | 一份 proposal 能不能进 `main/`（基线/差异/证据/日志/疑点） |
| **VPlan Gate** | `vplan gate` | 契约能不能从 `assume` 推到 `active`（回归/覆盖率/义务/审阅） |

Workspace Gate 是“改文件”的门；VPlan Gate 是“签核契约”的门。两者互不替代。

---

## 1. 准备

```bash
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -e ".[dev]"                              # 桌面工作台再加 ",gui"
cp .env.example .env                                 # 可选；LLM 步骤需要 key
```

- 没有 LLM key：`workspace loop` 会如实返回 `blocked / LLM_UNAVAILABLE`，但手工 proposal、
  gate、promote、VPlan 的确定性路径照常可用。
- 需要跑仿真/编译的步骤需要 QuestaSim（`vlog/vsim` 在 PATH）。

下面的命令统一用 `python -m src.cli.commands`；如果装了入口脚本，`vagent` 等价。

---

## 2. 五分钟上手：手工通道（不用 LLM）

### 2.1 建工作区

```bash
# main = 已签核基线；staging 自动复制一份，可随意改
python -m src.cli.commands workspace init workspace/npu --from specs/npu_sched/rtl
# 只读项目视图：不给 --project-root 时会从 --from 向上找 .git/pyproject.toml，
# 找到的工程根即视图根；显式指定可覆盖
python -m src.cli.commands workspace init workspace/npu \
  --from specs/npu_sched/rtl --project-root .
```

目录：

```text
workspace/npu/
  main/        签核内容（沙箱只读）
  staging/     你的工作区（可写、可跑、可丢弃）
  proposals/   proposal JSON
  gate/        GateReport / 批准 / backups / ledger.jsonl
  .harness/    会话与事件（harness 用）
```

> `workspace/` 已在 `.gitignore` 里；不要把 staging 提交进库。

### 2.2 改 staging

直接编辑，或用自己的脚本改：

```text
workspace/npu/staging/rtl/xxx.sv
```

> 写路径只能是 `staging/` 内的相对路径；`../`、绝对路径、`main/xxx` 都会被拒绝。

### 2.3 交 proposal（窄接口）

```bash
python -m src.cli.commands workspace propose workspace/npu \
  --task "给 cmd_int_perf 补一个复位边界用例" \
  --before "vlog 通过；该边界无覆盖" \
  --after  "vlog 通过；新增 case 覆盖 line 47" \
  --reasoning "在 staging/tb 增加一个 case，复位释放后打一拍边界" \
  --run "vlog -sv rtl/cmd_int_perf.sv tb/cmd_int_perf_tb.sv" \
  --open-question "line 47 的复位时序仍建议人工确认"
```

要点：

- `--run` 是**真跑**：命令在 `staging/` 下执行，退出码与日志自动进 proposal；
- 至少一条 `--run`，否则 proposal 证据不完整会被拒绝；
- `--open-question` 会进人工门；没有疑点可以不给。

### 2.4 过门 + 人工批准 + 提升

```bash
python -m src.cli.commands workspace gate workspace/npu <proposal_id>
python -m src.cli.commands workspace approve workspace/npu <proposal_id> --by jiang
python -m src.cli.commands workspace promote workspace/npu <proposal_id> --by jiang
```

- `gate`：默认 6 项检查（见 §4）；**任何 block 失败都不许 promote**；
- `approve`：有 `open_questions` / warn 时必须批；批准人必填；
- `promote`：**唯一**写 `main/` 的动作；覆盖/删除前备份到 `gate/backups/<id>/`，
  并追加 `gate/ledger.jsonl`（谁提议、什么证据、谁批的）。

### 2.5 丢弃或查看

```bash
python -m src.cli.commands workspace status workspace/npu     # 主区指纹 / 差异 / proposal
python -m src.cli.commands workspace proposals workspace/npu  # 申请单列表
python -m src.cli.commands workspace reset workspace/npu      # staging 恢复成 main
```

---

## 3. LLM Harness：让它在沙箱里自己跑

Harness 是显式状态机 + 结果回填 + 会话恢复，不是“一次问答”。

### 3.1 基本用法

```bash
python -m src.cli.commands workspace loop workspace/npu \
  --task "补一个边界用例：先读覆盖率与 RTL，写 case，跑 vlog，再交 proposal" \
  --plan
```

- `--plan`：第一次响应必须先给计划；
- `--require-plan-approval`：计划需要人批准后才继续；
- `--require-exec-approval`：`run_shell` / `job_start` 需要人批准；
- `--max-steps 12`、`--max-rounds 2`、`--max-tokens 200000`；
- `--no-subagent`：禁止它再派子 agent。

### 3.2 暂停与恢复

Harness 遇到以下情况会暂停并返回 `paused`：

| pending kind | 触发 | 恢复命令 |
|---|---|---|
| `plan` | `--require-plan-approval` | `resume --approve`（可 `--plan` 改计划） |
| `approval` | `--require-exec-approval` 或工具要求审批 | `resume --approve` / `--deny` |
| `answer` | agent 调 `ask_user` | `resume --answer "..."` |

```bash
python -m src.cli.commands workspace sessions workspace/npu
python -m src.cli.commands workspace resume workspace/npu <session_id> --approve
python -m src.cli.commands workspace resume workspace/npu <session_id> --answer "用 0x7f"
```

会话与事件：

```text
workspace/npu/.harness/sessions/<session_id>.json          # 状态快照（可恢复）
workspace/npu/.harness/sessions/<session_id>.events.jsonl  # 状态/LLM/工具/压缩/提案事件
```

### 3.3 目标分解 + ReAct

复杂任务第一次响应可以给子目标：

```json
{"thought": "...", "tool": "read_file", "args": {...},
 "subgoals": [
   {"id": "G1", "title": "读基线", "success": "知道当前实现"},
   {"id": "G2", "title": "写并验证", "success": "新 case 跑通"}
 ]}
```

之后 harness **一次只推进一个子目标**：reason → act → observe，直到：

- `complete_subgoal(summary=...)`：标记完成（summary 必须是工具证据的说明）；
- `block_subgoal(reason=...)`：标记阻塞，自动变成 `open_questions`，继续下一个；
- 子目标步数用尽：自动 blocked，进入下一个。

全部子目标结束后，harness 要求 `propose` 汇总；Gate 的 `subgoals` 检查会拒绝仍有
未完成子目标的提案。事件里能看到 `subgoal.start / subgoal.finish /
react.reason / react.act / react.observe`。

### 3.4 EDA 证据（`--goal coverage`）

给 harness 一个**可裁决的目标**，它会先读基线证据、按缺口拆子目标，再逐轮改/跑/收证据：

```bash
python -m src.cli.commands workspace loop workspace/npu \
  --task "把功能覆盖率从 63% 提到 95%" \
  --goal coverage --target 95 \
  --project workspace/npu/staging \
  --evidence output_vplan_npu_sched_e2e_r6
```

- `--evidence`：已有 run 目录；harness 读
  `regression_stages.json / coverage_result.json / coverage_holes.json /
  closure_plan.json / contract_manifest.json`，按 `closure.actions`（如
  `ADD_MONITOR`）自动生成子目标；没有 actions 时按 holes 分组；
- `--project`：`run_verify` 要跑的项目路径（默认 staging）；
- `--project-root`：**只读项目视图**的根（默认取 `workspace init` 时记下的
  项目根）。harness 用 `project_map / read_project_file / search_project`
  读 RTL、验证代码、覆盖率数据、环境配置、spec、C/SystemC 模型；
- `--require-review`：`run_verify` 强制执行 VPlan 人工审阅门；沙箱默认带
  `--allow-unreviewed`（证据里会记录该事实）。

只看项目资源清单（不进 loop）：

```bash
python -m src.cli.commands workspace resources workspace/npu --kind rtl --limit 50
python -m src.cli.commands workspace resources workspace/npu --kind coverage
```

`kind` ∈ `rtl / verification / coverage / env / spec / model`；不传则给全量
分类计数。敏感文件（`.env`、凭据、私钥）永不列出/读取，二进制（`.ucdb` 等）
只返回大小与 sha256。

新增工具：

| 工具 | 作用 |
|---|---|
| `run_verify(project, run_dir, target)` | 调现有 `vplan execute` 跑一轮，日志/证据落 staging |
| `collect_evidence(run_dir, target)` | 读结构化报告 + 文件 sha256 |
| `compare_evidence(before, after)` | 覆盖率/回归/缺口前后对比 |
| `export_evidence(run_dir, out)` | 导出可交换证据 zip（v2 签核包优先，否则结构化证据） |

自动导出（`run_verify` 成功后立即打包，zip 落 staging）：

```bash
python -m src.cli.commands workspace loop workspace/npu \
  --task "..." --goal coverage --target 95 --evidence <run> --export
# 也可离线导出已有 run：
python -m src.cli.commands workspace export workspace/npu \
  --run output_vplan_npu_sched_e2e_r6
```

导出优先收 `<run>/signoff_evidence/`（v2：manifest + inputs/execution/verdict/replay），
没有时退回结构化证据文件并标 `complete=false`；zip 内固定时间戳 + 逐文件
sha256 + `export_manifest.json`，同样输入可复算。

Gate 用 `--profile eda` 追加领域检查：

```bash
python -m src.cli.commands workspace gate workspace/npu <id> --profile eda
```

检查项：`eda_regression`（status=PASS 且 failed=0）、`eda_coverage`（functional ≥
target）、`eda_evidence_files`（每个文件 sha256 匹配）、`eda_contracts`（证据里有
契约义务计数）。证据不在 staging/ 下、或没有 target 时会给 warn + 人工门。

### 3.5 状态机

```text
NEW → PLANNING → ACTING → OBSERVING → PLANNING …
              ├→ AWAITING_PLAN → PLANNING
              ├→ PAUSED        → PLANNING/ACTING
              └→ PROPOSING → DONE | BLOCKED | CANCELLED | FAILED
```

- **结果回填**：tool 结果同时进消息（下一轮 LLM 可见）和 `working`
  （changed_files / commands / logs / todos / subagents / jobs / open_questions）；
- **上下文压缩**：token 估算 + 旧 tool 结果裁剪 + compaction，完整日志仍在 staging；
- **熔断**：步数 / 轮次 / token / 连续工具错误 / 取消。

### 3.6 Harness 可用工具

`read_file`、`list_files`、`search`、`read_skill`、`write_file`、`delete_file`、
`str_replace`、`run_shell`、`run_verify`、`collect_evidence`、`compare_evidence`、
`export_evidence`、`project_map`、`read_project_file`、`search_project`、
`job_start`、`job_output`、`job_kill`、`todo_write`、`spawn_subagent`、
`complete_subgoal`、`block_subgoal`、`ask_user`、`propose`、`finish`。

- `read_file/list_files/search` 看的是 staging/main；`project_map /
  read_project_file / search_project` 看**只读项目视图**（RTL/验证/覆盖率/
  环境/spec/模型），可用于先摸清项目再动手；
- 写/删/替换只能落 staging，项目只读视图没有任何写方法；
- `run_shell` 的 cwd 是 staging，日志写 `staging/.evidence/`；
- 后台任务日志写 `staging/.jobs/`；
- skill 从 `workspace/npu/.skills/*.md` 发现，全文用 `read_skill` 读。

---

## 4. Gate 到底查什么

默认检查（`src/workspace/gate/checks.py`）：

| 检查 | 判据 |
|---|---|
| `proposal_schema` | 字段齐全；路径/哈希合法；日志存在 |
| `main_baseline` | proposal 基于的 main 指纹 == 当前 main |
| `changed_files` | proposal 申报的变更 == staging 当前差异（防夹带） |
| `evidence_commands` | 至少一条 `exit_code=0`；非 0 命令 → warn（人工确认） |
| `evidence_logs` | 日志存在且在 `staging/` 内 |
| `subgoals` | 有未完成子目标 → fail；blocked → warn（人工门） |
| `open_questions` | 非空 → `human_required` |

`--profile eda` 追加：`eda_regression`（PASS 且 failed=0）、`eda_coverage`
（functional ≥ target）、`eda_evidence_files`（sha256 匹配）、`eda_contracts`
（义务计数）；任何 block 失败都挡住 promote。

领域检查（契约、分级回归、覆盖率阈值）可以注入：

```bash
python -m src.cli.commands workspace gate workspace/npu <id> \
  --check my_project.checks:regression_evidence
```

钩子签名：`hook(proposal, zones) -> [{name,status,severity,detail}]`；
`status=fail, severity=block` 即挡住 promote。

---

## 5. 失败剧本

| 现象 | 原因 | 处理 |
|---|---|---|
| `proposal_invalid: evidence.commands 为空` | 没有真跑命令 | 加 `--run` 重交，或让 loop 跑命令 |
| `gate: changed_files fail` | proposal 交了之后 staging 又被改 | 重新 `propose`；gate 不会替旧证据放行 |
| `gate: main_baseline fail` | 期间有人 promote 了别的 proposal | rebase staging 后重新 propose/gate |
| `promote: human_required` | 有 open_questions/warn 未批 | 先 `approve --by` |
| `promote: Gate 检查未通过` | block 检查失败 | 回 staging 修，重新 gate |
| `blocked / LLM_UNAVAILABLE` | 没有 key 或调用失败 | 配 `.env`，或改走手工 `propose` |
| `paused / plan` | 计划未批 | `resume --approve`（或 `--deny`） |
| `paused / approval` | 命令未批 | `resume --approve`（或 `--deny`） |
| `paused / answer` | agent 在问人 | `resume --answer "..."` |
| `MAX_STEPS / BUDGET_EXHAUSTED` | 步数/token 用尽 | 调大 `--max-steps/--max-tokens`，或缩小任务 |
| staging 搞坏了 | — | `workspace reset`（main/proposal/gate 不动） |

---

## 6. 它和 VPlan 主流程的关系

两条路线互不替代：

```text
VPlan 主流程（签核）
  spec → dplan → TP/Case IR → verify(UVM) → 分级回归 → coverage → evidence → audit/gate

Workspace 沙箱（改东西）
  staging 里改/跑 → proposal → Gate → approve → promote 到 main
```

### 6.1 VPlan 常用命令

```bash
python -m src.cli.commands vplan status specs/npu_sched
python -m src.cli.commands vplan review specs/npu_sched --by <name>   # 人工审阅门
python -m src.cli.commands vplan execute specs/npu_sched \
  -o output_vplan_npu_sched --max-rounds 1 --sim-mode cov
python -m src.cli.commands vplan gate specs/npu_sched
```

- 未审阅/已过期时 `execute` 会被拒绝；`--allow-unreviewed` 只用于开发调试（日志有 warning）。
- UVM 资产只落 `<run>/sv/`；`SIGNOFFAI_UVM_LAYOUT=legacy` 是旧布局逃生口。
- `vplan gate` 是契约门，和 `workspace gate` 无关。

### 6.2 GUI

```bash
python -m src.workbench          # 或 run_gui.bat / vagent gui run
```

- 「验证产出」页读取 `sv/`（不再显示顶层 agents/env/bench）；
- 「ISA 激励」页走 `isa_ir_tools` 的 validate/build；
- VPlan 页读取 `sv/asset_registry.csv` 与 `sv/uvm_arch.yaml`。

---

## 7. 命令速查

```bash
# Workspace
workspace init <root> [--from <baseline>]
workspace status <root>
workspace propose <root> --task ... --before ... --after ... --reasoning ... \
    --run "cmd" [--open-question "..."] [--eda-run <run>] [--target 95]
workspace loop <root> --task ... [--plan] [--require-plan-approval] \
    [--require-exec-approval] [--max-steps N] [--max-rounds N] [--max-tokens N] \
    [--no-subagent] [--session-id <id>] \
    [--goal coverage --target 95] [--project <staging>] [--evidence <run>] \
    [--max-subgoals N] [--require-review]
workspace sessions <root>
workspace resume <root> <session_id> [--approve|--deny] [--answer "..."] [--plan "..."]
workspace gate <root> <proposal_id> [--check module:callable] [--profile eda]
workspace approve <root> <proposal_id> --by <name> [--comment "..."]
workspace promote <root> <proposal_id> [--by <name>] [--force]
workspace proposals <root>
workspace reset <root>

# VPlan
vplan status <project>
vplan review <project> --by <name> | --check
vplan execute <project> -o <run> --max-rounds 1 --sim-mode cov
vplan gate <project> [--apply]
```

---

## 8. 纪律

1. **不写 main**：只有 `promote` 写；手工改 `main/` 视为绕过门卫。
2. **证据必须真**：`--run` 的命令真执行；不要手填日志/退出码。
3. **不提交 staging**：`workspace/` 已在 `.gitignore`；产物只在本机。
4. **失败响亮**：gate/promote 的拒绝是正常结果，不要 `--force` 掩盖。
5. `--force` 只用于开发调试；账本会记 `forced=true`。

---

## 9. 当前已知限制

- `specs/npu_sched` 仍未人工审阅：正式 execute 前需要 `vplan review`；
- 最近一次 E2E：loopback/p0/p1/p3 全过，功能覆盖率 **63.28%**（目标 95%），
  `vplan gate` 仍不会把契约从 `assume` 推进；
- `isa_ir_tools/data/csr_map.csv` 只有 127 行（loader 要求 232），含 CSR 操作的 case
  会显式失败；
- Harness 未接入 MCP / web 工具 / workflow-worker；扩展点在
  `src/workspace/harness/tools.py` 与 `_execute_tool`；
- 沙箱是**路径隔离 + 子进程 cwd 限制**，不是容器/虚拟机级隔离。
