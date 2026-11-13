"""统一工作入口 —— `vagent work <goal>`，按模式选择 Agent 或 Engine。"""
from __future__ import annotations

import json
import sys

import click

from src.cli.commands import cli


@cli.command("work")
@click.argument("goal")
@click.option("--mode", "work_mode", type=click.Choice(["agent", "verify"]),
              default="agent", help="agent（长循环）/ verify（确定性内核）")
@click.option("--workspace", "workspace", default=None,
              help="Agent 模式的工作区根（默认当前工程根）")
@click.option("--json", "json_output", is_flag=True, help="机器可读 JSON")
def work(goal, work_mode, workspace, json_output):
    """只描述目标：Agent 负责推进，Engine 负责可信结果。"""
    from src.modes import router

    try:
        if str(work_mode).lower() in ("verify", "engine"):
            result = router.run(goal, mode="verify")
        else:
            result = router.run(goal, mode="agent", workspace=workspace)
    except Exception as exc:                    # noqa: BLE001 失败要非零退出
        print(f"{work_mode} failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if json_output:
        print(json.dumps(result, ensure_ascii=False, default=str))
    else:
        router.render(result, work_mode)
    raise SystemExit(router.exit_code(result, work_mode))
