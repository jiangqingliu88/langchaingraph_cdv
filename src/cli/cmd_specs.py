"""CLI 命令组：规格与 CI（spec / ci）。

从 `src/cli/commands.py` 拆出；导入本模块即把命令注册到 `cli`。
共享 helper 仍从 `commands` 导入，别在这里再造一份。
"""
from __future__ import annotations

import asyncio  # noqa: F401
import json  # noqa: F401
import os  # noqa: F401
import sys  # noqa: F401
from pathlib import Path  # noqa: F401

import click
from rich.panel import Panel  # noqa: F401
from rich.table import Table  # noqa: F401

from src.layers.l2_orchestration.execution import PipelineExecutionService
from src.cli.output import common_options, get_output_adapter  # noqa: F401
from src.cli.commands import (  # noqa: F401
    cli, console, _extract_requirements_from_md, _output_gitlab_ci,
    _output_junit,
)

@cli.group()
def spec():
    """规格文档操作"""
    pass


@spec.command("analyze")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option("--format", "-f", "fmt", default="rich",
              type=click.Choice(["rich", "json", "table"]), help="输出格式")
def spec_analyze(spec_file, fmt):
    """分析规格文档，输出结构化 JSON

    \b
    示例:
      vagent spec analyze spec.md                   # Rich 格式
      vagent spec analyze spec.md --format json     # JSON 格式
      vagent spec analyze spec.md --format table    # 表格格式
    """
    out = get_output_adapter(fmt == "json")
    content = Path(spec_file).read_text(encoding="utf-8")

    # Extract structured info
    import re
    title_match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else "Untitled"

    # Features / sections
    sections = re.findall(r'^##\s+(.+)', content, re.MULTILINE)

    # Requirements
    reqs = _extract_requirements_from_md(content)

    # Interfaces
    interfaces = []
    for m in re.finditer(r'NAME:\s*(\S+).*?TYPE:\s*(\S+).*?WIDTH:\s*(\d+)', content, re.DOTALL):
        interfaces.append({"name": m.group(1), "type": m.group(2), "width": m.group(3)})

    result = {
        "file": spec_file,
        "title": title,
        "sections": sections,
        "requirement_count": len(reqs),
        "requirements": reqs[:20],
        "interface_count": len(interfaces),
        "interfaces": interfaces[:20],
        "size": len(content),
        "lines": content.count("\n") + 1,
    }

    out.print_result(result, title=f"Spec Analysis: {Path(spec_file).name}")


@spec.command("validate")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def spec_validate(spec_file, json_output):
    """校验规格文档完整性

    \b
    示例:
      vagent spec validate spec.md
    """
    out = get_output_adapter(json_output)
    content = Path(spec_file).read_text(encoding="utf-8")

    issues = []
    warnings = []

    # Check for title
    if not content.startswith("#"):
        issues.append("Missing top-level title (should start with '# Title')")

    # Check for sections
    import re
    sections = re.findall(r'^##\s+(.+)', content, re.MULTILINE)
    if not sections:
        warnings.append("No second-level sections found")

    # Check for requirements
    reqs = _extract_requirements_from_md(content)
    if not reqs:
        warnings.append("No requirements found (format: **REQ_xxx**)")

    # Check for interfaces
    if "NAME:" not in content:
        warnings.append("No interface definitions found (format: NAME: xxx, TYPE: xxx, WIDTH: n)")

    valid = len(issues) == 0
    result = {
        "file": spec_file,
        "valid": valid,
        "issues": issues,
        "warnings": warnings,
        "sections": len(sections),
        "requirements": len(reqs),
    }

    if valid:
        out.print_result(result, title=f"✓ Spec Valid: {Path(spec_file).name}")
    else:
        out.print_result(result, title=f"✗ Spec Issues: {Path(spec_file).name}")


@spec.command("convert")
@click.argument("input_file", type=click.Path(exists=True))
@click.option("--to", "target_format", required=True,
              type=click.Choice(["json", "md"]), help="目标格式")
@click.option("--output", "-o", type=click.Path(), help="输出文件路径")
def spec_convert(input_file, target_format, output):
    """规格格式转换: MD ↔ JSON

    \b
    示例:
      vagent spec convert spec.md --to json -o spec.json
      vagent spec convert spec.json --to md -o spec.md
    """
    content = Path(input_file).read_text(encoding="utf-8")

    if target_format == "json":
        result = {
            "source": input_file,
            "content": content,
            "title": "",
            "requirements": _extract_requirements_from_md(content),
            "lines": content.count("\n") + 1,
        }
        # Extract title
        import re
        tm = re.search(r'^#\s+(.+)', content, re.MULTILINE)
        if tm:
            result["title"] = tm.group(1).strip()
        output_json = json.dumps(result, indent=2, ensure_ascii=False)

        if output:
            Path(output).write_text(output_json, encoding="utf-8")
            console.print(f"[green]Converted to JSON: {output}[/green]")
        else:
            click.echo(output_json)

    elif target_format == "md":
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            console.print("[red]Input is not valid JSON[/red]")
            return

        md_lines = [f"# {data.get('title', 'Untitled')}", ""]
        for req in data.get("requirements", []):
            md_lines.append(f"**{req.get('id', 'REQ_?')}**: {req.get('description', '')}")
        md_lines.append("")

        output_md = "\n".join(md_lines)
        if output:
            Path(output).write_text(output_md, encoding="utf-8")
            console.print(f"[green]Converted to MD: {output}[/green]")
        else:
            click.echo(output_md)


