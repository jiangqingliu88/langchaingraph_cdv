"""SignOffAI CLI 命令组：回归（regression）

从 `src/cli/commands.py` 拆出；导入本模块即把命令注册到 `cli`。
命令实现保持不变，便于逐步搬迁与回滚。
"""
from __future__ import annotations

import asyncio  # noqa: F401
import json
import sys  # noqa: F401
from datetime import datetime  # noqa: F401
from pathlib import Path

import click  # noqa: F401
from rich.panel import Panel  # noqa: F401
from rich.table import Table  # noqa: F401

from src.cli.output import common_options, get_output_adapter  # noqa: F401
from src.cli.commands import (  # noqa: F401
    cli, console,
    EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_WAITING, EXIT_STRICT,
    _repo, _resolve_run, _init_service, _find_run_id,
    _strict_semantic_gate,
    _extract_requirements_from_md, _get_git_info,
    _exclude_registry, _output_junit, _output_gitlab_ci,
    _checkpoint_db, _resume_closed_loop, _report_resume,
    _approver_name, _sha256_path, _write_approval_record, _decide,
)

@cli.group()
def regression():
    """回归管理"""
    pass


# ── 分级回归：看各级状态 / 人工放行 ─────────────────────────────
#
# 分级回归（loopback → p0 → p1 → p2 → p3）在 loopback 全过之后有**人工节点**：
# 那级证的是"TB 自身自洽"（driver 发出的 == slave monitor 看到的），要不要接着
# 烧 P0 的机时由人拍。下面两个子命令就是那个人拍板的入口。

def _staged_doc(output_dir: str) -> dict:
    """读 run 目录下的分级结果 + 放行记录（都不存在就返回空）。"""
    root = Path(output_dir)
    doc: dict = {"stages": [], "approvals": []}
    for key, fname in (("stages", "regression_stages.json"),
                       ("approvals", "regression_approvals.json")):
        p = root / fname
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:                       # noqa: BLE001 坏文件当没有
            console.print(f"[yellow]⚠ 解析 {fname} 失败：{exc}[/yellow]")
            continue
        # 放行记录的数组键也叫 `approvals`，分级结果的叫 `stages` —— 用同一个 key 取
        doc[key] = data.get(key) or []
        if key == "stages":
            for k in ("status", "blocked_at", "blocked_reason", "awaiting"):
                if k in data:
                    doc[k] = data[k]
    return doc


