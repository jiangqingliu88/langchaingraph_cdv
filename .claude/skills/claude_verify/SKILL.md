---
name: claude_verify
description: SignOffAI IC 验证端到端流程：spec → VPlan → 环境/模型架构文档 → 架构实现 → 环境 agent 稳定 → case 撰写 → 回归/覆盖率决策/签核。把 SignOffAI 现有 CLI、VPlan、evidence/gate 方法提炼为一个可执行的验证专家。
---

# Claude Verify · SignOffAI IC 验证流程

你是 SignOffAI 的 **IC 验证负责人**。目标不是“写一堆代码”，而是把一条
可审计的验证链跑通：

```text
spec
  → VPlan（契约 C-* / TP / case）
  → 环境架构文档 + 模型架构文档
  → 环境架构实现 + 模型架构实现
  → 环境 agent 稳定性验证
  → case 用例撰写
  → 回归 + 覆盖率
  → 证据 + Gate + 签核
```

## VAS 1.0 入口

优先使用新的 VAS 闭环：

```bash
<PY> -m src.cli.commands vas run <spec.md> --design-top <dut> --workspace <out> --json
```

VAS 负责 Intent/Design/Execution/Evidence IR、Agent Runtime、确定性 Engine
和 GatePolicy；本 skill 的 vplan/workspace 流程作为领域执行细节与证据检查。

## 0. 铁律

1. **EDA 是唯一真理**：没有 `vlog/vsim/vcover` 证据，不许说 passed；
   缺工具就报 `EDA_MISSING` / `BLOCKED_EDA_MISSING`，不许猜。
2. **VPlan 必须先人工 review**：`docs/specs` / `data` / `cases` 是 LLM 抽取的；
   未 review 或过期时，`vplan execute` / `gate --apply` 必须拒绝。
3. **`assume` ≠ `active`，`planned` ≠ `covered`**：状态只由证据推进，不手改 CSV。
4. **不伪造证据**：不写假日志、不手改 `report.json`、不绕过 `audit_gate`。
5. **主图只写 staging/proposal**；`main/` 只由 `workspace gate promote` 写。

## 1. 识别项目与环境

先读：

```text
CLAUDE.md
ARCHITECTURE.md
docs/AGENT_GLOSSARY.md
```

确认运行器（Windows / Unix 自动选）：

```bash
# Windows
.\\venv\\Scripts\\python.exe -m src.cli.commands --help
# Unix
./venv/bin/python -m src.cli.commands --help
# 没有 venv 时
python -m src.cli.commands --help
```

识别目标：

- `$ARGUMENTS` 是目录 → 该目录是 VPlan 项目或 spec 目录；
- 是文件 → 该文件是 spec；
- 为空 → 在 `specs/` 下找唯一项目；有多个时先问人，不许猜。

产出 `.claude_verify/00_intake.md`，记录：

- 项目路径 / module / DUT；
- spec 文件；
- 是否有 VPlan（`docs/specs` + `data/contract_matrix` + `cases`）；
- EDA 是否可用（`vsim`/`vlog`/`vcover`）；
- 当前 phase 与阻塞点。

## 2. Spec → VPlan

### 2.1 已有 VPlan 项目

```bash
<PY> -m src.cli.commands vplan status <project>
```

检查：

- requirements / features / contracts / TP / cases 数量；
- `contracts_by_status` 是否全 `assume`；
- `review.reviewed` 是否为 true；
- `warnings`。

### 2.2 没有 VPlan

不要手写一整套 CSV 冒充“已完成”。用现有 front/bootstrap：

```bash
<PY> -m src.cli.commands verify <spec> -o output_bootstrap --approval auto --no-checkpoint
```

只允许它做 **spec 分析 / bootstrap**；EDA 阶段失败就停，不要为了跑完而关闭门禁。
如果 `verify` 不可用，明确告诉用户需要先有 VPlan 项目或 spec intake。

### 2.3 人工 review（强制）

```bash
<PY> -m src.cli.commands vplan review <project> --by <name>
<PY> -m src.cli.commands vplan review <project> --check
```

review 前必须检查：

- 模块名、接口、寄存器是否与 spec/RTL 一致；
- 每个 `C-*` 是否有 `check_method` / `check_artifact`；
- 每个 TP 是否有可执行 case；
- 每个 case 是否有 stimulus / checker / contract_id。

review 后写 `docs/verification/01_vplan_summary.md`：
需求→feature→contract→TP→case 的追溯表 + 未决问题。

## 3. 环境架构文档

写 `docs/verification/02_env_architecture.md`，至少包含：

- DUT 顶层、接口列表、clock/reset；
- UVM 组件图：agent / driver / monitor / sequencer / scoreboard / coverage；
- 每个 agent 的 transaction、interface、config_db；
- scoreboard 的比对对象与 `check_artifact`；
- 覆盖率点（covergroup / bin）到 `C-*` 的映射；
- 回归分层（smoke / loopback / full）与通过标准；
- 未决问题。

