"""Resource / Interaction intent 验证命令。"""
from __future__ import annotations

import json

import click

from src.workbench.cli.commands import cli


@cli.group("resource")
def resource_group():
    """Resource / Interaction IR：确定性冲突与场景检查。"""


@resource_group.command("verify")
@click.argument("intent", type=click.Path(exists=True, dir_okay=False,
                                          path_type=str))
@click.option("--out", "out_dir", default="", help="落盘目录（可选）")
@click.option("--address-width", default=64, show_default=True, type=int)
@click.option("--json", "json_output", is_flag=True, help="机器可读 JSON")
def resource_verify(intent, out_dir, address_width, json_output):
    """intent（resources/operations/interactions）→ PASS / FAIL / INCOMPLETE。"""
    from src.engine_plane.verify.resource_intent import verify_file, write_result

    result = verify_file(intent, address_width=address_width)
    if out_dir:
        path = write_result(result, out_dir)
        result["evidence_path"] = str(path)
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        c = result["counts"]
        print(f"{result['status']}: {result['reason']}")
        print(f"  resources={c['resources']} operations={c['operations']} "
              f"interactions={c['interactions']} scenarios={c['scenarios']}")
        for fact in result["conflicts"]:
            print(f"  conflict: {fact['operation_a']} × {fact['operation_b']} "
                  f"{fact['overlap']} ({fact['reason']})")
        for fact in result["overflows"]:
            print(f"  overflow: {fact['operation_a']} × {fact['operation_b']}")
    raise SystemExit(0 if result["status"] == "PASS"
                     else 1 if result["status"] == "FAIL" else 2)


__all__ = ["resource_group"]
