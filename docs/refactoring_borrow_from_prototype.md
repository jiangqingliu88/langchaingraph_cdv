# 借鉴原型架构的增量重构方案

> **核心原则：加法重构，不减法。** 不改 12 个 Agent 内部逻辑，不改 ToolHub，不改证据链。在原架构之上加一层"原型风格"的轻量入口，让简单场景简单用，复杂场景全量用。
>
> 日期：2026-08-10

---

## 〇、为什么要做这件事

当前架构在"能力上限"上远超原型——LLM 驱动、真实 EDA 集成、证据链——但在"使用体验"上被原型反超了几条街：

```
原型：python main.py plan --spec uart.md --task-type fast_qa
      → 一条命令，4 步跑完，中间问 4 次 y/n，输出 spa.json

当前：vagent verify --workflow full --spec uart.md
      → 一条命令，12 步跑完，没有审批点，输出分散在目录树 + SQLite 里
```

**问题不在于能力不够，在于"简单场景的入口太复杂"。**

这个重构的目标就是：**在不动当前架构的前提下，加一层原型风格的轻量入口。就像 Git 的 `--porcelain` vs `--plumbing`——原型是 porcelain，当前 Agent 管道是 plumbing。**

---

## 一、借鉴清单：原型 5 个设计，当前架构逐一消化

| # | 原型的做法 | 原型代码 | 当前缺失 | 重构方式 |
|:--:|-----------|---------|---------|---------|
| 1 | `--task-type fast_qa/final_signoff` | `build_stages(task_type)` | `_WORKFLOW_PHASE_MAP` 未暴露 | 加 `--profile` 参数 |
| 2 | `input("y/n/q?")` 人工审批 | `if stage.requires_approval: input()` | 零审批机制 | 加 ApprovalGate 模块 |
| 3 | SPA JSON 单文件快照 | `json.dump(spa, f)` | 目录树 + DB | report_generator 加 `--format summary-json` |
| 4 | `python main.py plan` 一条命令 | `cmd_plan()` | 分散在 50+ 子命令中 | 加 `vagent plan` 聚合命令 |
| 5 | `ctx = {}` 统一状态字典 | `ctx["_history"].append(...)` | 拆在 4 个模块里 | 不重构，但暴露 `ctx.summary()` |

---

## 二、重构项 1：`--profile` 工作流快速切换（~60 行）

### 2.1 原型启发

```python
# 原型：两种任务类型，4 步 vs 8 步
def build_stages(task_type: str) -> List[Dict]:
    if task_type == "fast_qa":
        return base        # RTL编译→UVM编译→时序→Smoke
    if task_type == "final_signoff":
        return base + full # +测试生成→回归→覆盖率→签核
```

### 2.2 当前已有的基础

`src/core/execution.py` 里已经有 `_WORKFLOW_PHASE_MAP`：

```python
# 推测现有结构（需确认实际代码）
_WORKFLOW_PHASE_MAP = {
    "full": [spec_planner, design_architect, verify_architect, model_agent, 
             write_rtl, test_engineer, assertion_engineer, coverage_manager,
             regression_manager, debug_engineer, quality_assurance, report_generator],
    "verify_only": [spec_planner, verify_architect, test_engineer, 
                    regression_manager, coverage_manager, report_generator],
    # ...
}
```

### 2.3 重构实现

在 `src/cli/commands.py` 的 `verify` 命令加 `--profile` 参数：

