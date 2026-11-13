---
description: SignOffAI IC 验证端到端流程（spec → VPlan → 架构文档 → 实现 → 环境稳定 → case → 回归/覆盖率/签核）
argument-hint: "<project-or-spec> [--module <name>] [--target 95]"
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Task
---

# /claude_verify

先读取并严格遵循：

```text
.claude/skills/claude_verify/SKILL.md
```

然后按其中的 12 个阶段执行。重点：

1. 识别 `$ARGUMENTS` 是项目目录、spec 文件还是空；空时先问，不要猜。
2. 先跑 `vplan status` / `vplan review --check`，确认 review 状态。
3. 依次产出：
   - `docs/verification/00_intake.md`
   - `01_vplan_summary.md`
   - `02_env_architecture.md`
   - `03_model_architecture.md`
   - `04_env_impl.md`
   - `05_model_impl.md`
   - `06_env_stability.md`
   - `07_cases.md`
   - `08_signoff.md`
4. EDA 不可用就报 `BLOCKED_EDA_MISSING`；未 review 就拒绝 `vplan execute`。
5. 对 `main/` 的修改只能走 `workspace propose → gate → approve → promote`。

执行时使用仓库 venv：

```bash
# Windows
.\\venv\\Scripts\\python.exe -m src.cli.commands ...
# Unix
./venv/bin/python -m src.cli.commands ...
```

最后报告：实际命令、证据路径、gate 结果、未决问题、是否可签。
