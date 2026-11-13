"""CLI 命令组：运行历史与查询（runs / logs / show / prune / trend / failures / projects / completion）。

从 `src/interfaces/cli/commands.py` 拆出；导入本模块即把命令注册到 `cli`。
共享 helper 仍从 `commands` 导入，别在这里再造一份。
"""
from __future__ import annotations

import json  # noqa: F401
from pathlib import Path  # noqa: F401

import click
from rich.table import Table  # noqa: F401

from src.interfaces.cli.output import common_options, get_output_adapter  # noqa: F401
from src.interfaces.cli.commands import (  # noqa: F401
    cli, console, _repo, _resolve_run, _checkpoint_db,
)

@cli.command(hidden=True)
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def completion(shell):
    """生成 shell 自动补全脚本

    \b
    示例:
      vagent completion bash  > /etc/bash_completion.d/vagent
      vagent completion zsh   > ~/.zsh/completions/_vagent
      vagent completion fish  > ~/.config/fish/completions/vagent.fish
    """
    import os as _os
    prog_name = "vagent"

    if shell == "bash":
        click.echo(f"""
_vagent_completion() {{
    local IFS=$'\\n'
    COMPREPLY=($(env COMP_WORDS="${{COMP_WORDS[*]}}" \\
        COMP_CWORD=$COMP_CWORD \\
        _{prog_name.upper()}_COMPLETE=bash_complete $1))
    return 0
}}
complete -o nosort -F _vagent_completion {prog_name}
""")
    elif shell == "zsh":
        click.echo(f"""
#compdef {prog_name}
_vagent() {{
    local -a completions
    local -a completions_with_descriptions
    local -a response
    response=($({{env COMP_WORDS="${{words[*]}}" COMP_CWORD=$((CURRENT-1)) \\
        _{prog_name.upper()}_COMPLETE=zsh_complete {prog_name}}}))
    for key descr in ${{(kv)response}}; do
        if [[ "$descr" == "_" ]]; then
            completions+=("$key")
        else
            completions_with_descriptions+=("$key":"$descr")
        fi
    done
    if [ -n "$completions_with_descriptions" ]; then
        _describe -V unsorted completions_with_descriptions -U
    fi
    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi
}}
compdef _vagent {prog_name}
""")
    elif shell == "fish":
        click.echo(f"""
function _{prog_name}_completion
    set -l response (env _{prog_name.upper()}_COMPLETE=fish_complete COMP_WORDS=(commandline -cp) COMP_CWORD=(commandline -t) {prog_name})
    for completion in $response
        echo $completion
    end
end
complete -f -c {prog_name} -a "(_{prog_name}_completion)"
""")


@cli.command("runs")
@click.option("--limit", "-n", default=20, help="显示数量")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def runs(limit, json_output):
    """列出所有 run（从 output 目录扫描：覆盖率/收敛/签核状态）"""
    out = get_output_adapter(json_output)
    repo = _repo()
    run_list = repo.list_runs(limit)
    if not run_list:
        out.print_success("无 run。先跑 'vagent verify' 或闭环。")
        return
    if json_output:
        click.echo(json.dumps(run_list, indent=2, ensure_ascii=False, default=str))
    else:
        rows = [[r["run_id"][:36], f"{r['final_coverage']}%",
                 "✓" if r["converged"] else "✗",
                 r.get("verdict", ""), r.get("signoff_status", "")] for r in run_list]
        out.print_table(["Run", "Coverage", "Converged", "Verdict", "Signoff"],
                        rows, title="Runs（磁盘扫描）")


@cli.command("prune")
@click.option("--keep-last", default=20, show_default=True, type=int,
              help="保留最近 N 个 run")
@click.option("--apply", is_flag=True,
              help="真的删除；默认 dry-run（只列出会删什么）")
@click.option("--include-approved", is_flag=True,
              help="连有签核证据/审批记录的 run 也删（默认保护）")
