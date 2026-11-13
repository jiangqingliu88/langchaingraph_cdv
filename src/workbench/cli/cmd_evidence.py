"""SignOffAI CLI 命令组：证据链（evidence）

从 `src/workbench/cli/commands.py` 拆出；导入本模块即把命令注册到 `cli`。
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

from src.workbench.cli.output import common_options, get_output_adapter  # noqa: F401
from src.workbench.cli.commands import (  # noqa: F401
    cli, console,
    EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_WAITING, EXIT_STRICT,
    _repo, _resolve_run, _init_service, _find_run_id,
    _strict_semantic_gate,
    _extract_requirements_from_md, _get_git_info,
    _exclude_registry, _output_junit, _output_gitlab_ci,
    _checkpoint_db, _resume_closed_loop, _report_resume,
    _approver_name, _sha256_path, _write_approval_record, _decide,
)

@cli.group("evidence")
def evidence_group():
    """证据链：人工变更记录 + 签核证据包校验/回放

    \b
    人工变更（项目级，跨运行累积）:
      vagent evidence record rtl/dut.sv -m "修正握手时序"
      vagent evidence log
      vagent evidence check

    \b
    签核证据包 v2（某一次 run 的 signoff_evidence/ 目录）:
      vagent evidence verify  <run>/signoff_evidence
      vagent evidence replay  <run>/signoff_evidence
      vagent evidence compare <pkg-a> <pkg-b>
    """
    pass


@evidence_group.command("verify")
@click.argument("package", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON")
def evidence_verify(package, json_output):
    """逐文件 sha256 + package_hash 校验"""
    from src.orchestration_plane.l2.evidence.signoff_package import verify_package

    result = verify_package(package)
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["ok"]:
        console.print(f"[green]✓ 证据包完整[/green]  verdict={result.get('verdict')}")
    else:
        console.print("[red]✗ 证据包校验失败[/red]")
        for issue in result["issues"]:
            console.print(f"  [red]{issue}[/red]")
    if not result["ok"]:
        raise SystemExit(1)


@evidence_group.command("replay")
@click.argument("package", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON")
def evidence_replay(package, json_output):
    """Tier A 离线回放：不跑 EDA，重算三态判定"""
    from src.orchestration_plane.l2.evidence.signoff_package import replay_tier_a

    result = replay_tier_a(package)
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        state = "[green]✓[/green]" if result["ok"] else "[red]✗[/red]"
        console.print(f"{state} 记录 {result['recorded_verdict']} / "
                      f"重算 {result['recomputed_verdict']}")
        for chk in result.get("checks") or []:
            icon = "[green]✓[/green]" if chk.get("ok") else "[red]✗[/red]"
            console.print(f"  {icon} {chk.get('check')}: "
                          f"{chk.get('recorded')} → {chk.get('recomputed')}")
    if not result["ok"]:
        raise SystemExit(1)


@evidence_group.command("compare")
@click.argument("package_a", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("package_b", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="输出机器可读 JSON")
def evidence_compare(package_a, package_b, json_output):
    """双环境判定一致性（同一份证据在两种环境各判一次）"""
    from src.orchestration_plane.l2.evidence.signoff_package import compare_packages

    result = compare_packages(package_a, package_b)
    if json_output:
        click.echo(json.dumps(result, indent=2, ensure_ascii=False))
    elif result["consistent"]:
        console.print(f"[green]✓ 判定一致[/green] verdict={result['verdict_a']}")
    else:
        console.print("[red]✗ 判定不一致[/red]")
        for diff in result["diffs"]:
            console.print(f"  [red]{diff['field']}: {diff['a']} vs {diff['b']}[/red]")
    if not result["consistent"]:
        raise SystemExit(1)


@evidence_group.command("record")
@click.argument("file_path", metavar="FILE")
@click.option("--message", "-m", "reason", default="",
              help="为什么改（会记进证据链；留空记为「未填理由」，不编理由）")
@click.option("--author", default="", help="署名（默认 PLATFORM_USER_NAME 或系统登录名）")
@click.option("--run-id", default="", help="同时往这次运行的日志写一条锚点")
@click.option("--root", "repo_root", default=".", help="仓库根（默认当前目录）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def evidence_record(file_path, reason, author, run_id, repo_root, json_output):
    """记录一次人工编辑（改完文件跑一下）

    \b
    示例:
      vagent evidence record config/ide/manual_nodes.yaml -m "超时 600 → 900"
    """
    out = get_output_adapter(json_output)
    from src.orchestration_plane.l2.evidence.human_edit import record_human_edit

    info = record_human_edit(file_path, reason, author=author, run_id=run_id,
                             repo_root=repo_root)
    if not info.get("recorded"):
        out.print_result({"recorded": False, "error": info.get("error", "记账失败")},
                         title="Evidence")
        sys.exit(1)

    if json_output:
        out.print_result(info, title="Evidence")
        return
    console.print(f"已记账 [bold]#{info['seq']}[/bold]　{info['file']}")
    console.print(f"  署名：{info['author']}　　理由：{info['reason']}")
    console.print(f"  内容哈希：{(info.get('content_hash') or '')[:16]}…")
    console.print(f"  链：{info['chain']}（共 {info['total_changes']} 条）")
    if run_id and not info.get("journal"):
        console.print(f"  [yellow]注意：没写进运行 {run_id} 的日志"
                      f"（找不到那次运行）[/yellow]")


@evidence_group.command("log")
@click.option("--limit", "-n", default=20, show_default=True, help="最多显示几条")
@click.option("--root", "repo_root", default=".", help="仓库根（默认当前目录）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def evidence_log(limit, repo_root, json_output):
    """看人工变更链 + 完整性自校验

    \b
    示例:
      vagent evidence log -n 5
    """
    out = get_output_adapter(json_output)
    from src.orchestration_plane.l2.evidence.human_edit import read_human_edits

    chain = read_human_edits(repo_root)
    if not chain["exists"]:
        out.print_result({"exists": False, "total_changes": 0, "path": chain["path"]},
                         title="Evidence")
        if not json_output:
            console.print(f"还没有人工变更记录。（会写到 {chain['path']}）")
        return

    records = list(reversed(chain["records"]))[:max(1, int(limit))]
    rows = [[str(r.get("seq", "")), str(r.get("timestamp", ""))[:19],
             str(r.get("file_path", "")), str(r.get("agent", "")),
             str(r.get("reason", ""))[:48]] for r in records]
    out.print_table(["#", "时间", "文件", "谁", "理由"], rows,
                    title=f"人工变更（共 {chain['total_changes']} 条）")
    if not json_output:
        state = "[green]完整[/green]" if chain["chain_valid"] else "[red]已断[/red]"
        console.print(f"链完整性：{state}　{chain['path']}")
        for issue in chain.get("issues", []):
            console.print(f"  [red]{issue.get('type')}[/red] {issue}")


@evidence_group.command("check")
@click.option("--root", "repo_root", default=".", help="仓库根（默认当前目录）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def evidence_check(repo_root, json_output):
    """对账：工作区改过、证据链里没有的文件

    \b
    链的价值不在「记了的有痕迹」，而在「没记的能被发现」—— 否则读链的人分不清
    「这段时间没人改」和「有人改了但没记账」。
    有未记账的改动时退出码为 1，可以直接拿去卡 CI。
    """
    out = get_output_adapter(json_output)
    from src.orchestration_plane.l2.evidence.human_edit import reconcile

    report = reconcile(repo_root)
    if json_output:
        out.print_result(report, title="Evidence check")
    elif not report["checked"]:
        console.print(f"[yellow]跳过：{report['reason']}[/yellow]")
    else:
        console.print(f"改动 {report['total_changed']} 个文件　"
                      f"已记账 {len(report['recorded'])}　"
                      f"未记账 {len(report['unrecorded'])}")
        for path in report["unrecorded"]:
            console.print(f"  [red]✗[/red] {path}")
        if report["ok"]:
            console.print("[green]✓ 改动都有痕迹。[/green]")
        else:
            console.print("[yellow]上面这些改过但没记账 —— 补上：[/yellow]")
            console.print("  vagent evidence record <文件> -m \"为什么改\"")
    # 不在 git 仓库里谈不上"对账"，不算失败；在仓库里且链断了 = 失败
    if report["checked"] and not report["ok"]:
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# 血缘：RTL 版本 / run 基准 / bug↔版本
# ═══════════════════════════════════════════════════════════════
#
# 四件事一条链：**RTL 内容哈希 → 版本号 → run 挂版本 → 首次 run 当基准 →
# 用例与 bug 各自挂在版本上**。都是 `database/lineage.db` 里的可查实体。


@evidence_group.command("audit")
@click.argument("package", type=click.Path(exists=True, file_okay=False,
                                          path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="机器可读 JSON")
def evidence_audit(package, json_output):
    """Evidence v2：完整性 / 有效性 / 可信度三态审计。"""
    from src.engine_plane.audit.evidence_v2 import evaluate_package

    result = evaluate_package(package)
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['status']}: {result['reason']}")
        print(f"  completeness={result['completeness']['ok']} "
              f"validity={result['validity']['ok']} "
              f"trust={result['trust']['ok']}")
    raise SystemExit(0 if result["status"] == "PASS"
                     else 1 if result["status"] == "FAIL" else 2)


@evidence_group.command("stale")
@click.argument("provenance", type=click.Path(exists=True, dir_okay=False,
                                              path_type=Path))
@click.argument("current", type=click.Path(exists=True, dir_okay=False,
                                           path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="机器可读 JSON")
def evidence_stale(provenance, current, json_output):
    """provenance 输入 hash 与当前输入不一致 → 证据失效清单。"""
    from src.engine_plane.audit.evidence_v2 import stale_inputs

    doc = json.loads(Path(current).read_text(encoding="utf-8", errors="replace"))
    rows = stale_inputs(provenance, doc if isinstance(doc, dict) else {})
    if json_output:
        print(json.dumps({"stale": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"stale inputs: {len(rows)}")
        for row in rows:
            print(f"  {row['path']}  {row['recorded'][:12]} -> {row['current'][:12]}")
    raise SystemExit(1 if rows else 0)