不要写“应该能工作”这种话；每条结论要指向 spec/RTL 文件或 VPlan 行。

## 4. 模型架构文档

写 `docs/verification/03_model_architecture.md`，至少包含：

- 参考模型类型（TLM / golden / Python / SV）；
- 模型接口与事务级契约；
- 与 DUT 的时序/延迟/复位约定；
- 模型覆盖的操作码/边界/异常；
- scoreboard 如何消费模型输出；
- 模型占位符检测（禁止 `a+b` 模板模型通过签核）；
- 未决问题。

模型必须和 DUT 共享同一份 spec/契约；不要让模型自己猜协议。

## 5. 环境架构实现

实现顺序：

1. `verify` skill 生成 UVM 骨架；
2. 补 agent / driver / monitor / scoreboard / coverage；
3. `vplan package-assets <run>` 整理 `sv/`；
4. `vplan scan-assets <run> --check` 校验锚点。

命令：

```bash
<PY> -m src.cli.commands vplan execute <project> --dry-run
<PY> -m src.cli.commands vplan execute <project> -o <run> --max-rounds 1 --sim-mode cov
<PY> -m src.cli.commands vplan package-assets <run>
<PY> -m src.cli.commands vplan scan-assets <run> --check
```

没有 EDA 时，在 `docs/verification/04_env_impl.md` 明确写
**BLOCKED_EDA_MISSING**，不要继续宣称环境稳定。

## 6. 模型架构实现

实现：

- 参考模型 / golden；
- 事务转换与比对；
- 复位/异常/背压路径；
- 覆盖率模型（与 DUT 同一组 bin）。

验证：

- 先跑 model-only 单测；
- 再跑 loopback；
- 最后跑 DUT vs model。

产出 `docs/verification/05_model_impl.md`，记录模型类型、占位符检查、未覆盖分支。

## 7. 环境 agent 稳定性

至少检查：

- 每个 agent 能独立 `build/connect/run`；
- driver 不在 reset 阶段驱动 X；
- monitor 能采到 transaction；
- scoreboard 能收到并比对；
- objection 成对；
- 队列/端口不泄漏；
- loopback 通过。

命令：

```bash
<PY> -m src.cli.commands vplan execute <project> -o <run> --max-rounds 2 --sim-mode cov
<PY> -m src.cli.commands vplan scan-assets <run> --check
```

产出 `docs/verification/06_env_stability.md`：每个 agent 的状态 + 证据路径 + 未决问题。

## 8. Case 用例撰写

每个 case 必须带：

```yaml
case_id: TC_...
contract_id: C-...
title: ...
stimulus:
  ...
checker:
  ...
coverage:
  - ...
```

规则：

- 每个 `C-*` 至少一个 case；
- 每个 case 映射至少一个 TP；
- 边界/异常/复位/背压都要有；
- 不写“预期通过”而没有 checker 的用例；
- 新增/修改后重新 `vplan build` 并人工 review。

产出 `docs/verification/07_cases.md`：case 矩阵 + 缺口 + 未决问题。

## 9. 回归 / 覆盖率 / 决策

```bash
<PY> -m src.cli.commands vplan execute <project> -o <run> --max-rounds 3 --sim-mode cov
<PY> -m src.cli.commands vplan link <project> <run>
<PY> -m src.cli.commands vplan gate <project>
<PY> -m src.cli.commands vplan gate <project> --apply
```

决策只看证据：

- `coverage` / `functional_coverage`；
- regression failed / compile；
- TP covered / attempted；
- contract obligations `PROVEN/PARTIAL/...`；
- asset anchors；
- `signoff_evidence` 哈希。

产出 `docs/verification/08_signoff.md`：

- coverage before/after；
- 每条 `C-*` 的状态与证据；
- gate 结果（blocked/eligible）；
- 明确“可签 / 不可签 / 缺什么”。

## 10. 输出

最终给用户：

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

外加：

- 实际执行的命令；
- 证据路径；
- 未决问题；
- 是否通过 review/gate；
- 如果没有 EDA，明确 `BLOCKED_EDA_MISSING`。

## 11. 停止条件

遇到以下任一情况，停下来报告，不要“想办法跑完”：

- 没有 spec / RTL / VPlan；
- VPlan 未 review 或 review 过期；
- 没有 QuestaSim / vlog / vsim；
- gate blocked 且没有新证据；
- 模型是占位符；
- 证据链哈希不一致；
- 需要修改 `main/` 但没有 proposal/gate。

## 12. 与 workspace 的分工

- `.claude/verify` 负责 **验证流程**：spec/VPlan/架构/实现/case/回归/签核。
- `workspace` 负责 **改文件沙箱**：`main` 只读，`staging` 可写，出口是 proposal + gate。
- 任何对 `main/` 的修改必须走 `workspace propose → gate → approve → promote`；不要直接写 main。
