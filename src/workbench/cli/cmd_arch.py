"""Architecture 4.0 治理入口 —— Guard、8 平面、依赖矩阵。"""
from __future__ import annotations

import json

import click

from src.workbench.cli.commands import cli


@cli.group("arch")
def arch_group():
    """架构治理：Guard 2.x / 8 平面 / 依赖矩阵。"""


@arch_group.command("check")
@click.option("--json", "json_output", is_flag=True, help="机器可读 JSON")
def arch_check(json_output):
    """跑 Architecture Guard（预算 / 依赖 / 环 / 债务）。"""
    from config.architecture_guard import check

    result = check()
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Guard {result['tool_version']}: "
              + ("OK" if result["ok"] else "FAILED"))
        for key in ("line_issues", "complexity_issues", "zone_issues",
                    "import_issues", "cycle_issues"):
            for issue in result[key]:
                print(f"  [{issue['type']}] {issue}")
    raise SystemExit(0 if result["ok"] else 1)


@arch_group.command("planes")
@click.option("--json", "json_output", is_flag=True, help="机器可读 JSON")
def arch_planes(json_output):
    """8 个职责平面 + Workbench 的文件数与 Guard 状态。"""
    from src.workbench.api.architecture_service import snapshot

    data = snapshot()
    if json_output:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        raise SystemExit(0)
    print(f"Guard {data['guard']['version']}: "
          + ("OK" if data["guard"]["ok"] else "FAILED"))
    for plane in data["planes"]:
        print(f"  {plane['key']:<14} {plane['files']:>4} files  {plane['dir']}")
    wb = data["workbench"]
    print(f"  {'Workbench':<14} {wb['files']:>4} files  {wb['dir']}")


@arch_group.command("matrix")
@click.option("--json", "json_output", is_flag=True, help="机器可读 JSON")
def arch_matrix(json_output):
    """zone → 允许的依赖 + 实际 import 边数。"""
    from config.architecture_guard import dependency_matrix

    matrix = dependency_matrix()
    if json_output:
        print(json.dumps(matrix, ensure_ascii=False, indent=2))
        raise SystemExit(0)
    for zone, row in matrix.items():
        actual = ", ".join(f"{k}({v})" for k, v in row["imports"].items()) or "-"
        print(f"{zone:<14} allowed={','.join(row['allowed']) or '-'}")
        print(f"{'':<14} actual={actual}")