```python
# src/cli/commands.py — verify 命令增强（增量修改，~60 行）

# 预置 profile → workflow 映射
VERIFY_PROFILES = {
    "quick": {
        "description": "快速质量检查：编译 + 冒烟 + QA 审查",
        "phases": ["design_architect", "write_rtl", "verify_architect", 
                   "quality_assurance"],
        "approval_gates": ["write_rtl", "verify_architect"],  # 关键阶段需审批
    },
    "standard": {
        "description": "标准验证流程：设计 + UVM + 测试 + 回归 + 报告",
        "phases": ["spec_planner", "design_architect", "verify_architect",
                   "write_rtl", "test_engineer", "regression_manager",
                   "coverage_manager", "report_generator"],
        "approval_gates": ["design_architect", "verify_architect"],
    },
    "full": {
        "description": "完整签核流程：全部 12 个 Agent + 断言 + 调试 + 证据链",
        "phases": None,  # None = 走默认全部 12 步
        "approval_gates": [],
    },
    "debug": {
        "description": "调试模式：只跑失败分析",
        "phases": ["debug_engineer"],
        "approval_gates": [],
    },
    "spec_only": {
        "description": "只做规格分析，输出结构化测试计划",
        "phases": ["spec_planner"],
        "approval_gates": [],
    },
}

@cli.command()
@click.option("--spec", required=True, help="规格文档路径")
@click.option("--profile", type=click.Choice(list(VERIFY_PROFILES.keys())),
              default="standard", help="验证流程预设")
@click.option("--workflow", help="自定义 workflow（覆盖 --profile）")
@click.option("--approval", type=click.Choice(["interactive", "auto", "threshold"]),
              default="auto", help="审批模式")
@click.option("--output-dir", default=None, help="输出目录")
@click.option("--json", is_flag=True, help="JSON 格式输出")
@click.option("--resume", help="断点续跑 run_id")
def verify(spec, profile, workflow, approval, output_dir, json, resume):
    """运行验证流水线"""
    # 1. 解析 profile → phases
    if workflow:
        phases = workflow.split(",")
    else:
        profile_config = VERIFY_PROFILES[profile]
        phases = profile_config["phases"]
        if phases is None:
            phases = [p["name"] for p in FULL_PHASES]  # 全量 12 步
    
    # 2. 合并审批门控
    approval_gates = profile_config.get("approval_gates", [])
    
    # 3. 打印计划（像原型那样先告诉用户要做什么）
    click.echo(f"\n🧠 SignOffAI 验证计划")
    click.echo(f"   任务类型: {profile}")
    click.echo(f"   执行阶段: {len(phases)} 个")
    click.echo(f"   审批模式: {approval}")
    click.echo(f"   审批节点: {len(approval_gates)} 个")
    for i, phase in enumerate(phases):
        gate_mark = "🔴" if phase in approval_gates else "⏩"
        click.echo(f"   {gate_mark} [{i+1}/{len(phases)}] {phase}")
    
    # 4. 执行（复用现有 PipelineExecutionService）
    if approval == "interactive" and approval_gates:
        click.echo("\n⚠️  交互审批模式：关键阶段将暂停等待确认\n")
    
    # ... 调用现有执行引擎
```

### 2.4 效果

```bash
# 原型风格：一行命令，快速检查
vagent verify --spec uart.md --profile quick --approval interactive
# → 4 个阶段 + 2 个审批点，5 分钟出结果

# 标准验证
vagent verify --spec uart.md --profile standard
# → 8 个阶段，无需审批，自动跑完

# 完整签核
vagent verify --spec uart.md --profile full
# → 12 个 Agent 全跑，适合最终签核
```

---

## 三、重构项 2：人工审批门控（~120 行新文件）

### 3.1 原型启发

```python
# 原型：简单粗暴但有效
if stage.get("requires_approval", False):
    user_input = input(f"确认 {stage['name']} 通过并继续？ (y/n/q): ")
    if user_input == 'n':
        return ctx   # 终止
```

### 3.2 问题

原型的 `input()` 有三个局限：
- **CI 不兼容**：`input()` 会永久阻塞 CI pipeline
- **粒度太粗**：只能 y/n/q，没有"跳过但仍记录"或"查看详情再决定"
- **没有审计**：审批决策存在内存里，没有持久化

### 3.3 重构实现

新建 `src/core/approval.py`（不修改任何现有模块）：