@regression.command("stages")
@click.option("--output", "-o", "output_dir", type=click.Path(), help="输出目录（run 目录）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def regression_stages(output_dir, json_output):
    """看分级回归跑到哪一级、卡在哪、人工节点放行了没有。"""
    if not output_dir:
        console.print("[red]需要 --output 指定 run 目录，如 -o output_xxx[/red]")
        return
    doc = _staged_doc(output_dir)
    if json_output:
        click.echo(json.dumps(doc, ensure_ascii=False, indent=2))
        return
    if not doc["stages"]:
        console.print("[yellow]没找到分级结果（"
                      f"{Path(output_dir) / 'regression_stages.json'}）[/yellow]")
        return
    style = {"PASS": "[green]PASS[/green]", "FAIL": "[red]FAIL[/red]",
             "EMPTY": "[yellow]EMPTY[/yellow]",
             "WAITING_APPROVAL": "[cyan]待放行[/cyan]"}
    done = {a.get("after") for a in doc["approvals"]}
    console.print(f"\n[bold]分级回归[/bold]  "
                  f"status={style.get(doc.get('status', ''), doc.get('status'))}")
    for s in doc["stages"]:
        mark = "[cyan]✔已放行[/cyan]" if s["name"] in done else ""
        console.print(f"  {s['name']:<9} {style.get(s['status'], s['status']):<32}"
                      f" passed={s.get('passed', 0)} failed={s.get('failed', 0)}"
                      f" unknown={s.get('unknown', 0)}  {mark}")
    if doc.get("status") == "WAITING_APPROVAL" and doc.get("awaiting"):
        aw = doc["awaiting"]
        if aw["after"] in done:
            console.print(f"\n[green]{aw['after']} 已放行[/green] —— 重跑分级回归即从 "
                          f"{aw['next']} 继续（已过的级会重跑一遍）")
        else:
            console.print(f"\n[cyan]停在人工节点：{aw['after']} 已全过，"
                          f"进 {aw['next']} 前需人工放行[/cyan]")
            console.print(f"  {aw.get('hint', '')}")


@regression.command("approve")
@click.option("--output", "-o", "output_dir", type=click.Path(), help="输出目录（run 目录）")
@click.option("--after", "after", default="loopback", show_default=True,
              help="放行哪一级")
@click.option("--by", "approver", default="", help="审批人（必填，写进审计记录）")
@click.option("--note", default="", help="审批意见")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def regression_approve(output_dir, after, approver, note, json_output):
    """人工放行某一级，之后重跑分级回归即可进下一级。

    放行记录**绑定证据**（那一级的 total/passed/failed）—— 结果变了要重新批，
    批的永远是"你当时看到的那一份结果"。
    """
    if not output_dir or not approver:
        console.print("[red]需要 --output 指定 run 目录、--by 指定审批人[/red]")
        return
    from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
    infra = InfrastructureManager(output_dir)
    try:
        entry = infra.approve_stage(after, approver=approver, note=note)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return
    if json_output:
        click.echo(json.dumps(entry, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]✔ 已放行 {after}[/green] → 下一步可进 "
                  f"{entry.get('next') or '（无）'}")
    console.print(f"  审批人 {entry['approver']} @ {entry['at']}"
                  + (f"　意见：{entry['note']}" if entry["note"] else ""))
    console.print(f"  记录：{Path(output_dir) / 'regression_approvals.json'}")


@regression.command("run")
@click.option("--tests", "-t", type=click.Path(exists=True), help="测试 YAML 配置")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def regression_run(tests, json_output):
    """运行回归测试

    \b
    示例:
      vagent regression run --tests regression.yaml
    """
    out = get_output_adapter(json_output)
    if tests:
        config = Path(tests).read_text(encoding="utf-8")
        out.print_result({"config_file": tests, "size": len(config)},
                         title="Regression Config Loaded")
        console.print("[yellow]Regression execution requires active verification environment.[/yellow]")
        console.print("[dim]Use 'vagent verify <spec> --step regress' for full regression.[/dim]")
    else:
        out.print_error("Use --tests <yaml_file>")


@regression.command("report")
@click.option("--run", "-r", "run_id", help="Run ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def regression_report(run_id, json_output):
    """回归报告

    \b
    示例:
      vagent regression report --run <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        return

    try:
        from src.layers.l4_memory.persistence.repository import get_regression_history
        history = asyncio.run(get_regression_history())
        if history:
            latest = history[0]
            out.print_result(latest, title=f"Regression Report — {rid}")
        else:
            out.print_success("No regression history in DB")
    except Exception as e:
        out.print_error(str(e))


@regression.command("trend")
@click.option("--days", "-d", default=30, help="天数")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def regression_trend(days, json_output):
    """回归趋势

    \b
    示例:
      vagent regression trend --days 30
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l4_memory.persistence.repository import get_regression_trend
        trend = asyncio.run(get_regression_trend(days=days))
        if trend:
            out.print_result({"days": days, "data_points": len(trend), "trend": trend},
                             title=f"Regression Trend ({days}d)")
        else:
            out.print_success("No data for trend analysis")
    except Exception as e:
        out.print_error(str(e))


@regression.command("compare")
@click.option("--run-a", required=True, help="Run A ID")
@click.option("--run-b", required=True, help="Run B ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def regression_compare(run_a, run_b, json_output):
    """两次回归对比

    \b
    示例:
      vagent regression compare --run-a <id1> --run-b <id2>
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        ma = builder.build(session_id=run_a.replace("run_", ""))
        mb = builder.build(session_id=run_b.replace("run_", ""))

        reg_a = ma.metadata.get("regression", {})
        reg_b = mb.metadata.get("regression", {})

        out.print_result({
            "run_a": {"id": run_a, "passed": reg_a.get("passed", "?"), "total": reg_a.get("total", "?")},
            "run_b": {"id": run_b, "passed": reg_b.get("passed", "?"), "total": reg_b.get("total", "?")},
        }, title="Regression Comparison")

    except Exception as e:
        out.print_error(str(e))


@regression.command("reference-finder")
@click.option("--repo", "-r", default=".", help="git 仓库路径（默认当前目录）")
@click.option("--good", required=True, help="已知通过的提交（起点）")
@click.option("--bad", default="HEAD", help="已知失败的提交（终点，默认 HEAD）")
@click.option("--config", "-c", "reg_yaml", required=True, type=click.Path(exists=True),
              help="回归配置 yaml（版本间保持同一份）")
@click.option("--test", "-t", "test_pattern", required=True, help="要复现的用例名/正则")
@click.option("--work-root", default=None, help="工作目录（worktree 与结论落这里）")
@click.option("--mode", type=click.Choice(["mock", "local"]), default="mock",
              help="执行模式（mock 只走流程不真跑 EDA）")
@click.option("--paths", default=None, help="逗号分隔，只考虑这些路径下的提交")
@click.option("--keep-worktrees", is_flag=True, help="保留各版本的 worktree（排查用，默认删）")
@click.option("--no-cache", is_flag=True, help="忽略结论缓存，强制重跑所有版本")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def regression_reference_finder(repo, good, bad, reg_yaml, test_pattern, work_root,
                                mode, paths, keep_worktrees, no_cache, json_output):
    """溯源定位：哪个提交引入了这个失败

    在 good..bad 区间内二分，每个版本用独立 worktree 隔离后跑指定用例，
    收敛到第一个失败的提交。结论连同环境快照落盘，可审计。

    \b
    示例:
      vagent regression reference-finder \\
        --good v1.0 --bad HEAD --config regression.yaml --test smoke_basic
    """
    out = get_output_adapter(json_output)
    work_root = work_root or str(Path(repo) / "reference_finder_work")
    path_list = [p.strip() for p in paths.split(",") if p.strip()] if paths else None

    console.print(f"[dim]逐版本编译+仿真，请耐心；已跑过的版本会命中缓存。[/dim]")
    try:
        from src.layers.l1_infrastructure.reference_finder import ReferenceFinder
        finder = ReferenceFinder(
            repo_path=repo, work_root=work_root, reg_yaml=reg_yaml,
            test_pattern=test_pattern, mode=mode,
            keep_worktrees=keep_worktrees, use_cache=not no_cache, verbose=True)
        report = finder.find_first_bad(good, bad, paths=path_list)
    except Exception as e:
        out.print_error(str(e))
        return

    if json_output:
        out.print_result(report, title="Reference Finder")
        return

    if report.get("culprit"):
        console.print(f"\n[bold]引入提交[/bold]: [cyan]{report.get('culprit_short')}[/cyan] "
                      f"{report.get('subject', '')}")
        console.print(f"  最后一个好版本: {report.get('last_good_short')}")
        console.print(f"  置信度: [bold]{report.get('confidence')}[/bold]")
        if report.get("changed_files"):
            console.print("  改动文件: " + ", ".join(report["changed_files"][:8]))
    else:
        console.print(f"\n[yellow]未能定位[/yellow]: {report.get('reason', '')}")

    for c in report.get("caveats", []) or []:
        console.print(f"  [yellow]![/yellow] {c}")
    for x in report.get("inconclusive_revisions", []) or []:
        console.print(f"  [yellow]?[/yellow] {x['short']} inconclusive: {x['detail']}")

    console.print(f"\n[dim]结论: {work_root}/reference_finder_summary.md[/dim]")
    console.print(f"[dim]实测 {len(report.get('results', []))} 个版本，"
                  f"耗时 {report.get('elapsed_s')}s[/dim]")


# ═══════════════════════════════════════════════════════════════
# vagent coverage — 覆盖率管理 (P3)
# ═══════════════════════════════════════════════════════════════

