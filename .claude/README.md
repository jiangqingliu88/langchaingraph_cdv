# Claude Verify

把 SignOffAI 的 IC 验证流程提炼成 Claude Code 可调用的命令 / 子 agent / skill。
**不复制实现**：所有执行仍落到现有 `src.cli.commands`、`vplan`、`evidence`、
`workspace`，这里只做流程编排与硬门禁。

## 文件

| 文件 | 作用 |
|---|---|
| `.claude/commands/claude_verify.md` | `/claude_verify` 斜杠命令 |
| `.claude/agents/claude_verify.md` | 可被 Task 调用的验证子 agent |
| `.claude/skills/claude_verify/SKILL.md` | 12 阶段流程本体（权威） |

## 使用

```text
/claude_verify specs/npu_sched
/claude_verify path/to/spec.md --module my_dut --target 95
```

或让 Claude Code 派子 agent：

```text
Task(subagent_type="claude_verify", prompt="验证 specs/npu_sched ...")
```

## 流程

```text
spec
 → VPlan（review/build/status）
 → 环境架构文档
 → 模型架构文档
 → 环境架构实现
 → 模型架构实现
 → 环境 agent 稳定性
 → case 用例撰写
 → 回归 / 覆盖率
 → evidence / gate / 签核
```

## 硬门禁

- 未 review 的 VPlan 不许 `execute`；
- 无 EDA 证据不许说 passed，必须报 `BLOCKED_EDA_MISSING`；
- `assume` 不能手改成 `active`，`planned` 不能手改成 `covered`；
- `main/` 只能通过 `workspace propose → gate → approve → promote` 改；
- 所有结论必须带命令、日志、报告或证据路径。

## 产出

```text
docs/verification/
  00_intake.md
  01_vplan_summary.md
  02_env_architecture.md
  03_model_architecture.md
  04_env_impl.md
  05_model_impl.md
  06_env_stability.md
  07_cases.md
  08_signoff.md
```