```python
# src/core/approval.py — 新增文件，~120 行
"""人工审批门控模块。借鉴原型设计的 input() 审批，升级为多模式可配置版本。"""

import json
import sys
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field

# ── 审批决策 ────────────────────────────────────────────

class ApprovalDecision(str, Enum):
    APPROVE = "approve"     # 通过，继续
    REJECT = "reject"       # 拒绝，终止流程
    SKIP = "skip"           # 跳过此阶段，继续后续
    REVIEW = "review"       # 查看详情后再决定

# ── 审批记录 ────────────────────────────────────────────

@dataclass
class ApprovalRecord:
    stage: str
    decision: ApprovalDecision
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    reviewer: str = "human"
    reason: str = ""
    context_snapshot: Optional[Dict] = None  # 审批时的上下文快照

# ── 审批模式 ────────────────────────────────────────────

class ApprovalMode(str, Enum):
    INTERACTIVE = "interactive"   # 终端交互：input() 等待 y/n
    AUTO = "auto"                 # 全自动：全部自动通过（CI 模式）
    THRESHOLD = "threshold"       # 阈值模式：只有风险 > threshold 才审批

# ── 审批门控 ────────────────────────────────────────────

class ApprovalGate:
    """审批门控 — 借鉴原型 input() 但升级为多模式可配置"""

    def __init__(
        self,
        mode: ApprovalMode = ApprovalMode.AUTO,
        risk_threshold: str = "high",
        input_func: Callable = input,       # 可注入，方便测试
        output_func: Callable = print,      # 可注入
    ):
        self.mode = mode
        self.risk_threshold = risk_threshold
        self._input = input_func
        self._output = output_func
        self.records: List[ApprovalRecord] = []

    def requires_approval(self, stage_name: str, risk_level: str = "low") -> bool:
        """判断阶段是否需要审批"""
        if self.mode == ApprovalMode.AUTO:
            return False
        if self.mode == ApprovalMode.INTERACTIVE:
            return True
        if self.mode == ApprovalMode.THRESHOLD:
            risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            return risk_order.get(risk_level, 0) >= risk_order.get(self.risk_threshold, 1)
        return False

    def ask(self, stage_name: str, summary: str, risk_level: str = "low") -> ApprovalRecord:
        """执行审批询问"""
        # 先判断是否需要审批
        if not self.requires_approval(stage_name, risk_level):
            record = ApprovalRecord(
                stage=stage_name,
                decision=ApprovalDecision.APPROVE,
                reason=f"自动通过 (模式: {self.mode.value})"
            )
            self.records.append(record)
            return record

        # 交互审批
        self._output(f"\n{'='*60}")
        self._output(f"🔴 审批节点: {stage_name}")
        self._output(f"   风险等级: {risk_level.upper()}")
        self._output(f"   摘要: {summary}")
        self._output(f"{'='*60}")

        while True:
            choice = self._input(
                f"  确认通过并继续？\n"
                f"  [y] 通过  [n] 拒绝(终止)  [s] 跳过此阶段  [d] 查看详情  [q] 退出\n"
                f"  选择: "
            ).strip().lower()

            if choice == 'y':
                decision = ApprovalDecision.APPROVE
                break
            elif choice == 'n':
                decision = ApprovalDecision.REJECT
                break
            elif choice == 's':
                decision = ApprovalDecision.SKIP
                break
            elif choice == 'd':
                self._output(f"  📋 完整上下文: {summary}")
                continue
            elif choice == 'q':
                self._output("🛑 用户退出流程")
                sys.exit(0)
            else:
                self._output("  请输入 y/n/s/d/q")

        record = ApprovalRecord(
            stage=stage_name,
            decision=decision,
            reason=f"用户手动选择: {choice}"
        )
        self.records.append(record)

        if decision == ApprovalDecision.REJECT:
            self._output(f"⛔ 用户拒绝 {stage_name}，流程终止。")
            self._output(f"   已通过的审批: {len([r for r in self.records if r.decision == ApprovalDecision.APPROVE])} 条")

        return record

    def summary(self) -> Dict:
        """输出审批摘要（对标原型的 spa['approvals']）"""
        return {
            "total_gates": len(self.records),
            "approved": len([r for r in self.records if r.decision == ApprovalDecision.APPROVE]),
            "rejected": len([r for r in self.records if r.decision == ApprovalDecision.REJECT]),
            "skipped": len([r for r in self.records if r.decision == ApprovalDecision.SKIP]),
            "records": [
                {
                    "stage": r.stage,
                    "decision": r.decision.value,
                    "timestamp": r.timestamp,
                    "reason": r.reason,
                }
                for r in self.records
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.summary(), indent=2, ensure_ascii=False)


# ── 便捷工厂函数 ────────────────────────────────────────

def create_approval_gate(mode: str) -> ApprovalGate:
    """从 CLI 参数创建审批门控"""
    mode_map = {
        "interactive": ApprovalMode.INTERACTIVE,
        "auto": ApprovalMode.AUTO,
        "threshold": ApprovalMode.THRESHOLD,
    }
    return ApprovalGate(mode=mode_map.get(mode, ApprovalMode.AUTO))
```

