"""SignOffAI CLI 命令组：覆盖率（coverage）

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
def coverage():
    """覆盖率管理"""
    pass


@coverage.command("report")
@click.option("--run", "-r", "run_id", help="Run ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_report(run_id, json_output):
    """覆盖率报告

    \b
    示例:
      vagent coverage report --run <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        return

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))
        cov = manifest.metadata.get("coverage", {})

        if isinstance(cov, dict) and cov:
            out.print_result({
                "run_id": rid,
                "line_coverage": f"{cov.get('line_pct', 0):.1f}%",
                "branch_coverage": f"{cov.get('branch_pct', 0):.1f}%",
                "toggle_coverage": f"{cov.get('toggle_pct', 0):.1f}%",
                "overall": f"{cov.get('coverage_pct', 0):.1f}%",
            }, title=f"Coverage Report — {rid}")
        else:
            out.print_error("Coverage data not available")
    except Exception as e:
        out.print_error(str(e))


@coverage.command("gaps")
@click.option("--run", "-r", "run_id", help="Run ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_gaps(run_id, json_output):
    """覆盖率缺口

    \b
    示例:
      vagent coverage gaps --run <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        return

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))
        cov = manifest.metadata.get("coverage", {})

        if isinstance(cov, dict):
            gaps = cov.get("gaps", [])
            suggestions = cov.get("suggestions", [])
            out.print_result({
                "run_id": rid,
                "gaps": gaps[:20],
                "suggestions": suggestions[:10],
                "gap_count": len(gaps),
            }, title=f"Coverage Gaps — {rid}")
        else:
            out.print_error("Coverage data not available")
    except Exception as e:
        out.print_error(str(e))


@coverage.command("exclude")
@click.option("--coverage", "-c", type=float, default=None, help="当前覆盖率（%，配合 --total 计算有效覆盖率）")
@click.option("--total", "-t", type=int, default=None, help="总覆盖点数")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_exclude(coverage, total, json_output):
    """覆盖率里的 Exclude 视图：已放弃点 + 待审批 + 有效覆盖率

    \b
    示例:
      vagent coverage exclude                              # 已放弃/待审批摘要
      vagent coverage exclude -c 95 -t 100                 # 附有效覆盖率
    """
    out = get_output_adapter(json_output)
    reg = _exclude_registry()
    try:
        approved = reg.get_approved_excludes()
        pending = reg.list_pending()
        stats = reg.stats()
        result = {
            "stats": stats,
            "approved_points": sorted(reg.get_excluded_points()),
            "pending": [{"exclude_id": p["exclude_id"], "coverage_point": p["coverage_point"],
                         "type": p["exclude_type"], "reason": p["reason"]} for p in pending],
        }
        if coverage is not None and total is not None:
            result["effective"] = {
                "raw_coverage": coverage, "total_points": total,
                "excluded": stats["excluded_points"],
                "effective_total": max(total - stats["excluded_points"], 1),
                "effective_coverage": reg.effective_coverage(coverage, total),
            }

        if json_output:
            click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            return

        console.print(f"[bold]覆盖率 Exclude 视图[/bold] — "
                      f"已放弃 {stats['excluded_points']} 点 | 待审批 {stats['pending']}")
        if coverage is not None and total is not None:
            eff = result["effective"]
            console.print(f"[cyan]有效覆盖率: {eff['raw_coverage']}% → {eff['effective_coverage']}%"
                          f"（分母 {eff['total_points']} → {eff['effective_total']}）[/cyan]")
        if approved:
            console.print(f"\n[yellow]已批准（生效）:[/yellow]")
            for e in approved:
                console.print(f"   {e['exclude_id']}  {e['coverage_point']}  ({e['exclude_type']})")
        if pending:
            console.print(f"\n[bold red]待审批（阻断签核）:[/bold red]")
            for p in pending:
                console.print(f"   {p['exclude_id']}  {p['coverage_point']}  ({p['exclude_type']}) — "
                              f"vagent exclude approve {p['exclude_id']}")
        if not approved and not pending:
            console.print("[dim]暂无 Exclude。闭环会自动发现结构性死代码并提议；也可手动 'vagent exclude propose'。[/dim]")
    finally:
        reg.close()


@coverage.command("trend")
@click.option("--days", "-d", default=30, help="天数")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_trend(days, json_output):
    """覆盖率趋势

    \b
    示例:
      vagent coverage trend --days 30
    """
    out = get_output_adapter(json_output)
    # Use regression trend as proxy
    try:
        from src.layers.l4_memory.persistence.repository import get_regression_trend
        trend = asyncio.run(get_regression_trend(days=days))
        out.print_result({"days": days, "data_points": len(trend), "trend": trend},
                         title=f"Coverage Trend ({days}d)")
    except Exception as e:
        out.print_error(str(e))


@coverage.command("merge")
@click.option("--runs", required=True, help="逗号分隔的 run IDs")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_merge(runs, json_output):
    """合并多次覆盖率

    \b
    示例:
      vagent coverage merge --runs run_a,run_b,run_c
    """
    out = get_output_adapter(json_output)
    run_list = [r.strip() for r in runs.split(",")]

    # Aggregate coverage data
    aggregated = {"line_pct": 0, "branch_pct": 0, "toggle_pct": 0, "coverage_pct": 0}
    count = 0

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        for rid in run_list:
            manifest = builder.build(session_id=rid.replace("run_", ""))
            cov = manifest.metadata.get("coverage", {})
            if isinstance(cov, dict) and cov:
                for key in aggregated:
                    aggregated[key] += cov.get(key, 0)
                count += 1

        if count > 0:
            for key in aggregated:
                aggregated[key] = round(aggregated[key] / count, 1)

        out.print_result({
            "runs": run_list,
            "run_count": count,
            "merged_coverage": aggregated,
        }, title="Merged Coverage")
    except Exception as e:
        out.print_error(str(e))


def _print_tp_chain(tid, s, cases):
    """打印一条测试点的取证链（人读；机器读走 `--json`）。"""
    if not s:
        console.print(f"[red]{tid}: 没有这条测试点[/red]")
        return
    mark = "[green]SIGNED_OFF[/green]" if s.get("signed_off") else "[red]UNSIGNED[/red]"
    by = f" ({s['signed_off_by']})" if s.get("signed_off_by") else ""
    console.print(f"[bold]{tid}[/bold]  {mark}")
    console.print(f"  owner : {s.get('owner_test') or '-'} @ {s.get('owner_stage') or '-'}")
    console.print(f"  task  : {s.get('owner_case') or '-'}{by}")
    console.print(f"  bins  : {', '.join(s.get('owned_bins') or []) or '-'}")
    rec = cases.get(s.get("owner_case"))
    if rec:
        scb = rec.get("scb") or {}
        a = rec.get("assertions") or {}
        console.print(f"  scb   : total={scb.get('total')} matched={scb.get('matched')} "
                      f"mismatched={scb.get('mismatched')}")
        console.print(f"  assert: {a.get('rules', 0)} rules, {a.get('fired', 0)} fired")
        if s.get("timing_ok") is not None:
            console.print(f"  timing: {'ok' if s['timing_ok'] else 'VIOLATION'}"
                          f"（expect_cycles）")
        wave = rec.get("wave") or rec.get("wave_abs") or "-"
        console.print(f"  wave  : {wave}")
        if rec.get("wave_abs"):
            from src.tools.common.lib.case_meta import visualizer_command
            console.print(f"          [dim]{visualizer_command(rec['wave_abs'])}[/dim]")
    if s.get("reasons"):
        console.print(f"  reason: {', '.join(str(r) for r in s['reasons'])}")
    console.print()


@coverage.command("case-report")
@click.option("--output", "-o", "output_dir", required=True,
              type=click.Path(file_okay=False),
              help="运行目录（含 coverage/case_tp.json 的那一层）")
@click.option("--tp", "tp_id", default=None, help="只看某条测试点（如 TP-NPUSCH-D_DEP-RAW）")
@click.option("--sample", "max_cases", default=0, type=int,
              help="逐用例解析上限（超过则采样，并在 evidence_sampled 里说明）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_case_report(output_dir, tp_id, max_cases, json_output):
    """逐用例取证链：用例 → 覆盖仓 → 测试点 → 波形

    \b
    示例:
      vagent coverage case-report -o output_xxx --tp TP-NPUSCH-D_DEP-RAW
    """
    from src.tools.common.lib.collect_real_coverage import _case_cov_matrix

    try:
        idx = _case_cov_matrix(Path(output_dir), max_cases=max_cases)
    except Exception as e:                            # noqa: BLE001
        click.echo(f"逐用例取证读取失败: {e}", err=True)
        return
    by_tp = idx.get("by_tp") or {}
    if not by_tp:
        click.echo(f"没有逐用例证据（{output_dir}/coverage/testpoints.yaml 缺失"
                   f"或回归目录为空）", err=True)
        return
    if json_output:
        payload = by_tp.get(tp_id, {}) if tp_id else {"counts": idx.get("counts"),
                                                      "by_tp": by_tp}
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return

    cases = {c.get("task"): c for c in idx.get("cases") or []}
    for tid in ([tp_id] if tp_id else list(by_tp)):
        _print_tp_chain(tid, by_tp.get(tid), cases)
    console.print(f"[dim]共 {idx.get('counts', {}).get('total', 0)} 条；"
                  f"签核 {idx.get('counts', {}).get('signed_off', 0)} / "
                  f"未签核 {idx.get('counts', {}).get('unsigned', 0)}[/dim]")


def _print_evidence_tp(tp: dict, review: dict) -> None:
    """打印一条 TP 的四层证据（人读；机器读走 `--json`）。"""
    mark = {"VERIFIED": "[green]VERIFIED[/green]",
            "PARTIAL": "[yellow]PARTIAL[/yellow]",
            "NOT_VERIFIED": "[red]NOT_VERIFIED[/red]",
            "PENDING_BACKEND": "[cyan]PENDING_BACKEND[/cyan]"}.get(
                tp.get("contract_status"), str(tp.get("contract_status")))
    console.print(f"[bold]{tp.get('tp_id')}[/bold]  {mark}  "
                  f"{tp.get('dimension')}={tp.get('value')}  "
                  f"req={tp.get('requirement') or '-'}")
    for layer_def in review.get("four_layers") or []:
        key = layer_def.get("key")
        name = layer_def.get("name") or key
        question = layer_def.get("question") or ""
        layer = (tp.get("evidence_layers") or {}).get(key) or {}
        status = layer.get("status") or "?"
        color = "green" if status == "PROVEN" else (
            "yellow" if status == "PARTIAL" else
            ("cyan" if status in ("NOT_APPLICABLE", "PENDING_BACKEND") else "red"))
        console.print(f"  {name:<6} [{color}]{status:<16}[/{color}] {question}  "
                      f"{layer.get('proves') or ''}")
    if tp.get("signed_off_by"):
        console.print(f"  signoff: {tp['signed_off_by']}  wave={tp.get('wave') or '-'}")
    console.print()


@coverage.command("tp-evidence")
@click.option("--output", "-o", "output_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--tp", "tp_id", default=None, help="只看某条测试点")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def coverage_tp_evidence(output_dir, tp_id, json_output):
    """TP Cov 证据视图：功能覆盖 / 时序 / 数据 / 路径 四层按契约汇聚

    \b
    示例:
      vagent coverage tp-evidence -o output_xxx
      vagent coverage tp-evidence -o output_xxx --tp TP-NPUSCH-D_QUEUE-0
    """
    from src.tools.checking.coverage_tools.tp_evidence import load_tp_evidence

    ev = load_tp_evidence(Path(output_dir))
    tps = ev.get("tps") or []
    if not tps:
        click.echo(f"没有 TP IR / 证据（{output_dir}/coverage/testpoints.yaml）",
                   err=True)
        return
    if json_output:
        payload = (next((t for t in tps if t.get("tp_id") == tp_id), {})
                   if tp_id else ev)
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return
    console.print(f"[bold]TP Cov 证据视图[/bold] —— {ev.get('run')}  "
                  f"{ev.get('counts')}")
    console.print(f"[dim]{(ev.get('review') or {}).get('answer') or ''}[/dim]\n")
    wanted = [tp_id] if tp_id else [t.get("tp_id") for t in tps]
    by_id = {t.get("tp_id"): t for t in tps}
    for tid in wanted:
        if tid not in by_id:
            console.print(f"[red]{tid}: 没有这条测试点[/red]")
            continue
        _print_evidence_tp(by_id[tid], ev.get("review") or {})
    proof = (ev.get("review") or {}).get("path_proof") or []
    if proof:
        console.print("[bold]PATH 组[/bold]")
        for b in proof:
            console.print(f"  {b.get('group')}.{b.get('bin')}  "
                          f"tp={b.get('tp_id') or '-'}  status={b.get('status')}  "
                          f"checks={', '.join(b.get('checks') or []) or '-'}")


@coverage.command("case-evidence")
@click.option("--output", "-o", "output_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--format", "-f", "fmt", default="terminal",
              type=click.Choice(["terminal", "markdown", "html", "json"]),
              help="输出格式")
@click.option("--out", "out_prefix", default="", help="markdown/html 落盘前缀")
def coverage_case_evidence(output_dir, fmt, out_prefix):
    """Case 证据视图：用例 / 功能契约 / 功能组×路径 / 缺口 四张表

    \b
    示例:
      vagent coverage case-evidence -o output_xxx
      vagent coverage case-evidence -o output_xxx -f html --out report/case_view
    """
    from src.tools.humanview.case_associate_view import (
        build_case_view, render_html, render_markdown, render_terminal)

    try:
        data = build_case_view(Path(output_dir))
    except Exception as exc:                        # noqa: BLE001
        click.echo(f"Case 证据视图构建失败: {exc}", err=True)
        return
    if not data.get("cases") and not data.get("features"):
        click.echo(f"没有可展示的证据（{output_dir} 里没有 case_cov / TP IR）",
                   err=True)
        return
    text = {"terminal": render_terminal, "markdown": render_markdown,
            "html": render_html}.get(fmt)
    if fmt == "json":
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return
    rendered = text(data) if text else render_terminal(data)
    if out_prefix and fmt in ("markdown", "html"):
        path = Path(out_prefix).with_suffix(".md" if fmt == "markdown" else ".html")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        console.print(f"已写到 {path}")
        return
    console.print(rendered)


@coverage.command("case-gate")
@click.option("--output", "-o", "output_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
@click.option("--strict", is_flag=True,
              help="有 blocker 时以非零码退出（CI 用）")
@click.option("--rules", "show_rules", is_flag=True,
              help="只打印规则表（id / 级别 / 阶段 / 是否启用）")
def coverage_case_gate(output_dir, json_output, strict, show_rules):
    """Case 门禁：blocker / warning / info（读 case_view + cell_matrix + evd）

    \b
    示例:
      vagent coverage case-gate -o output_xxx
      vagent coverage case-gate -o output_xxx --strict   # CI 里当硬门
    """
    from src.tools.humanview.case_associate_view.gates import (
        load_declarative, load_rules, rules_table, write_gates)

    if show_rules:
        table = {r["id"]: r for r in rules_table(load_rules())}
        for rule in load_declarative():
            entry = table.setdefault(rule["id"], {
                "id": rule["id"], "level": rule.get("level", "warning"),
                "stage": rule.get("stage", "block"),
                "enabled": rule.get("enabled", True) is not False,
                "title": rule.get("title", rule["id"])})
            entry["declarative"] = True
        if json_output:
            click.echo(json.dumps(list(table.values()), ensure_ascii=False,
                                  indent=2))
            return
        for row in sorted(table.values(), key=lambda r: r["id"]):
            console.print(f"  {row['id']:<30} {row['level']:<8} "
                          f"{row['stage']:<7} "
                          f"{'on ' if row.get('enabled', True) else 'off'} "
                          f"{row['title']}")
        return

    try:
        data = write_gates(Path(output_dir))
    except Exception as exc:                        # noqa: BLE001
        click.echo(f"Case 门禁执行失败: {exc}", err=True)
        raise SystemExit(2)
    if json_output:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        counts = data.get("counts") or {}
        console.print(f"[bold]Case Gate[/bold]  {data.get('verdict')}  "
                      f"blocker={counts.get('blocker', 0)} "
                      f"warning={counts.get('warning', 0)} "
                      f"info={counts.get('info', 0)}")
        for level in ("blockers", "warnings", "infos"):
            for item in (data.get(level) or [])[:20]:
                console.print(f"  [{level[:-1]}] {item.get('rule')} · "
                              f"{item.get('target')} · {item.get('message')}")
    if strict and (data.get("counts") or {}).get("blocker"):
        raise SystemExit(1)


@cli.group()
def wave():
    """波形索引（用例 ↔ 测试点 ↔ 波形）"""
    pass


@wave.command("show")
@click.option("--output", "-o", "output_dir", required=True,
              type=click.Path(file_okay=False), help="运行目录")
@click.option("--task", "task", default=None, help="只看某条用例（如 tp_xxx_seed_6001）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def wave_show(output_dir, task, json_output):
    """读 waves/manifest.json，给出波形路径与打开命令

    \b
    示例:
      vagent wave show -o output_xxx --task tp_npusch_d_queue_0_seed_6001
    """
    from src.tools.common.lib.case_meta import (
        read_wave_manifest, visualizer_command)

    manifest = read_wave_manifest(Path(output_dir))
    entries = manifest.get("entries") or []
    if task:
        entries = [e for e in entries if e.get("task") == task]
    if json_output:
        click.echo(json.dumps({"entries": entries,
                               "by_tp": manifest.get("by_tp") or {}},
                              indent=2, ensure_ascii=False, default=str))
        return
    if not entries:
        click.echo(f"没有波形索引条目（{output_dir}/waves/manifest.json）", err=True)
        return
    for e in entries:
        console.print(f"[bold]{e.get('task')}[/bold]  test={e.get('test') or '-'} "
                      f"seed={e.get('seed')}  stage={e.get('stage') or '-'}")
        console.print(f"  tp    : {', '.join(e.get('tp_ids') or []) or '-'}")
        console.print(f"  wave  : {e.get('wave') or e.get('wave_abs') or '-'}"
                      f"{'' if e.get('wave_exists') else '  [yellow](不存在)[/yellow]'}")
        cmd = visualizer_command(e.get("wave_abs") or "")
        if cmd:
            console.print(f"          [dim]{cmd}[/dim]")
        console.print()


# ═══════════════════════════════════════════════════════════════
# vagent env — UVM 环境操作 (P3)
# ═══════════════════════════════════════════════════════════════

