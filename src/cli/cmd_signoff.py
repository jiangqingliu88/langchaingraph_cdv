"""SignOffAI CLI 命令组：签核（signoff）

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
def signoff():
    """签核报告生成与证据链管理"""
    pass


@signoff.command("generate")
@click.argument("run_id", required=False)
@click.option("--type", "-t", "report_type", default="milestone",
              type=click.Choice(["tapeout", "milestone", "interim", "final"]),
              help="签核类型")
@click.option("--title", help="签核标题")
@click.option("--project-id", type=int, help="项目 ID")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def signoff_generate(run_id, report_type, title, project_id, json_output):
    """为指定 run 生成签核报告

    \b
    示例:
      vagent signoff generate <run_id>                     # 里程碑签核
      vagent signoff generate <run_id> --type tapeout      # 流片签核
      vagent signoff generate <run_id> --type final        # 最终签核
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified and no runs found")
        sys.exit(1)

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))

        title_text = title or f"Signoff: {report_type} — {rid}"
        out.print_result({
            "run_id": rid,
            "title": title_text,
            "type": report_type,
            "state": manifest.state,
            "overall_score": manifest.overall_score,
            "passed": manifest.passed,
            "total": manifest.total_phases,
            "evidence_hash": manifest.evidence_hash[:16] if manifest.evidence_hash else "N/A",
            "generated_at": manifest.generated_at,
        }, title=f"Signoff Report — {report_type}")

        # 持久化到 DB
        if project_id:
            try:
                from src.layers.l4_memory.persistence.repository import create_signoff
                import asyncio as _a
                sid = _a.run(create_signoff(
                    project_id=project_id, title=title_text,
                    report_type=report_type,
                    summary={"run_id": rid, "score": manifest.overall_score,
                             "passed": manifest.passed, "total": manifest.total_phases},
                    requester_id=1, run_id=rid,
                    manifest_hash=manifest.manifest_hash,
                ))
                out.print_success(f"Signoff saved to DB (id={sid})")
            except Exception as e:
                out.print_error(f"DB save failed: {e}")

    except Exception as e:
        out.print_error(f"Signoff generation failed: {e}")
        sys.exit(1)


@signoff.command("export")
@click.argument("run_id", required=False)
@click.option("--output", "-o", default="evidence.zip", help="输出 zip 路径")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def signoff_export(run_id, output, json_output):
    """导出签核证据包

    \b
    示例:
      vagent signoff export <run_id> -o evidence.zip
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        sys.exit(1)

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder, EvidencePackager
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))

        packager = EvidencePackager()
        zip_path = packager.package(manifest, Path(output))

        # Verify
        verify_result = packager.verify(zip_path)

        out.print_result({
            "zip_path": str(zip_path),
            "size_kb": round(zip_path.stat().st_size / 1024, 1),
            "valid": verify_result["valid"],
            "issues": verify_result["issues"],
            "manifest_hash": manifest.manifest_hash[:16] if manifest.manifest_hash else "N/A",
        }, title="Evidence Package Exported")

    except Exception as e:
        out.print_error(f"Export failed: {e}")
        sys.exit(1)


@signoff.command("verify")
@click.argument("run_id", required=False)
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def signoff_verify(run_id, json_output):
    """验证证据链完整性

    \b
    示例:
      vagent signoff verify <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        sys.exit(1)

    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        manifest = builder.build(session_id=rid.replace("run_", ""))

        issues = []
        if manifest.passed < manifest.total_phases:
            issues.append(f"{manifest.failed} phases failed")
        if manifest.overall_score < 50:
            issues.append(f"Overall score too low: {manifest.overall_score}")
        if not manifest.evidence_hash:
            issues.append("No evidence hash — artifacts may be incomplete")

        valid = len(issues) == 0
        out.print_result({
            "run_id": rid,
            "valid": valid,
            "issues": issues,
            "overall_score": manifest.overall_score,
            "passed": manifest.passed,
            "total": manifest.total_phases,
        }, title="Evidence Chain Verification")

    except Exception as e:
        out.print_error(f"Verification failed: {e}")
        sys.exit(1)


@signoff.command("checklist")
@click.argument("run_id", required=False)
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def signoff_checklist(run_id, json_output):
    """输出签核检查清单

    \b
    示例:
      vagent signoff checklist <run_id>
    """
    out = get_output_adapter(json_output)
    rid = run_id or _find_run_id()
    if not rid:
        out.print_error("No run_id specified")
        sys.exit(1)

    checklist = [
        {"item": "Specification completeness", "required": True},
        {"item": "Design architecture review", "required": True},
        {"item": "UVM environment validation", "required": True},
        {"item": "Test point coverage ≥ 95%", "required": True},
        {"item": "Regression pass rate ≥ 99%", "required": False},
        {"item": "Code coverage ≥ 90%", "required": True},
        {"item": "Functional coverage ≥ 95%", "required": True},
        {"item": "Assertion coverage ≥ 80%", "required": False},
        {"item": "Debug analysis complete", "required": False},
        {"item": "QA review passed", "required": True},
        {"item": "Signoff report generated", "required": True},
    ]

    # ── 动态检查：Exclude 待审批未处理 → 阻断签核（放弃必须闭环：提议→审批）──
    exclude_pending = 0
    try:
        reg = _exclude_registry()
        exclude_pending = reg.stats().get("pending", 0)
        reg.close()
    except Exception:
        pass
    if exclude_pending:
        checklist.append({
            "item": f"Exclude 待审批未处理（{exclude_pending} 条，阻断）",
            "required": True, "pending_excludes": exclude_pending,
        })
    else:
        checklist.append({"item": "Exclude 无待审批（放弃已闭环）", "required": False})

    if json_output:
        click.echo(json.dumps({"run_id": rid, "checklist": checklist}, indent=2, ensure_ascii=False))
    else:
        table = Table(title=f"Signoff Checklist — {rid}")
        table.add_column("#")
        table.add_column("Item")
        table.add_column("Required")
        for i, item in enumerate(checklist, 1):
            req = "[red]Required[/red]" if item["required"] else "[dim]Optional[/dim]"
            table.add_row(str(i), item["item"], req)
        console.print(table)


@signoff.command("diff")
@click.argument("run_a")
@click.argument("run_b")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def signoff_diff(run_a, run_b, json_output):
    """两次签核对比

    \b
    示例:
      vagent signoff diff <run_id_a> <run_id_b>
    """
    out = get_output_adapter(json_output)
    try:
        from src.layers.l2_orchestration.evidence.manifest import ManifestBuilder
        builder = ManifestBuilder()
        ma = builder.build(session_id=run_a.replace("run_", ""))
        mb = builder.build(session_id=run_b.replace("run_", ""))

        diff = {
            "run_a": {"id": run_a, "score": ma.overall_score, "passed": ma.passed, "total": ma.total_phases},
            "run_b": {"id": run_b, "score": mb.overall_score, "passed": mb.passed, "total": mb.total_phases},
            "delta": {
                "score": mb.overall_score - ma.overall_score,
                "passed": mb.passed - ma.passed,
            },
        }
        out.print_result(diff, title="Signoff Diff")

    except Exception as e:
        out.print_error(f"Diff failed: {e}")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# vagent diff — 版本差异对比 (P0)
# ═══════════════════════════════════════════════════════════════

