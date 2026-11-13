"""受控修复提案命令（M4）。"""
from __future__ import annotations

import json
from pathlib import Path

import click

from src.workbench.cli.commands import cli


def _load(path: str) -> dict:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() in (".yaml", ".yml"):
        import yaml
        return yaml.safe_load(text) or {}
    return json.loads(text)


@cli.group("repair")
def repair_group():
    """修复提案：只写 staging，必须由 Engine 复验。"""


@repair_group.command("validate")
@click.argument("proposal", type=click.Path(exists=True, dir_okay=False))
@click.option("--project-root", default=".", show_default=True)
@click.option("--json", "json_output", is_flag=True)
def repair_validate(proposal, project_root, json_output):
    """检查 proposal 是否越过受控边界。"""
    from src.agent_plane.specialists.debug.repair_policy import (
        proposal_from_dict, validate_proposal,
    )

    result = validate_proposal(proposal_from_dict(_load(proposal)), project_root)
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(("OK: " if result["ok"] else "REJECTED: ") + result["target"])
        for issue in result["issues"]:
            print(f"  - {issue}")
    raise SystemExit(0 if result["ok"] else 1)


@repair_group.command("stage")
@click.argument("proposal", type=click.Path(exists=True, dir_okay=False))
@click.option("--staging", required=True, type=click.Path(file_okay=False))
@click.option("--project-root", default=".", show_default=True)
@click.option("--json", "json_output", is_flag=True)
def repair_stage(proposal, staging, project_root, json_output):
    """把 proposal 写进 staging（绝不写项目根）。"""
    from src.agent_plane.specialists.debug.repair_policy import (
        proposal_from_dict, stage_patch,
    )

    result = stage_patch(proposal_from_dict(_load(proposal)), staging,
                         project_root)
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(("STAGED: " if result.get("ok") else "REJECTED: ")
              + str(result.get("staging_path") or result.get("issues")))
        if result.get("ok"):
            print("  requires_engine_verification = True")
    raise SystemExit(0 if result.get("ok") else 1)


__all__ = ["repair_group"]
