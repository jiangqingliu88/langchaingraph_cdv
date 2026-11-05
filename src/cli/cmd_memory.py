"""CLI 命令组：知识图谱 / 蒸馏 / 驾驭 / 排除 / 血缘。

从 `src/cli/commands.py` 拆出（L4 记忆与 L5 治理域）；导入本模块即把命令
注册到 `cli`。共享 helper 仍从 `commands` 导入，别在这里再造一份。
"""
from __future__ import annotations

import asyncio  # noqa: F401
from pathlib import Path  # noqa: F401

import click

from src.cli.output import get_output_adapter  # noqa: F401
from src.cli.commands import (  # noqa: F401
    cli, console, _exclude_registry,
)

@cli.group("knowledge")
def knowledge():
    """验证知识图谱：导出/导入签核证据包（跨项目复用）

    \b
    示例:
      vagent knowledge export gemm -c 96.0            # 导出本项目的签核证据包
      vagent knowledge import other_project_signoff.json   # 合并进本项目 KG
    """
    pass


@knowledge.command("export")
@click.argument("project_name")
@click.option("--output", "-o", "out_path", default=None,
              help="输出 JSON 路径（默认 <project>_signoff.json）")
@click.option("--coverage", "-c", type=float, default=None, help="本项目功能覆盖率（%%）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def knowledge_export(project_name, out_path, coverage, json_output):
    """导出签核证据包（KG + 覆盖率摘要）供其它项目导入复用。

    marketplace.export_signoff_package 一直存在却零调用（V4 的「签核证据包
    交换」因此从未真正发生），此处接上 CLI。
    """
    import asyncio
    out = get_output_adapter(json_output)
    try:
        from src.layers.l3_decision.knowledge.persistence import load_graph_from_db
        from src.layers.l3_decision.knowledge.marketplace import export_signoff_package
        g = asyncio.run(load_graph_from_db())
        if len(g) == 0:
            out.print_error("知识图谱为空：先跑一次 design 阶段把 KG 写入库")
            return
        path = out_path or f"{project_name}_signoff.json"
        cov = {"functional": coverage} if coverage is not None else {}
        p = export_signoff_package(g, project_name, cov, path)
        out.print_result({"project": project_name, "nodes": len(g),
                          "package": p, "coverage": cov}, title="签核证据包已导出")
    except Exception as e:
        out.print_error(f"导出失败: {e}")


@knowledge.command("import")
@click.argument("package_path", type=click.Path(exists=True))
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def knowledge_import(package_path, json_output):
    """导入签核证据包并合并进本项目知识图谱（跨项目复用）。"""
    import asyncio
    out = get_output_adapter(json_output)
    try:
        from src.layers.l3_decision.knowledge.persistence import (
            load_graph_from_db, save_graph_to_db)
        from src.layers.l3_decision.knowledge.marketplace import (
            load_signoff_package, merge_package_into_graph)
        pkg = load_signoff_package(package_path)
        g = asyncio.run(load_graph_from_db())
        added = merge_package_into_graph(g, pkg)
        if added:
            asyncio.run(save_graph_to_db(g))
        out.print_result({"from_project": pkg.get("project", ""), "added_nodes": added,
                          "total_nodes": len(g)}, title=f"已合并 {added} 个新节点")
    except Exception as e:
        out.print_error(f"导入失败: {e}")


@cli.group("distill")
def distill():
    """Agent 自主蒸馏：把经验固化为能力（L5 进化）"""
    pass


@distill.command("run")
@click.option("--apply", is_flag=True, help="灰度上线（回归验证通过后固化）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def distill_run(apply, json_output):
    """扫描经验库 → 生成蒸馏提案 → 验证 → （可选）灰度上线"""
    out = get_output_adapter(json_output)
    try:
        from src.layers.l5_evolution.distillation import DistillationOrchestrator
        orch = DistillationOrchestrator("output")
        result = orch.run(apply=apply)
        if json_output:
            click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            console.print(f"[cyan]蒸馏扫描:[/cyan] {result['scanned']} 条提案"
                          f"（灰度上线 {result['applied']} 条）")
            for p in result["proposals"]:
                ch = {"debug_to_fix": "调试→模板", "gap_to_policy": "gap→策略",
                      "decision_weight": "决策→权重"}.get(p["channel"], p["channel"])
                console.print(f"  [{p['channel']}] {p['proposal_id']} — {ch}: {p['reasoning'][:50]}")
    except Exception as e:
        out.print_error(str(e))


@distill.command("list")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def distill_list(json_output):
    """列出已固化的蒸馏能力（live 模板/策略/权重）"""
    out = get_output_adapter(json_output)
    try:
        from src.layers.l5_evolution.distillation import DistillationOrchestrator
        orch = DistillationOrchestrator("output")
        result = {
            "templates": orch.get_live_templates(),
            "policy_bins": orch.get_live_policy_bins(),
            "weights": orch.get_live_weights(),
        }
        if json_output:
            click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            console.print(f"[cyan]已固化模板:[/cyan] {len(result['templates'])} 条")
            console.print(f"[cyan]已固化策略覆盖点:[/cyan] {len(result['policy_bins'])} 条")
            console.print(f"[cyan]已固化决策权重:[/cyan] {result['weights']}")
    except Exception as e:
        out.print_error(str(e))


@distill.command("rollback")
@click.argument("proposal_id")
def distill_rollback(proposal_id):
    """回滚某条已固化的蒸馏能力"""
    try:
        from src.layers.l5_evolution.distillation import DistillationOrchestrator
        orch = DistillationOrchestrator("output")
        if orch.rollback(proposal_id):
            console.print(f"[green]已回滚: {proposal_id}[/green]")
        else:
            console.print(f"[yellow]未找到 live 提案: {proposal_id}[/yellow]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@cli.group("govern")
def govern():
    """统一驾驭层：预算 + 熔断 + 细粒度干预 + 决策可干预"""
    pass


@govern.command("status")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def govern_status(json_output):
    """查看驾驭状态：熔断器 + 预算 + 干预指令"""
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.governance.governor import Governor
        gov = Governor("output")
        status = gov.status()
        if json_output:
            click.echo(json.dumps(status, indent=2, ensure_ascii=False, default=str))
        else:
            b = status["breaker"]
            budget = status["budget"]
            console.print(Panel(
                f"[cyan]熔断（连续失败 ≥ {b['threshold']} 次）:[/cyan] {b['open'] or '无'}\n"
                f"[cyan]失败计数:[/cyan] {b['failures'] or '无'}\n"
                f"[cyan]Token:[/cyan] {budget['tokens']['used']}/{budget['tokens']['budget']}\n"
                f"[cyan]时间:[/cyan] {budget['time_s']['used']}s/{budget['time_s']['budget']}s\n"
                f"[cyan]EDA 调用:[/cyan] {budget['eda']['used']}/{budget['eda']['budget']}\n"
                f"[cyan]预算耗尽:[/cyan] {'是' if budget['exhausted'] else '否'}\n"
                f"[cyan]干预指令:[/cyan] {status['intervention'] or '无'}",
                title="驾驭状态（Governor）"))
    except Exception as e:
        out.print_error(str(e))


@govern.command("override")
@click.argument("action_type")
def govern_override(action_type):
    """人工接管决策：强制指定下一步动作（如 RELAX_CONSTRAINT / EXPAND_SEEDS）"""
    try:
        from src.layers.l2_orchestration.governance.governor import Intervention
        Intervention("output").write({"cmd": "override_action", "action_type": action_type})
        console.print(f"[green]已写入干预指令：override → {action_type}[/green]")
        console.print("[dim]下次闭环决策时会用此动作覆盖，执行后自动清除。[/dim]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@govern.command("reset")
@click.argument("action_type")
def govern_reset(action_type):
    """人工复位某动作的熔断状态"""
    try:
        from src.layers.l2_orchestration.governance.governor import CircuitBreaker
        # 熔断状态是内存态，复位需通过 Governor（新建实例会丢失状态）。
        # 这里用"清除干预 + 提示"：熔断是运行时内存态，重启即复位。
        console.print(f"[yellow]熔断是运行时内存态，重启 run 即复位。[/yellow]")
        console.print(f"[dim]若要强制继续，用 'vagent govern override {action_type}' 接管。[/dim]")
    except Exception as e:
        console.print(f"[red]{e}[/red]")


@cli.group("exclude")
def exclude():
    """允许放弃：四步闭环（发现→归因→审计→调规）"""
    pass


@exclude.command("list")
@click.option("--status", "-s", "status_filter", default="all",
              type=click.Choice(["all", "approved", "proposed", "rejected"]),
              help="按状态过滤")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def exclude_list(status_filter, json_output):
    """列出 Exclude 记录（已批准/待审批/已拒绝）"""
    out = get_output_adapter(json_output)
    reg = _exclude_registry()
    try:
        approved = reg.get_approved_excludes()
        pending = reg.list_pending()
        stats = reg.stats()

        if json_output:
            click.echo(json.dumps({
                "stats": stats,
                "approved": approved,
                "pending": pending,
            }, indent=2, ensure_ascii=False, default=str))
            return

        console.print(f"[bold]Exclude 状态库[/bold] — "
                      f"批准 {stats['approved']} | 待审批 {stats['pending']} | "
                      f"已放弃点 {stats['excluded_points']}")

        type_label = {"unreachable": "结构死代码", "excluded_by_design": "规格不测",
                      "not_worth_it": "成本过高"}
        def _rows(entries):
            return [[e["exclude_id"], e["coverage_point"],
                     type_label.get(e["exclude_type"], e["exclude_type"]),
                     (e["reason"] or "—")[:36],
                     e.get("approver") or "—",
                     (e.get("audit_hash") or "")[:10] + "…" if e.get("audit_hash") else "—"]
                    for e in entries]

        if status_filter in ("all", "approved") and approved:
            out.print_table(["ID", "覆盖点", "类型", "理由", "审批人", "哈希指纹"],
                            _rows(approved), title="已批准（生效）")
        if status_filter in ("all", "proposed") and pending:
            out.print_table(["ID", "覆盖点", "类型", "理由", "审批人", "哈希指纹"],
                            _rows(pending), title="待审批")
        if status_filter == "all" and not approved and not pending:
            console.print("[dim]暂无 Exclude 记录。用 'vagent exclude propose' 提议。[/dim]")
    finally:
        reg.close()


@exclude.command("propose")
@click.argument("coverage_point")
@click.option("--reason", "-r", required=True, help="放弃理由（必填，审计依据）")
@click.option("--type", "-t", "exclude_type", default="not_worth_it",
              type=click.Choice(["unreachable", "excluded_by_design", "not_worth_it"]),
              help="归因分类")
@click.option("--evidence", "-e", default="", help="证据（波形/RTL 追溯等）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def exclude_propose(coverage_point, reason, exclude_type, evidence, json_output):
    """提议 Exclude（归因分类 → 待审批）

    \b
    示例:
      vagent exclude propose opcode[31:16] -r 'tie-off 固定死代码' -t unreachable
      vagent exclude propose burst_64      -r '规格不要求测 64 拍' -t excluded_by_design
    """
    out = get_output_adapter(json_output)
    reg = _exclude_registry()
    try:
        existing = reg.get_point_status(coverage_point)
        if existing:
            out.print_error(f"覆盖点 '{coverage_point}' 已存在（状态: {existing}）")
            return
        exclude_id = reg.propose_exclude(coverage_point, reason, exclude_type, evidence)
        out.print_result({"exclude_id": exclude_id, "coverage_point": coverage_point,
                          "type": exclude_type, "status": "proposed"},
                         title="Exclude 已提议（待审批）")
        console.print(f"[dim]审批: vagent exclude approve {exclude_id} --approver <姓名>[/dim]")
    finally:
        reg.close()


@exclude.command("approve")
@click.argument("exclude_id")
@click.option("--approver", "-a", default=None, help="审批人签名（默认取环境变量 USER）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def exclude_approve(exclude_id, approver, json_output):
    """审计门控：批准 Exclude（记录审批人 + 哈希指纹，接证据链）"""
    out = get_output_adapter(json_output)
    approver = approver or os.environ.get("USER", "engineer")
    reg = _exclude_registry()
    try:
        ok = reg.approve_exclude(exclude_id, approver)
        if ok:
            out.print_success(f"已批准 {exclude_id}（审批人: {approver}，哈希指纹已接入证据链）")
        else:
            out.print_error(f"Exclude {exclude_id} 不存在")
    finally:
        reg.close()


@exclude.command("reject")
@click.argument("exclude_id")
@click.option("--approver", "-a", default=None, help="审批人签名")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def exclude_reject(exclude_id, approver, json_output):
    """拒绝 Exclude（点仍需覆盖）"""
    out = get_output_adapter(json_output)
    approver = approver or os.environ.get("USER", "engineer")
    reg = _exclude_registry()
    try:
        reg.reject_exclude(exclude_id, approver)
        out.print_success(f"已拒绝 {exclude_id}（审批人: {approver}）")
    finally:
        reg.close()


@exclude.command("effective")
@click.option("--coverage", "-c", type=float, required=True, help="当前覆盖率（%）")
@click.option("--total", "-t", type=int, required=True, help="总覆盖点数")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def exclude_effective(coverage, total, json_output):
    """动态调规：计算有效覆盖率 = coverage / (total - excluded)"""
    out = get_output_adapter(json_output)
    reg = _exclude_registry()
    try:
        excluded = len(reg.get_excluded_points())
        effective = reg.effective_coverage(coverage, total)
        result = {"raw_coverage": coverage, "total_points": total,
                  "excluded": excluded,
                  "effective_total": max(total - excluded, 1),
                  "effective_coverage": effective}
        out.print_result(result, title="有效覆盖率（Exclude 调规）")
        console.print(f"[dim]已放弃 {excluded} 点，从分母剔除后覆盖率 {coverage}% → {effective}%[/dim]")
    finally:
        reg.close()


@cli.group("lineage")
def lineage_group():
    """血缘：这一轮跑的是 RTL 的哪一版、跟谁比、哪些 bug 挂在哪版

    \b
    版本号由 **RTL 目录内容哈希**自动派生（不依赖 git，`--rtl <dir>` 也能用）：
    内容变了就是新版。基准 = **每个模块的第一次 run**，写下就不再改 ——
    "相对最初那版偏了多少"是单调的，"上一轮"会随跑的次数漂。

    \b
    示例:
      vagent lineage versions npu_sched
      vagent lineage baseline npu_sched
      vagent lineage bugs npu_sched --version 2
      vagent lineage compare output_x_jiang_20261014_010101
    """
    pass


@lineage_group.command("versions")
@click.argument("module", required=False, default="")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def lineage_versions_cmd(module, json_output):
    """列出 RTL 版本（`module` 省略则全部）

    \b
      vagent lineage versions            # 全部模块
      vagent lineage versions npu_sched  # 只看这个模块
    """
    out = get_output_adapter(json_output)
    from src.app.services.flow.lineage_api import lineage_versions

    rows = lineage_versions(module)
    if json_output:
        out.print_result(rows, title="RTL 版本")
        return
    if not rows:
        console.print("[yellow]还没有版本记录[/yellow]（跑一次 verify 就有了）")
        return
    out.print_table(["模块", "版本", "哈希", "首次 run", "记录时间"],
                    [[r["module"], r["name"], r["hash"],
                      r["first_seen_run_id"][:32], r["created_at"][:19]]
                     for r in rows], title="RTL 版本")


@lineage_group.command("baseline")
@click.argument("module", required=False, default="")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def lineage_baseline_cmd(module, json_output):
    """查看基准锚点（每个模块的**第一次** run）

    \b
      vagent lineage baseline npu_sched
    """
    out = get_output_adapter(json_output)
    from src.app.services.flow.lineage_api import lineage_versions, resolve_baseline_for

    if not module:
        mods = sorted({r["module"] for r in lineage_versions("")})
        if json_output:
            out.print_result({m: resolve_baseline_for(m) for m in mods},
                             title="基准锚点")
            return
        if not mods:
            console.print("[yellow]还没有模块被锚过基准[/yellow]")
            return
        for m in mods:
            base = resolve_baseline_for(m)
            console.print(f"{m}：[cyan]{base['name']}[/cyan] @ "
                          f"{base['run_id']}" if base else f"{m}：[yellow]无锚[/yellow]")
        return

    base = resolve_baseline_for(module)
    if json_output:
        out.print_result(base or {}, title=f"{module} 的基准")
        return
    if not base:
        console.print(f"[yellow]{module} 还没有基准[/yellow]"
                      f"（这个模块还没成功跑完过一次带 RTL 的 run）")
        return
    console.print(f"{module} 的基准：[cyan]{base['name']}[/cyan] "
                  f"@ {base['run_id']}（{base['created_at'][:19]}）")


@lineage_group.command("bugs")
@click.argument("module", required=False, default="")
@click.option("--version", "-v", "version_no", type=int, default=None,
              help="只看这一版上发现或修好的")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def lineage_bugs_cmd(module, version_no, json_output):
    """列出 bug ↔ RTL 版本的关联

    \b
      vagent lineage bugs npu_sched
      vagent lineage bugs npu_sched --version 2
    """
    out = get_output_adapter(json_output)
    from src.app.services.flow.lineage_api import lineage_bugs

    rows = lineage_bugs(module, version_no)
    if json_output:
        out.print_result(rows, title="bug ↔ RTL 版本")
        return
    if not rows:
        console.print("[yellow]没有关联记录[/yellow]"
                      "（debug 阶段记 bug 时会自动挂上版本）")
        return
    out.print_table(["bug", "模块", "发现于", "修好于", "发现 run"],
                    [[r["bug_id"], r["module"],
                      f"v{r['found_version_no']}" if r["found_version_no"] else "-",
                      f"v{r['fixed_version_no']}" if r["fixed_version_no"] else "-",
                      (r["found_run_id"] or "")[:32]] for r in rows],
                    title="bug ↔ RTL 版本")


@lineage_group.command("bind-modules")
@click.option("--apply", "apply_", is_flag=True,
              help="真的写库（缺省只干跑，打印归属表）")
@click.option("--candidate", "-c", "candidates", multiple=True,
              help="补充候选模块名（可重复；缺省自动枚举 specs/ 与各 run 的 spec.json）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def lineage_bind_modules_cmd(apply_, candidates, json_output):
    """把用例库里**没有模块归属的老行**归位（一次性）

    \b
    `module` 列是后加的，之前的行没有归属；而回归按模块筛是**严格按列**筛的
    （读侧不猜 —— 猜错就是把别的项目的用例放进本项目）。所以老行要显式归位。

    \b
    归属按命名约定取**最长匹配**；agent 自检（`*_loopback`）与兜底名（`dut`）
    一律不归属 —— 它们本来就不属于任何模块。**先干跑看一眼，再 --apply。**

    \b
    示例:
      vagent lineage bind-modules              # 只看归属表
      vagent lineage bind-modules --apply      # 写库（先备份 .bak）
    """
    out = get_output_adapter(json_output)
    from src.app.services.flow.lineage_api import bind_testcase_modules

    result = bind_testcase_modules(candidates=candidates or None, apply=apply_)
    if json_output:
        out.print_result(result, title="用例库模块归位")
        return
    console.print(f"候选模块：{', '.join(result['candidates']) or '（无）'}")
    console.print(f"待归位的行：{result['total_legacy']}")
    if result["attributed"]:
        out.print_table(["归到模块", "行数"],
                        [[m, str(n)] for m, n in result["attributed"].items()],
                        title="归属结果")
    if result["unmatched"]:
        console.print(f"不归属的 {len(result['unmatched'])} 行"
                      f"（agent 自检 / 兜底名）—— 按模块筛时自然落选：")
        for n in result["unmatched"][:8]:
            console.print(f"  [dim]{n}[/dim]")
        if len(result["unmatched"]) > 8:
            console.print(f"  [dim]…还有 {len(result['unmatched']) - 8} 行[/dim]")
    if result["applied"]:
        console.print(f"[green]✓ 已写库[/green]　备份：{result['backup']}")
    else:
        console.print("[yellow]干跑，没写库。[/yellow]确认无误后加 `--apply`")


@lineage_group.command("compare")
@click.argument("current", type=click.Path(exists=True))
@click.option("--baseline", "-b", "baseline", default="",
              help="显式指定基准 run 目录（缺省自动用血缘里的锚点）")
@click.option("--module", "-m", default="", help="锚点查不到时按模块兜")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def lineage_compare_cmd(current, baseline, module, json_output):
    """与**基准**对比（`compare_runs` 的自动锚点版）

    \b
      vagent lineage compare output_x_jiang_20261014_010101
      vagent lineage compare out_x -b output_npu2_jiang_20261012_230152
    """
    out = get_output_adapter(json_output)
    from src.app.services.flow.lineage_api import compare_against_baseline

    result = compare_against_baseline(current, baseline=baseline, module=module)
    if result.get("error"):
        out.print_error(result["error"], code=2)
        sys.exit(2)
    if json_output:
        out.print_result(result, title="与基准对比")
        return
    s = result.get("summary") or {}
    console.print(f"基准：[cyan]{Path(result['baseline_dir']).name}[/cyan]")
    console.print(f"当前：[cyan]{result.get('current', '')}[/cyan]")
    console.print(f"  新失败 {s.get('newly_failing', 0)}　"
                  f"修好 {s.get('fixed', 0)}　"
                  f"覆盖率差 {s.get('coverage_delta')}")
    newly = (result.get("cases") or {}).get("newly_failing") or []
    for name in newly[:20]:
        console.print(f"  [red]✗[/red] {name}")


@lineage_group.command("prune")
@click.option("--keep-last", default=50, show_default=True,
              help="每个模块**至少保留**最近这么多版（不管有没有引用）")
@click.option("--module", "-m", default="", help="只清这个模块（缺省全部）")
@click.option("--apply", "apply_", is_flag=True,
              help="真删。**默认只预演**（打印要删什么，不动库）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def lineage_prune_cmd(keep_last, module, apply_, json_output):
    """清理**孤儿**版本行（没有被任何 run / 基准 / bug 引用的那些）

    \b
      vagent lineage prune                 # 预演：看会删什么
      vagent lineage prune --apply         # 真删
      vagent lineage prune -m npu_sched --keep-last 20 --apply

    三条判据全中才删：没 run 引用、不是基准锚、不是 bug 的 found/fixed 版本。
    保守到几乎删不掉东西是故意的 —— 真正会涨的是 `run_rtl_bindings`
    （一行一次 run），而那是**证据**，不在这里删。
    """
    out = get_output_adapter(json_output)
    from src.app.services.flow.lineage_api import prune_lineage

    result = prune_lineage(keep_last=keep_last, module=module, dry_run=not apply_)
    if json_output:
        out.print_result(result, title="血缘清理")
        return
    n = result["pruned"]
    if not n:
        console.print(f"[green]没有可清理的孤儿版本[/green]"
                      f"（每模块保留最近 {result['keep_last']} 版）")
        return
    head = "将要删除" if result["dry_run"] else "已删除"
    console.print(f"[yellow]{head} {n} 个孤儿版本[/yellow]"
                  f"（保留窗口 {result['keep_last']}）")
    for v in result["versions"][:30]:
        console.print(f"  {v}")
    if result["dry_run"]:
        console.print("[dim]这是预演。确认无误后加 --apply 真删[/dim]")