### 3.4 在流水线中集成（增量修改 step_executor.py）

```python
# src/core/step_executor.py — 增量修改，~15 行

# 在阶段执行前后插入审批检查
from src.core.approval import ApprovalGate, ApprovalDecision

class StepExecutor:
    def __init__(self, ..., approval_gate: Optional[ApprovalGate] = None):
        self.approval_gate = approval_gate

    def execute_step(self, step_name: str, ...):
        result = self._run_agent(step_name, ...)
        
        # 审批门控（新增 ~10 行）
        if self.approval_gate:
            record = self.approval_gate.ask(
                stage_name=step_name,
                summary=self._build_summary(result),
                risk_level=self._assess_risk(result),
            )
            if record.decision == ApprovalDecision.REJECT:
                raise PipelineTerminatedError(f"用户拒绝 {step_name}")
            if record.decision == ApprovalDecision.SKIP:
                return None  # 跳过，继续下一步
        
        return result
```

### 3.5 效果

```bash
# 终端交互审批（原型风格）
vagent verify --spec uart.md --profile quick --approval interactive

# 输出:
# 🔴 审批节点: write_rtl
#    风险等级: MEDIUM
#    摘要: 生成 3 个模块 (uart_core, baud_gen, tx_fifo)，编译通过 0 errors
#   确认通过并继续？
#   [y] 通过  [n] 拒绝(终止)  [s] 跳过此阶段  [d] 查看详情  [q] 退出
#   选择: y
# ✅ 审批通过，继续下一阶段。

# CI 全自动
vagent verify --spec uart.md --approval auto --json
```

---

## 四、重构项 3：SPA 摘要 JSON 输出（~40 行增量修改）

### 4.1 原型启发

```python
# 原型：一份 JSON 看清全部
spa = {
    "spa_id": "spa_abc123",
    "stages_executed": [...],
    "history": [...],        # 每步的工具调用 + 结果
    "approvals": [...],      # 每步的审批决策
    "coverage": {...},       # 覆盖率数据
    "regression": {...},     # 回归结果
}
json.dump(spa, f, indent=2)
```

### 4.2 当前问题

当前输出结构（推测）：

```
output_jiang_20260809_143022/
├── manifest.json           ← 每个阶段的输入输出 hash
├── evidence_chain/         ← 5 层证据链
│   ├── L1_spec_planner/
│   └── L2_design_architect/
├── artifacts/
├── coverage/
├── regression/
└── signoff_report.html     ← 最终报告
```

**问题：** 要了解全局状态，需要打开 5+ 个文件和 SQLite。原型一份 JSON 就能回答"发生了什么"。

### 4.3 重构实现

在 `report_generator` 的输出中加一个 `--format summary-json` 选项：