@spec.command("trace")
@click.argument("req_id")
@click.option("--full", is_flag=True, help="完整追溯链")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def spec_trace(req_id, full, json_output):
    """追溯需求 → 模块 → 测试点

    \b
    示例:
      vagent spec trace REQ_ALU_001               # 基础追溯
      vagent spec trace REQ_ALU_001 --full        # 完整追溯链
    """
    out = get_output_adapter(json_output)
    try:
        trace_result = asyncio.run(_trace_requirement(req_id))
        if not trace_result:
            out.print_error(f"Requirement '{req_id}' not found")
            return

        if full:
            out.print_result(trace_result, title=f"Full Trace: {req_id}")
        else:
            summary = {
                "req_id": trace_result.get("req_id", req_id),
                "description": trace_result.get("description", ""),
                "is_covered": trace_result.get("is_covered", False),
                "source_doc": trace_result.get("source_doc", {}),
            }
            out.print_result(summary, title=f"Trace: {req_id}")

    except Exception as e:
        out.print_error(f"Trace failed: {e}")


@cli.group()
def ci():
    """CI/CD 集成命令"""
    pass


@ci.command("verify")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option("--json", "-j", "json_output", is_flag=True, default=True, help="JSON 输出 (CI 默认)")
@click.option("--junit", is_flag=True, help="输出 JUnit XML")
@click.option("--gitlab", is_flag=True, help="GitLab CI 格式")
@click.option("--quiet", "-q", is_flag=True, help="静默模式")
def ci_verify(spec_file, json_output, junit, gitlab, quiet):
    """CI 模式运行验证（最小化输出 + 退出码）

    \b
    示例:
      vagent ci verify spec.md                     # CI 默认 JSON
      vagent ci verify spec.md --junit              # JUnit XML
      vagent ci verify spec.md --gitlab             # GitLab CI 格式
    """
    service = PipelineExecutionService.get_instance()
    spec = Path(spec_file).read_text(encoding="utf-8")

    async def run():
        result = await service.run_closed_loop(spec_text=spec, output_root=None)
        return result

    result = asyncio.run(run())

    if junit:
        _output_junit(result)
    elif gitlab:
        _output_gitlab_ci(result)
    else:
        # Default JSON
        click.echo(json.dumps({
            "status": "PASS" if result["passed"] == result["total"] else "FAIL",
            "passed": result["passed"],
            "total": result["total"],
            "score": result["overall_score"],
            "run_id": result["run_id"],
            "phases": [{"name": p["name"], "status": p["status"], "score": p.get("score", 0)}
                       for p in result["phases"]],
        }, indent=2, ensure_ascii=False))

    sys.exit(0 if result["passed"] == result["total"] else 1)


@ci.command("check")
def ci_check():
    """检查 CI 环境是否就绪"""
    checks = {}

    # Python version
    checks["python"] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    # Click installed
    try:
        import click
        checks["click"] = click.__version__
    except Exception:
        checks["click"] = "MISSING"

    # Rich installed
    try:
        import rich
        checks["rich"] = rich.__version__
    except Exception:
        checks["rich"] = "MISSING"

    # SQLAlchemy
    try:
        import sqlalchemy
        checks["sqlalchemy"] = sqlalchemy.__version__
    except Exception:
        checks["sqlalchemy"] = "MISSING"

    # Environment
    checks["platform_env"] = os.environ.get("PLATFORM_ENV", "development")
    checks["llm_provider"] = os.environ.get("LLM_PROVIDER", "deepseek")
    checks["ci"] = os.environ.get("CI", "false")

    all_ok = "MISSING" not in checks.values()
    status = "[green]READY[/green]" if all_ok else "[yellow]PARTIAL[/yellow]"
    console.print(f"CI Environment: {status}")
    for k, v in checks.items():
        color = "green" if v != "MISSING" else "red"
        console.print(f"  [{color}]{k}: {v}[/{color}]")


@ci.command("precheck")
@click.argument("spec_file", type=click.Path(exists=True))
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def ci_precheck(spec_file, json_output):
    """预检查（不实际执行）

    \b
    示例:
      vagent ci precheck spec.md
    """
    out = get_output_adapter(json_output)
    spec_path = Path(spec_file)
    content = spec_path.read_text(encoding="utf-8")

    checks = {
        "spec_exists": spec_path.exists(),
        "spec_size": spec_path.stat().st_size,
        "has_title": content.startswith("#"),
        "has_requirements": "**REQ_" in content,
        "has_interfaces": "NAME:" in content,
        "spec_lines": content.count("\n") + 1,
    }

    all_ok = all(checks.values()) if all(isinstance(v, bool) for v in [
        checks["spec_exists"], checks["has_title"],
        checks["has_requirements"], checks["has_interfaces"],
    ]) else False

    result = {"ready": all_ok, "checks": checks}
    out.print_result(result, title="CI Precheck")
