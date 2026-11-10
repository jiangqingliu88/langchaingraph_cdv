"""
SignOffAI CLI — 增强版命令行接口

对标 git/docker 的命令行体验，支持 CI/CD 集成和交互式调试。
23 个命令组，50+ 子命令。

用法:
  vagent --help
  vagent verify --help
  vagent signoff <run_id> --type tapeout
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# ── UTF-8 强制编码 (修复 Windows 中文乱码) ──
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# `python -m src.cli.commands` 把本文件当 `__main__` 执行；拆出的命令模块
# 若 `from src.cli.commands import cli` 会再加载一份模块、注册到另一个 cli。
# 这里把 `__main__` 别名为正式模块名，保证**只有一个 cli 对象**。
if __name__ == "__main__" and "src.cli.commands" not in sys.modules:
    sys.modules["src.cli.commands"] = sys.modules["__main__"]


# ── structlog 统一写 stderr（stdout 保留给业务输出/--json，不被日志污染）──
import structlog  # noqa: E402
structlog.configure(logger_factory=structlog.WriteLoggerFactory(sys.stderr))

from src.layers.l2_orchestration.executors.registry import ExecutorRegistry
from src.layers.l2_orchestration.execution import PipelineExecutionService
from src.layers.l2_orchestration.governance.approval import create_approval_gate, ApprovalDecision, PipelineTerminatedError
from src.cli.output import OutputAdapter, common_options, get_output_adapter

console = Console()

# 退出码与无状态 helper 已搬到 `src/cli/common.py`；这里 re-export，拆出的
# `cmd_*` 模块继续 `from src.cli.commands import ...`，不用跟着改。
from src.cli.common import (  # noqa: E402,F401
    EXIT_FAIL, EXIT_LAYER_VIOLATION, EXIT_OK, EXIT_STRICT, EXIT_USAGE,
    EXIT_WAITING, _approver_name, _extract_requirements_from_md,
    _get_git_info, _output_gitlab_ci, _output_junit, _sha256_path,
)


def _strict_semantic_gate(run_dir: Path, run_id: str) -> None:
    """`audit` 判了 `PASS_WITH_CAVEAT` → 按 CI 的口径当失败（exit `EXIT_STRICT`）。

    读 `<run>/report.json` 的 `verdict` / `caveats` —— 那是 audit 的**唯一**结论
    出处，这里只决定处置。报告不存在（没跑到 audit / 老 run 目录）就**不拦**：
    门禁拿不到证据时该说"判不了"，而不是把"没报告"当成"有问题"。

    只升格 `PASS_WITH_CAVEAT`：`READY` 放行、`NEEDS_FIX` 本来就会以非零码收场
    （那是另一条路的事，不在这里抢）。
    """
    report = run_dir / "report.json"
    try:
        doc = json.loads(report.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        console.print(f"[dim]--strict-semantic：读不到 {report.name}，这一轮没有可判的签核结论"
                      f"（不拦）[/dim]")
        return
    if doc.get("verdict") != "PASS_WITH_CAVEAT":
        return
    console.print()
    console.print(Panel.fit(
        f"[bold]--strict-semantic：签核判为 PASS_WITH_CAVEAT[/bold]\n"
        f"硬门禁都过了，但有 {len(doc.get('caveats') or [])} 条**软缺口** —— "
        f"这些正是「绿但没真生效」的地方：\n\n"
        + "\n".join(f"  · {c}" for c in (doc.get("caveats") or []))
        + f"\n\n完整报告：{report}",
        title=f"[red]严格语义：拒绝[/red]", border_style="red"))
    sys.exit(EXIT_STRICT)

# ═══════════════════════════════════════════════════════════════
# Agent 初始化
# ═══════════════════════════════════════════════════════════════

# 七 Agent 角色映射（闭环架构 design/model/verify/ops/coverage/debug/audit）
AGENT_ALIASES = {
    "design": "design", "model": "model", "verify": "verify",
    "ops": "ops", "coverage": "coverage", "debug": "debug", "audit": "audit",
}
AGENT_HELP = ", ".join(AGENT_ALIASES.keys())


class VerificationCLI:
    """CLI Agent 初始化器 (向后兼容)"""

    def __init__(self):
        self.settings = None
        self.registry = ExecutorRegistry.get_instance()
        self.agent_config = {}

    async def initialize(self):
        from src.executors import DesignExecutor, ModelExecutor, VerifyExecutor, OpsExecutor, CoverageExecutor, DebugExecutor, AuditExecutor
        agents = [
            ("design", DesignExecutor()),
            ("model", ModelExecutor()),
            ("verify", VerifyExecutor()),
            ("ops", OpsExecutor()),
            ("coverage", CoverageExecutor()),
            ("debug", DebugExecutor()),
            ("audit", AuditExecutor()),
        ]
        for role, agent in agents:
            await agent.initialize()
            self.registry.set_agent_instance(role, agent)
        console.print("[green]7 agents initialized[/green]")


def _init_service():
    """初始化 PipelineExecutionService (幂等)"""
    service = PipelineExecutionService.get_instance()
    if not service.initialized:
        asyncio.run(service.initialize_agents())
    return service


def _find_run_id(run_id: str = None) -> str | None:
    """查找 run_id: 指定或最新"""
    if run_id:
        return run_id
    service = PipelineExecutionService.get_instance()
    runs = service.list_runs()
    if runs:
        return runs[-1]["run_id"]
    return None


# ═══════════════════════════════════════════════════════════════
# 主命令入口
# ═══════════════════════════════════════════════════════════════

@click.group(invoke_without_command=True)
@click.version_option(version="2.4.0", prog_name="SignOffAI")
@click.option("-p", "--print", "prompt", default="", help="单次查询模式（非交互），如 -p '生成 APB 验证计划'")
@click.option("-c", "--continue", "continue_mode", is_flag=True, help="继续上次会话")
@click.option("-r", "--resume", "resume_id", help="恢复指定会话 ID")
@click.pass_context
def cli(ctx, prompt, continue_mode, resume_id):
    """SignOffAI — AI 驱动的芯片验证签核平台

    无参数进入交互式 REPL；-p 'prompt' 单次查询；-c 继续；-r 恢复。
    """
    # 无子命令时，进入 REPL 或单次查询
    if ctx.invoked_subcommand is None:
        from src.cli.repl import run_interactive, run_once
        if prompt:
            run_once(prompt)       # vagent -p "prompt"
        elif continue_mode:
            run_interactive(continue_latest=True)   # vagent -c
        elif resume_id:
            run_interactive(session_id=resume_id)   # vagent -r <id>
        else:
            run_interactive()      # vagent 进入 REPL


# ═══════════════════════════════════════════════════════════════
# vagent dump — 复现 + 导出签核证据包
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# vagent config — 配置管理 (P2)
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# 业务 CLI 命令（RunRepository 磁盘扫描，面向工程师日常使用）
# ═══════════════════════════════════════════════════════════════

def _repo(output_base: str = "output"):
    """run 目录的读取侧。

    `output_base` 默认 `"output"`，与 `RunService` 的默认基准一致。它认两种布局：
    `output/` 与同级的 `output_*`（`make_output_root` 产出的是后者）。但
    **`vagent verify -o /别处/xx` 跑出来的运行不在这个命名空间里** —— 那时要用
    `--output-base` 指过去，否则命令只会说"找不到 run"（而它确实找不到）。
    """
    from src.layers.l2_orchestration.run_repository import RunRepository
    return RunRepository(output_base)


def _resolve_run(repo, run_id):
    """解析 run_id：指定则用，否则取最新。"""
    if run_id:
        return run_id
    runs = repo.list_runs(1)
    return runs[0]["run_id"] if runs else None


# ── 查看与诊断类 ──


# ── 人工介入与修复类 ──

def _checkpoint_db(run_dir: Path) -> Path:
    """这次运行的检查点库 —— 它在不在，决定"有没有挂起的审批可恢复"。"""
    return run_dir / "docs" / "checkpoints.sqlite"


def _resume_closed_loop(run_dir: Path, decision: str) -> dict:
    """把审批答案喂回**被 interrupt 挂起**的运行，并等它跑完。

    ## 为什么是"检查点模式"，不是 `answer_approval`

    两条路的分工（见 `run_service.resume` 的注释）：

        answer_approval   运行**还活着**，挂在某个线程上同步等答案 —— 那个进程
                          必须还在。CLI 的 `verify` 早就退出了，没有活着的图可答。
        resume（本函数）   运行**已经结束在这次 astream 上**，状态落在检查点里，
                          另一个进程（就是这里）用 `Command(resume=...)` 接着跑。

    CLI 只能走后一条：`verify` 进程退出后，唯一的现场就是 `docs/checkpoints.sqlite`。
    这也是"暂停"这个词在 CLI 上的准确含义 —— 运行没结束，只是没有进程在跑它。

    ## 为什么用 `run_dir.parent` + `run_dir.name` 当参数

    `run_closed_loop_streaming` 重入时要靠 `output_root` **基准目录** + `run_id`
    去定位这次运行（`_resolve_run_dir`）。写死基准目录 `"output"` 就只有
    `output/` 与 `output_*` 两种布局找得到 —— 而 `-o /别处/xx` 跑出来的运行
    就永远恢复不了，报的还是"找不到状态"。

    拿**目录名**当 run_id、拿**父目录**当基准，`_resolve` 第一条就命中
    （`父/名字` 就是这个目录本身），与布局无关。真实输出目录最终以检查点里的
    为准（`run_closed_loop_streaming` 里 `output_root = initial.output_root`）。
    """
    async def _run() -> dict:
        service = PipelineExecutionService.get_instance()
        return await service.run_closed_loop_streaming(
            spec_text="", output_root=str(run_dir.parent),
            run_id=run_dir.name, resume=decision, checkpointing=True)

    return asyncio.run(_run())


def _report_resume(result: dict, rid: str) -> None:
    """把恢复后的结局说清楚 —— 它可能又停在下一个人工节点上（图里不止一个）。"""
    if result.get("interrupted"):
        pending = result.get("pending") or {}
        console.print(f"[yellow]又停在一个待审批的节点上："
                      f"{pending.get('stage', 'approval')}[/yellow]")
        console.print(f"  继续：vagent resume --run {rid[:32]} --decision approve")
        return
    console.print(f"[green]运行已继续并结束：{rid[:32]}"
                  f"（状态 {result.get('status', '?')}）[/green]")


def _write_approval_record(run_dir: Path, rid: str, action: str, reason: str) -> None:
    """审计记录 —— **无论有没有挂起的图都写**。

    它是"人在什么时候为什么签了/驳了"的凭证，与"这次签核有没有真的推着图走"
    是两件事。原来只有这一半（所以才叫断链）：记录写了，没人读、也不驱动任何事。

    ## 为什么必须绑定证据哈希

    不绑定的审批记录只说明"某人点了通过"，不说明"他签的是哪一份证据"。
    证据包被替换后，旧审批仍然"有效"——那等于审批可被静默复用。这里把
    v2 manifest、v1 evidence、tp_matrix 的 sha256 一并记下，`vagent approval`
    会重新算一遍并指出不一致。
    """
    import hashlib

    evidence_files = {
        "package_manifest": run_dir / "signoff_evidence" / "manifest.json",
        "signoff_evidence": run_dir / "signoff_evidence.json",
        "tp_matrix": run_dir / "coverage" / "tp_matrix.json",
        "report": run_dir / "report.json",
    }
    evidence = {name: {"path": str(p), "sha256": _sha256_path(p)}
                for name, p in evidence_files.items() if p.is_file()}
    history = run_dir / "approvals.jsonl"
    prev_hash = ""
    try:
        if history.is_file():
            lines = [ln for ln in history.read_text(encoding="utf-8",
                                                     errors="replace").splitlines()
                     if ln.strip()]
            if lines:
                prev_hash = str((json.loads(lines[-1]) or {}).get("approval_hash") or "")
    except (OSError, ValueError):
        prev_hash = ""

    record = {
        "action": action,
        "reason": reason,
        "at": datetime.now().isoformat(),
        "run": rid,
        "approver": _approver_name(),
        "evidence": evidence,
        # **追加链**：审批历史不被覆盖；prev_hash 让"删中间一条"可被发现。
        "prev_hash": prev_hash,
    }
    # 审批记录自身的哈希：改一个字就能被发现（链外锚点）。
    record["approval_hash"] = hashlib.sha256(
        json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    # 1) append-only 历史（权威）
    with history.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    # 2) 最新视图（人读 / 旧消费者）
    (run_dir / "approval.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def _decide(rid: str, action: str, reason: str, colour: str, verb: str, repo) -> None:
    """`approve` / `reject` 的公共身体：**记审计 + 驱动恢复**。"""
    run_dir = repo._resolve(rid)
    if run_dir is None:
        console.print(f"[yellow]找不到 {rid[:32]} 的目录[/yellow]")
        return
    run_dir = Path(run_dir)
    _write_approval_record(run_dir, rid, action, reason)
    console.print(f"[{colour}]已{verb} {rid[:32]}（理由: {reason or '无'}）[/{colour}]")

    # 没有检查点 = 这次运行从来没挂起过（比如它跑完了、或压根没开检查点）。
    # **这不是错误** —— 审批记录照样是有效的审计凭证，只是没有图可推进。
    if not _checkpoint_db(run_dir).exists():
        console.print("[dim]这次运行没有检查点（没有挂起的审批）—— 只记了审批记录[/dim]")
        return

    console.print("[dim]正在把审批答案喂回挂起的运行…[/dim]")
    try:
        _report_resume(_resume_closed_loop(run_dir, action), rid)
    except Exception as exc:                          # noqa: BLE001 恢复失败要说清
        console.print(f"[red]恢复失败：{exc}[/red]")
        console.print("[dim]审批记录已保留；运行仍停在检查点上，可再试一次[/dim]")


@cli.command("approve")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--reason", default="", help="审批理由（审计用）")
@click.option("--output-base", default="output",
              help="run 目录所在基准（默认 output）。`verify -o /别处/xx` 跑出来的运行要用它指过去")
def approve(run_id, reason, output_base):
    """人工审批签核：记审计记录，**并让挂起的运行继续跑**"""
    repo = _repo(output_base)
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    _decide(rid, "approve", reason, "green", "审批", repo)


@cli.command("reject")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--reason", default="", help="驳回理由（审计用）")
@click.option("--output-base", default="output",
              help="run 目录所在基准（默认 output）")
def reject(run_id, reason, output_base):
    """人工驳回签核：记审计记录，**并让挂起的运行按驳回继续**"""
    repo = _repo(output_base)
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    _decide(rid, "reject", reason, "red", "驳回", repo)


@cli.command("approval")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--output-base", default="output",
              help="run 目录所在基准（默认 output）")
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON")
def approval_show(run_id, output_base, json_output):
    """查看审批记录，并**重算证据哈希**（审批是否仍然对应同一份证据）

    \b
    用途:
      vagent approval --run <id>          # 人读
      vagent approval --run <id> --json   # CI / 审计脚本
    """
    repo = _repo(output_base)
    rid = _resolve_run(repo, run_id)
    run_dir = repo._resolve(rid) if rid else None
    if run_dir is None:
        console.print("[yellow]找不到 run[/yellow]")
        return
    run_dir = Path(run_dir)
    path = run_dir / "approval.json"
    if not path.is_file():
        console.print("[yellow]这个 run 没有审批记录[/yellow]")
        return
    try:
        record = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except ValueError as exc:
        console.print(f"[red]审批记录读不出来：{exc}[/red]")
        return

    import hashlib

    # 追加链：检查 prev_hash 是否连续（删中间一条会暴露）
    history_path = run_dir / "approvals.jsonl"
    chain_ok = True
    history_count = 0
    try:
        if history_path.is_file():
            prev = ""
            for line in history_path.read_text(encoding="utf-8",
                                               errors="replace").splitlines():
                if not line.strip():
                    continue
                hist = json.loads(line)
                history_count += 1
                if str(hist.get("prev_hash") or "") != prev:
                    chain_ok = False
                prev = str(hist.get("approval_hash") or "")
    except (OSError, ValueError):
        chain_ok = False

    evidence = record.get("evidence") or {}
    changed = []
    for name, entry in evidence.items():
        p = Path(str(entry.get("path") or ""))
        now = _sha256_path(p) if p.is_file() else ""
        if not now or now != entry.get("sha256"):
            changed.append({"name": name, "path": str(p),
                            "recorded": entry.get("sha256"),
                            "current": now,
                            "missing": not p.is_file()})
    base = {k: v for k, v in record.items() if k != "approval_hash"}
    recomputed_hash = hashlib.sha256(
        json.dumps(base, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    result = {"record": record, "evidence_changed": changed,
              "approval_hash_ok": recomputed_hash == record.get("approval_hash"),
              "history_count": history_count, "history_chain_ok": chain_ok,
              "valid": (not changed and chain_ok
                        and recomputed_hash == record.get("approval_hash"))}
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return
    console.print(Panel.fit(
        f"[bold]{record.get('action', '?')}[/bold] by {record.get('approver', '?')}\n"
        f"at {record.get('at', '?')}\n"
        f"reason: {record.get('reason') or '无'}",
        title="SignOffAI — 审批记录"))
    if result["valid"]:
        console.print(f"[green]✓ 审批哈希与证据文件一致（历史 {history_count} 条）[/green]")
    else:
        if not chain_ok:
            console.print("[red]✗ 审批追加链断开（prev_hash 不连续）[/red]")
        if not result["approval_hash_ok"]:
            console.print("[red]✗ 审批记录自身哈希不匹配（被改过）[/red]")
        for ch in changed:
            state = "缺失" if ch["missing"] else "已变化"
            console.print(f"[red]✗ 证据{state}: {ch['name']} ({ch['path']})[/red]")


# 签核证据包的三条命令（verify / replay / compare）定义在**既有的**
# `evidence` 组下（文件后半段，人工变更链那一组）。这里不能再定义同名组 ——
# 后定义的组会覆盖先定义的，命令会静默消失（实测：`evidence verify` 报
# "No such command"）。


@cli.command("resume")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--decision", default="approve",
              type=click.Choice(["approve", "reject", "skip"]),
              help="审批答案（喂回挂起的 interrupt）")
@click.option("--output-base", default="output",
              help="run 目录所在基准（默认 output）")
def resume(run_id, decision, output_base):
    """恢复一次被审批挂起的运行（检查点模式；也可答 approve/reject/skip）

    与 `approve` / `reject` 的差别只有一点：那两个**顺带记一条审计记录**，
    这个纯恢复（例如答案要记成 `skip`，或只是想把图推下去）。
    """
    repo = _repo(output_base)
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    run_dir = repo._resolve(rid)
    if run_dir is None:
        console.print(f"[yellow]找不到 {rid[:32]} 的目录[/yellow]")
        return
    if not _checkpoint_db(Path(run_dir)).exists():
        console.print(f"[red]{rid[:32]} 没有检查点 —— 这次运行没有可恢复的挂起[/red]")
        console.print("[dim]检查点要 `verify --checkpoint`（默认开）才会落[/dim]")
        return
    console.print(f"[dim]以 {decision} 恢复 {rid[:32]}…[/dim]")
    try:
        _report_resume(_resume_closed_loop(Path(run_dir), decision), rid)
    except Exception as exc:                          # noqa: BLE001
        console.print(f"[red]恢复失败：{exc}[/red]")


@cli.command("patch")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--stage", default="", help="阶段名")
@click.option("--file", "file_path", default="", help="补丁文件路径")
def patch(run_id, stage, file_path):
    """记录人工补丁到 run（AI 修不好时的兜底，审计追踪）"""
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    run_dir = Path(repo._resolve(rid))
    patch_dir = run_dir / "patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    record = {"stage": stage, "file": file_path,
              "at": datetime.now().isoformat(), "by": os.environ.get("USER", "engineer")}
    (patch_dir / f"patch_{int(time.time())}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]补丁已记录到 {rid[:32]}/patches/（stage={stage or 'any'}）[/green]")


# ── 归档与清理类 ──

@cli.command("archive")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--output", "output_zip", default="evidence.zip", help="输出 zip 路径")
def archive(run_id, output_zip):
    """打包 run 的签核证据（manifest + report + 覆盖率 + **覆盖率库/波形** + 证据链）"""
    import zipfile
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    run_dir = Path(repo._resolve(rid))
    evidence_files = ["docs/manifest.json", "docs/evidence_chain.json",
                      "report.json", "sim/coverage/coverage_result.json",
                      # **结论的物证**：没有它们，包里的"覆盖率 93.5%"与波形
                      # 就无从核对 —— 而这两样恰恰是回归会反复重写的。上面的
                      # `coverage_result.json` 记了它们的路径与 sha256
                      #（`collect_real_coverage._artifact_manifest`），
                      # 但记哈希的文件本身不进来，等于只有指纹没有实物。
                      "sim/coverage/merged.ucdb",
                      "sim/coverage/wave_seed_default.vcd",
                      # 分级回归走到了哪一级、哪些级等人放行 —— 签核要看这个
                      "regression_stages.json"]
    # 波形文件名带种子（`wave_<seed_tag>.vcd`），清单里那一个名字只覆盖默认那条。
    # 扫一遍把其余种子的一起收 —— 不然"归档了波形"是句半真的话。
    for f in sorted((run_dir / "sim" / "coverage").glob("wave_*.vcd")):
        rel = str(f.relative_to(run_dir)).replace("\\", "/")
        if rel not in evidence_files:
            evidence_files.append(rel)

    missing = []
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in evidence_files:
            f = run_dir / rel
            if f.exists():
                zf.write(f, arcname=f"{rid[:20]}/{rel}")
            else:
                missing.append(rel)
    # **缺了什么要说**：静默跳过会让"包里没有波形"与"这次本来就没跑波形"
    # 长得一模一样 —— 前者是归档漏了（要修），后者是事实（要接受）。
    if missing:
        console.print(f"[dim]以下证据不在这次 run 里（未打包）：{'、'.join(missing)}[/dim]")
    console.print(f"[green]证据包已打包: {output_zip}[/green]")


@cli.command("clean")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
@click.option("--keep-logs", is_flag=True, help="保留日志")
def clean(run_id, keep_logs):
    """清理 run 的中间文件（build/work、uvm_regress），保留证据/日志"""
    import shutil
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    run_dir = Path(repo._resolve(rid))
    cleaned = []
    for sub in ["build", "uvm_regress"]:
        d = run_dir / sub
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            cleaned.append(sub)
    if not keep_logs:
        # 清理日志，但保留证据
        pass
    console.print(f"[green]已清理 {rid[:32]}: {', '.join(cleaned) or '无中间文件'}[/green]")


@cli.command("cleanup")
@click.option("--older-than", default="30d", help="清理 N 天前（如 30d / 7d）")
def cleanup(older_than):
    """清理 N 天前的 run 目录（磁盘管理）"""
    import shutil
    import re as _re
    m = _re.match(r"(\d+)d", older_than)
    days = int(m.group(1)) if m else 30
    cutoff = time.time() - days * 86400
    repo = _repo()
    cleaned = 0
    for d in repo.output_base.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            cleaned += 1
    console.print(f"[green]已清理 {cleaned} 个 {days} 天前的 run 目录[/green]")


# ── 报告与统计类 ──


def _exclude_registry():
    """Exclude 状态库（项目根 .signoffai/，跨 run 共享）。

    刻意不接受 output_dir：exclude 是治理产物，审计哈希链必须跨 run 连续，
    因此与 run 输出目录隔离——主循环 execution.py 用的也是项目根路径。
    历史上有过 output 相对路径的实现，结果是 CLI 批准的 exclude 主循环读不到。
    """
    from src.layers.l4_memory.exclude_registry import ExcludeRegistry
    return ExcludeRegistry()


# ═══════════════════════════════════════════════════════════════
# 验证工作台（PySide6 桌面窗口）
# ═══════════════════════════════════════════════════════════════

@cli.group("gui")
def gui_group():
    """打开验证工作台（PySide6 桌面窗口，界面由 YAML 清单驱动）"""
    pass


@gui_group.command("run")
@click.argument("manifest", required=False, type=click.Path(exists=True))
@click.option("--module", "-m", default=None,
              help="启动后聚焦到这个模块 id（写在清单里的 id）")
@click.option("--input", "-i", default=None,
              help="覆盖指定模块的业务输入路径")
@click.option("--theme", default=None, help="主题名，留空用清单里的设置")
@click.option("--reset-layout", is_flag=True, help="忽略上次保存的窗口布局")
def gui_run(manifest, module, input, theme, reset_layout):
    """启动工作台。

    \b
    示例:
      vagent gui run                          # 用默认清单 config/workbench.yaml
      vagent gui run my.yaml                  # 用别的清单
      vagent gui run -m debug.sim_log         # 直接聚焦某个模块
    """
    args = [a for a in [manifest] if a]
    if module:
        args += ["--module", module]
    if input:
        args += ["--input", input]
    if theme:
        args += ["--theme", theme]
    if reset_layout:
        args += ["--reset-layout"]

    # PySide6 是可选依赖 —— 缺失时给装法而不是 traceback（约定：stderr + 退出码 2）
    try:
        from src.workbench.app import main as workbench_main
    except ImportError as exc:
        click.echo(
            "GUI 需要 PySide6，当前环境没有装：\n"
            f"  {exc}\n\n"
            "装法：pip install -e .[gui]　　或　　pip install PySide6\n"
            "（纯 CLI 用法 check / analyze / generate 不需要它）",
            err=True)
        sys.exit(2)
    sys.exit(workbench_main(args))


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

# 命令组拆分：**导入即注册**。必须放在所有 helper 定义之后，否则被拆出的
# 模块 `from src.cli.commands import _repo, ...` 会拿到半成品。
from . import (  # noqa: E402,F401
    cmd_config, cmd_contract, cmd_coverage, cmd_debug, cmd_diff,
    cmd_evidence, cmd_humanview, cmd_infra, cmd_memory, cmd_metrics,
    cmd_regression,
    cmd_project, cmd_runs, cmd_services, cmd_session, cmd_signoff, cmd_soc,
    cmd_specs, cmd_tools,
    cmd_verify, cmd_vplan,
)


def main():
    _layer_guard_or_die()
    _tool_registry_or_die()
    cli()


def _tool_registry_or_die() -> None:
    """启动期工具注册表守卫 —— 空映射必须显式声明“就是不用工具”。

    `EXECUTOR_TOOL_MODULES` 的空元组语义是“声明不用 hub 工具”，所以**忘配**
    与**故意不用**长得一模一样。这里把前者变成启动失败，并在 stderr 打一行
    汇总（stdout 留给 `--json` 业务输出）。
    """
    try:
        from src.layers.l2_orchestration.communication.tool_hub import (
            ToolHub, ToolRegistryError)
    except Exception:                                  # noqa: BLE001
        return          # 拿不到注册表就别拦人 —— 这是护栏，不是功能
    try:
        summary = ToolHub.validate_registry()
    except ToolRegistryError as exc:
        print(f"工具注册表配置错误（启动期守卫）：\n{exc}", file=sys.stderr)
        sys.exit(EXIT_USAGE)
    print(ToolHub.format_registry_summary(summary), file=sys.stderr)


def _layer_guard_or_die() -> None:
    """启动期分层守卫 —— 拆模块时**本地立刻炸**，不必等 CI 跑完全量。

    放在 `main()` 里 `cli()` **之前**，而不是 `cli` 的回调体里：命令是分发式的，
    回调体只覆盖"进 REPL"那条路，子命令直接执行时根本不经过它。

    代价是每次冷启动扫一遍 `src/layers`（约 122 文件 / 29k 行，`ast.parse`
    量级，远小于 1 秒）。拿这么久换"依赖方向反了当场知道"，值。
    """
    try:
        from src.layers._bootstrap import ensure_layer_contract
    except Exception:                                  # noqa: BLE001
        return          # 拿不到守卫就别拦人 —— 这是护栏，不是功能
    try:
        ensure_layer_contract()
    except Exception as exc:                           # noqa: BLE001
        console.print(f"[red]分层依赖违规（启动期守卫）：[/red]\n{exc}")
        sys.exit(EXIT_LAYER_VIOLATION)


if __name__ == "__main__":
    main()