```python
# src/agents/report_generator/main.py — 增量修改，~40 行

def generate_summary_json(run_context: Dict) -> str:
    """
    生成 SPA 风格的摘要 JSON（对标原型输出）。
    不替代完整证据链——只提供快速概览。
    """
    # 从 context.py 和 manifest.py 聚合数据
    stages_executed = []
    history = []
    
    for step in run_context.get("_history", []):
        stages_executed.append(step["stage"])
        history.append({
            "stage": step["stage"],
            "tool": step.get("tool", "llm_agent"),
            "timestamp": step.get("timestamp"),
            "status": step.get("result", {}).get("status", "UNKNOWN"),
            "summary": step.get("summary", ""),
            "artifacts": step.get("artifacts", []),
        })
    
    spa = {
        "spa_id": run_context.get("run_id"),
        "profile": run_context.get("profile", "standard"),
        "version": "1.0",
        "created_at": run_context.get("started_at"),
        "completed_at": run_context.get("completed_at"),
        "stages_executed": stages_executed,
        "history": history,
        "approvals": run_context.get("approval_summary", {}),
        "coverage": run_context.get("coverage", {}),
        "regression": run_context.get("regression", {}),
        "quality_score": run_context.get("quality_score"),
        "evidence_chain_hash": run_context.get("evidence_chain_hash"),
    }
    
    output_path = run_context["output_dir"] / "spa_summary.json"
    with open(output_path, 'w') as f:
        json.dump(spa, f, indent=2, ensure_ascii=False)
    
    return output_path


# 在 report_generator 的 prompt 中注册这个函数为可用工具
```

### 4.4 效果

```bash
# 跑完流水线后
vagent show output_jiang_20260809_143022/spa_summary.json

# 输出（对标原型的 cmd_show）：
📖 SPA ID: run_20260809_143022
任务类型: standard
执行阶段: spec_planner, design_architect, verify_architect, write_rtl,
          test_engineer, regression_manager, coverage_manager, report_generator
审批记录: 2 条
  - design_architect: approve @ 2026-08-09T14:30:22
  - verify_architect: approve @ 2026-08-09T14:32:15
覆盖率: functional 98.5%, line 97.8%
回归: 10/10 passed
签核证据: 已在 output_jiang_20260809_143022/evidence_chain/
```

---

## 五、重构项 4：`vagent plan` 聚合命令（~100 行新命令）

### 5.1 原型启发

```python
# 原型：计划 + 执行 + 展示，三个步骤两种组合
parser_plan  → cmd_plan()   → agent.plan(spec)  → spa.json
parser_show  → cmd_show()   → print(spa.summary)
```

### 5.2 问题

当前 CLI 中，用户想做"从 Spec 出发跑完整流程 + 看结果"需要记住：
```bash
vagent verify --spec xx.md --profile standard --output-dir xxx
vagent dump <run_id>
vagent signoff generate <run_id>
vagent signoff --verify <run_id>
```

### 5.3 重构实现

加一个 `vagent plan` 命令——把"计划→执行→摘要"揉成一条命令：