@click.option("--output-base", default="output", help="run 目录所在基准")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def prune_runs(keep_last, apply, include_approved, output_base, json_output):
    """清理旧 run 目录（保留最近 N 个；默认保护已签核/已审批的 run）"""
    import shutil

    out = get_output_adapter(json_output)
    repo = _repo(output_base)
    dirs = [p for p in repo.run_dirs() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    keep = set(dirs[:max(0, keep_last)])
    candidates = [p for p in dirs if p not in keep]

    deleted, protected = [], []
    for p in candidates:
        has_evidence = ((p / "signoff_evidence" / "manifest.json").is_file()
                        or (p / "approval.json").is_file()
                        or (p / "signoff_evidence.json").is_file())
        if has_evidence and not include_approved:
            protected.append({"run": p.name, "reason": "signed/approved"})
            continue
        if apply:
            try:
                shutil.rmtree(p)
                deleted.append({"run": p.name, "path": str(p)})
            except OSError as e:
                protected.append({"run": p.name, "reason": f"delete failed: {e}"})
        else:
            deleted.append({"run": p.name, "path": str(p), "dry_run": True})

    payload = {"keep_last": keep_last, "kept": [p.name for p in dirs if p in keep],
               "would_delete": deleted, "protected": protected,
               "applied": bool(apply)}
    if json_output:
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        mode = "已删除" if apply else "将删除（dry-run）"
        out.print_table(["Run", "路径"],
                        [[d["run"], d.get("path", "")] for d in deleted],
                        title=f"{mode} {len(deleted)} 个 run")
        if protected:
            console.print(f"[yellow]保护 {len(protected)} 个（签核/审批或删除失败）[/yellow]")
            for p in protected[:10]:
                console.print(f"  [dim]{p['run']}: {p['reason']}[/dim]")
        if not apply:
            console.print("[dim]加 --apply 才会真的删除[/dim]")


@cli.command("gc")
@click.option("--runs-root", default=".", show_default=True,
              help="run 目录所在根（默认当前目录）")
@click.option("--keep-last", default=5, show_default=True, type=int,
              help="最近 N 个 run 不回收")
@click.option("--keep-days", default=30.0, show_default=True, type=float,
              help="N 天内的 run 不回收")
@click.option("--apply", is_flag=True,
              help="真的删除；默认 dry-run（只列计划）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def gc_artifacts(runs_root, keep_last, keep_days, apply, json_output):
    """回收旧 run 的大件（波形/覆盖库），**保留证据链**。

    \b
    与 `prune` 的分工：prune 删整个 run；gc 只删可重建的
    `regression_run/**/waves|cov` 与 `sim/**/*.ucdb|vdb`，
    `coverage/ status/ docs/ contract/ evidence/` 永不删除。
    """
    from src.core.runtime.gc import apply_gc, plan_gc

    plan = plan_gc(runs_root, keep_last=keep_last, keep_days=keep_days)
    result = apply_gc(plan, confirm=True) if apply else plan
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
        return
    mb = (result.get("candidate_bytes") or result.get("freed_bytes") or 0) / 1048576
    verb = "已回收" if apply else "将回收"
    console.print(f"[bold]{verb}[/bold] {result.get('candidate_files', 0)} 个文件 / "
                  f"{mb:.1f} MB（扫描 {result.get('runs', 0)} 个 run，"
                  f"保留 {len(result.get('kept_runs') or [])} 个）")
    for item in (result.get("deleted") or result.get("candidates") or [])[:10]:
        console.print(f"  [dim]{item['path']} ({item['bytes'] / 1048576:.1f} MB)[/dim]")
    if not apply:
        console.print("[dim]加 --apply 才会真的删除[/dim]")


@cli.command("logs")
@click.option("--run", "run_id", default="", help="run ID 或前缀（默认最新）")
@click.option("--stage", default="", help="阶段过滤（compile/sim/coverage）")
@click.option("--tail", "-t", default=0, help="只显示每个日志尾部 N 行")
def logs(run_id, stage, tail):
    """查看某 run 的日志文件"""
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    log_files = repo.logs(rid, stage)
    if not log_files:
        console.print("[yellow]无日志文件[/yellow]")
        return
    for lf in log_files:
        console.print(f"[cyan]{lf['name']}[/cyan] ({lf['size_kb']} KB)")
        if tail > 0:
            try:
                lines = Path(lf["path"]).read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines[-tail:]:
                    console.print(f"  [dim]{line}[/dim]")
            except Exception:
                pass


@cli.command("show")
@click.option("--run", "run_id", default="", help="run ID 或前缀（默认最新）")
@click.option("--format", "fmt", default="json", type=click.Choice(["json"]), help="输出格式")
def show(run_id, fmt):
    """导出某 run 的完整结构数据（阶段/覆盖率/证据）"""
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    run = repo.get_run(rid)
    click.echo(json.dumps(run, indent=2, ensure_ascii=False, default=str))


@cli.command("trend")
@click.option("--limit", "-n", default=30, help="最近 N 次")
@click.option("--metric", default="coverage", type=click.Choice(["coverage"]))
def trend(limit, metric):
    """覆盖率趋势（最近 N 次 run）"""
    repo = _repo()
    data = repo.trend(metric, limit)
    if not data:
        console.print("[yellow]无数据[/yellow]")
        return
    for d in data:
        bar = "█" * int(d["coverage"] / 5)
        console.print(f"{d['run_id'][:28]:30} {d['coverage']:5.1f}% {bar}")


@cli.command("failures")
@click.option("--run", "run_id", default="", help="run ID 或前缀")
def failures(run_id):
    """列出某 run 的失败阶段"""
    repo = _repo()
    rid = _resolve_run(repo, run_id)
    if not rid:
        console.print("[yellow]无 run[/yellow]")
        return
    fails = repo.failures(rid)
    if not fails:
        console.print("[green]无失败阶段[/green]")
        return
    for f in fails:
        console.print(f"[red]✗ {f.get('name', '?')}[/red] — {f.get('status', '')}")


@cli.command("projects")
def projects():
    """列出 output 目录里的项目（按前缀分组）"""
    repo = _repo()
    prefixes = {}
    for d in sorted(repo.output_base.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            prefix = d.name.split("_")[0] if "_" in d.name else d.name
            prefixes.setdefault(prefix, []).append(d.name)
    for prefix, dirs in sorted(prefixes.items()):
        console.print(f"[cyan]{prefix}[/cyan]: {len(dirs)} 个 run")