```python
# src/cli/commands.py — 新增 plan 命令，~100 行

@cli.command()
@click.argument("spec", type=click.Path(exists=True))
@click.option("--profile", type=click.Choice(list(VERIFY_PROFILES.keys())),
              default="standard", help="验证流程预设")
@click.option("--approval", type=click.Choice(["interactive", "auto", "threshold"]),
              default="auto", help="审批模式")
@click.option("--output", default=None, help="输出目录")
@click.option("--dry-run", is_flag=True, help="只打印计划，不执行")
@click.option("--json", is_flag=True, help="JSON 格式输出")
@click.pass_context
def plan(ctx, spec, profile, approval, output, dry_run, json):
    """
    一站式验证计划：从 Spec 到签核报告。
    
    对标原型 python main.py plan --spec xx.md --task-type xx
    
    \b
    示例:
      vagent plan uart_spec.md                              # 标准流程
      vagent plan uart_spec.md --profile quick --approval interactive  # 快速+人工审批
      vagent plan uart_spec.md --profile full               # 完整签核
      vagent plan uart_spec.md --dry-run                    # 只看计划不执行
    """
    # 1. 解析 profile → phases
    profile_config = VERIFY_PROFILES[profile]
    phases = profile_config["phases"]
    if phases is None:
        phases = [p["name"] for p in FULL_PHASES]
    approval_gates = profile_config.get("approval_gates", [])
    
    # 2. 打印计划（像原型那样）
    click.echo(f"\n🧠 SignOffAI 验证计划")
    click.echo(f"   Spec:     {spec}")
    click.echo(f"   Profile:  {profile} ({profile_config['description']})")
    click.echo(f"   阶段数:   {len(phases)}")
    click.echo(f"   审批模式: {approval}")
    click.echo(f"   审批节点: {len(approval_gates)} 个")
    click.echo()
    for i, phase in enumerate(phases):
        gate_mark = "🔴审批" if phase in approval_gates else "  ⏩"
        click.echo(f"   [{i+1}/{len(phases)}] {gate_mark}  {phase}")
    
    if dry_run:
        click.echo("\n📋 Dry-run 模式，不执行。")
        return
    
    # 3. 确认开始
    if approval == "interactive":
        confirm = click.confirm("\n开始执行？", default=True)
        if not confirm:
            click.echo("已取消。")
            return
    
    # 4. 执行（委托给现有的 verify 命令）
    click.echo(f"\n▶️ 开始执行...")
    ctx.invoke(
        verify,
        spec=spec,
        profile=profile,
        workflow=None,
        approval=approval,
        output_dir=output,
        json=json,
        resume=None,
    )
    
    # 5. 输出摘要（像原型 cmd_show 那样）
    click.echo(f"\n✅ 验证完成")
```

### 5.4 效果

```bash
# 最简用法 —— 对标原型
vagent plan uart_spec.md --profile quick --approval interactive

# 输出：
# 🧠 SignOffAI 验证计划
#    Spec:     uart_spec.md
#    Profile:  quick (快速质量检查：编译 + 冒烟 + QA 审查)
#    阶段数:   4
#    审批模式: interactive
#    审批节点: 2 个
# 
#    [1/4] 🔴审批  design_architect
#    [2/4]   ⏩    write_rtl
#    [3/4] 🔴审批  verify_architect
#    [4/4]   ⏩    quality_assurance
# 
# 开始执行？ [Y/n]: 
# ▶️ 开始执行...
# ... [流水线执行] ...
# ✅ 验证完成
# 📊 4/4 阶段通过，覆盖率 98.5%，详见 output_xxx/spa_summary.json
```

---

## 六、重构项 5：统一 `ctx` 状态视图（~0 行新代码，只改调用方式）

### 6.1 原型启发

```python
# 原型：ctx 是一个字典，贯穿整个过程
ctx = {
    "spec": spec_content,
    "_history": [],       # append-only 日志
    "_approvals": [],     # append-only 审批记录
    # + 每个阶段的输出直接写进 ctx
    "coverage_report": {...},
    "regression_results": {...},
}

# 任何时候都能看到全局状态
print(ctx["_history"][-1])     # 最后一步做了什么
print(ctx["_approvals"])       # 所有审批决策
```

### 6.2 当前状态

当前架构把 ctx 拆分到了多个模块：

| 原型 ctx 字段 | 当前对应的模块 | 
|--------------|-------------|
| `_history` | `manifest.py` + `evidence.py` |
| `_approvals` | 无（新增的 `approval.py`） |
| 阶段输出 | `context.py` 的三层结构 (config/state/data) |
| 恢复能力 | `checkpoint.py` |

**不改这些模块。** 它们各司其职是对的。但要加一个 `.summary()` 方法到 `context.py`：

```python
# src/core/context.py — 增量修改，~20 行

class PipelineContext:
    # ... 现有代码 ...
    
    def summary(self) -> Dict:
        """
        返回扁平摘要（对标原型的 ctx 字典视图）。
        不替代分层结构，只提供快速概览。
        """
        return {
            "run_id": self.run_id,
            "spec": self.state.get("spec_summary", ""),
            "phases_completed": [
                p for p in self.state.get("phases", [])
                if p.get("status") == "completed"
            ],
            "phases_failed": [
                p for p in self.state.get("phases", [])
                if p.get("status") == "failed"
            ],
            "current_phase": self.state.get("current_phase"),
            "artifacts": self.state.get("artifacts", []),
            "coverage": self.state.get("coverage", {}),
            "regression": self.state.get("regression", {}),
        }
```

---

## 七、改动汇总

### 7.1 新增文件

| 文件 | 行数 | 职责 |
|------|:---:|------|
| `src/core/approval.py` | ~120 | 审批门控模块（多模式 + 审计记录） |

### 7.2 修改文件

| 文件 | 新增行数 | 改什么 |
|------|:---:|------|
| `src/cli/commands.py` | ~160 | `--profile` 参数 + `vagent plan` 命令 + `VERIFY_PROFILES` 配置 |
| `src/core/step_executor.py` | ~15 | 在阶段边界插入 `ApprovalGate.ask()` |
| `src/agents/report_generator/main.py` | ~40 | `generate_summary_json()` 函数 |
| `src/core/context.py` | ~20 | `PipelineContext.summary()` 方法 |

### 7.3 不受影响的模块

```
✅ 12 个 Agent —— 内部逻辑不动
✅ src/core/tool_protocol.py —— 工具协议不变
✅ src/core/tool_hub.py —— 工具注册不变
✅ src/core/evidence.py —— 证据链不变
✅ src/core/manifest.py —— Manifest 不变
✅ src/core/checkpoint.py —— 断点续跑不变
✅ src/core/execution.py —— PipelineExecutionService 不变（只通过参数裁剪 phases）
✅ src/tools/* —— 所有工具不变
```

### 7.4 总工作量

| 阶段 | 内容 | 时间 |
|------|------|:---:|
| 实现 `approval.py` | 新文件，含测试 | 2 小时 |
| 改 `commands.py` | `--profile` + `vagent plan` | 2 小时 |
| 改 `step_executor.py` | 插入审批钩子 | 30 分钟 |
| 改 `report_generator` | `generate_summary_json` | 1 小时 |
| 改 `context.py` | `.summary()` 方法 | 30 分钟 |
| 集成测试 | 验证交互/auto/threshold 三种模式 | 2 小时 |
| 文档 | 更新 CLI_USAGE.md | 1 小时 |
| **总计** | | **~9 小时（1-2 个工作日）** |

---

## 八、重构前后体验对比

### Before（当前）

```bash
# 要跑一个快速验证，用户需要：
vagent verify --spec uart.md --workflow design_architect,write_rtl,verify_architect,quality_assurance
# → 记不住 workflow 参数
# → 没有审批，错了也不知道
# → 输出分散，要找 5 个文件才能看清结果
```

### After（重构后）

```bash
# 同样的需求：
vagent plan uart.md --profile quick --approval interactive
# → 命令好记（对标原型 python main.py plan）
# → 关键阶段人工确认
# → 一份 spa_summary.json 看清全部
# → --profile full 随时升级到完整签核
```

---

## 九、和前面三份文档的关系

```
docs/refactoring_borrow_from_prototype.md  ← 本文：具体的增量重构方案
     │
     │  依赖前面的分析：
     ├── prototype_vs_current_architecture.md  ← 识别了差距
     ├── agent_workflow_vs_engineer_mindset.md ← 验证了 Agent 的正确性
     └── llm_vs_traditional_tools_analysis.md  ← 确认了 LLM/工具分工
     
     │  与并行重构独立：
     └── refactoring_remove_dvsim.md  ← 删除 dvsim（独立操作，互不干扰）
```

**两份重构文档可以并行执行——它们改动的是不同文件、不同模块，没有冲突。**

---

## 十、一句话总结

> **原型教会我们的事：好的工具应该让用户用一条命令开始，用一份 JSON 看清楚，用一次审批停下来想。当前架构不缺能力——缺的是这种"轻盈感"。这个重构就是在不动骨架的前提下，给当前架构穿上原型的衣服。**
