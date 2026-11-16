"""ChipStack 目录的 CLI 渲染与共享取数。

`cmd_project` 与 `cmd_workspace` 都只调这里 —— 目录怎么展示、验收怎么判，
只实现一次。不 import `commands`，避免拆出的命令模块互相拉扯。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from rich.console import Console
from rich.table import Table

from src.runtime_plane.artifacts.project_layout import ProjectLayout

console = Console()

_STATUS_COLOR = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}


def load_layout(root: str | Path | None = None,
                artifact_root: str | Path | None = None) -> ProjectLayout:
    return ProjectLayout.discover(root, artifact_root)


def print_layers(layout: ProjectLayout) -> None:
    table = Table(title=f"ChipStack 五层目录 · {layout.design_root}", show_lines=False)
    table.add_column("层", style="cyan", no_wrap=True)
    table.add_column("名称", style="bold")
    table.add_column("路径")
    table.add_column("状态", no_wrap=True)
    table.add_column("读写", no_wrap=True)
    for layer in layout.layers():
        table.add_row(
            layer.id, layer.title, str(layer.path),
            "[green]存在[/green]" if layer.exists else "[dim]缺失[/dim]",
            "可写" if layer.writable else "只读",
        )
    console.print(table)


def layer_lines(layout: ProjectLayout) -> List[str]:
    """给 `workspace show` / GUI 的缩进树（纯文本）。"""
    lines: List[str] = [f"DESIGN_ROOT: {layout.design_root}", ""]
    for layer in layout.layers():
        mark = "✓" if layer.exists else "·"
        lines.append(f"{layer.id} {mark} {layer.title}: {layer.path}")
        if layer.id == "L2" and layer.exists:
            for name in ("spec", "rtl", "tb", "ecn", "ref", "scripts", "docs"):
                path = layer.path / name
                count = _count_files(path)
                lines.append(f"    {'├──' if name != 'docs' else '└──'} {name}/"
                             + (f"  ({count} files)" if path.is_dir() else "  (缺失)"))
        if layer.id == "L4" and layer.exists:
            lines.extend(f"    · {child.name}" for child in _artifact_children(layer.path))
        if layer.id == "L5" and layer.exists:
            flows = [p.name for p in layer.path.iterdir() if p.is_dir()]
            if flows:
                lines.append("    · flows: " + ", ".join(sorted(flows)))
    return lines


def _count_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def _artifact_children(path: Path) -> List[Path]:
    try:
        return sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))[:24]
    except OSError:
        return []


def print_checks(layout: ProjectLayout) -> int:
    """渲染验收清单；返回 FAIL 数量（CLI 退出码用）。"""
    checks = layout.audit()
    table = Table(title="工程目录验收（CS-DIR-REQ-001 §7）", show_lines=False)
    table.add_column("需求", style="cyan", no_wrap=True)
    table.add_column("检查项")
    table.add_column("状态", no_wrap=True)
    table.add_column("详情")
    for row in checks:
        color = _STATUS_COLOR.get(row["status"], "white")
        table.add_row(row["id"], row["requirement"],
                      f"[{color}]{row['status']}[/{color}]", row["detail"])
    console.print(table)
    failures = sum(1 for row in checks if row["status"] == "FAIL")
    warnings = sum(1 for row in checks if row["status"] == "WARN")
    console.print(f"[dim]FAIL={failures} · WARN={warnings} · PASS={len(checks) - failures - warnings}[/dim]")
    return failures


def print_runs(layout: ProjectLayout) -> None:
    runs = layout.list_runs()
    if not runs:
        console.print("[dim]还没有 run。用 `workspace new-run <top>` 或启动一次验证。[/dim]")
        return
    table = Table(title="运行索引 run_manifest.json")
    table.add_column("run_id", style="cyan", no_wrap=True)
    table.add_column("状态", no_wrap=True)
    table.add_column("top")
    table.add_column("entrypoint")
    table.add_column("started_at")
    table.add_column("目录")
    for run in runs:
        table.add_row(
            str(run.get("run_id") or ""), str(run.get("status") or ""),
            str(run.get("top_module") or ""), str(run.get("entrypoint") or ""),
            str(run.get("started_at") or ""), str(run.get("run_dir") or ""),
        )
    console.print(table)


def print_agents(layout: ProjectLayout, run_id: str = "") -> None:
    from src.agent_plane.domains import all_domains, layout_rows

    run = None
    if run_id:
        run = _find_run(layout, run_id)
        if run is None:
            console.print(f"[red]找不到 run：{run_id}[/red]")
            return
    elif layout.list_runs():
        latest = layout.list_runs()[-1]
        run = layout.open_run(str(latest.get("run_id")), latest.get("top_module"),
                              scope=str(latest.get("scope") or "run"))
    table = Table(title="Agent 产物目录（R-020）")
    table.add_column("Domain", style="cyan")
    table.add_column("Agent")
    table.add_column("产物目录")
    table.add_column("存在", no_wrap=True)
    table.add_column("状态")
    rows = layout_rows(run)
    by_id = {str(row.get("agent_id")): row for row in rows}
    for domain in all_domains():
        for spec in domain.specs():
            row = by_id.get(spec.agent_id, {})
            table.add_row(
                domain.id, spec.agent_id, spec.artifact_dir,
                "[green]是[/green]" if row.get("exists") else "[dim]否[/dim]",
                str(row.get("status") or ""),
            )
    console.print(table)


def _find_run(layout: ProjectLayout, run_id: str):
    for row in layout.list_runs():
        if str(row.get("run_id") or "") == run_id:
            return layout.open_run(run_id, row.get("top_module"),
                                   scope=str(row.get("scope") or "run"))
    return None


def summary_payload(layout: ProjectLayout) -> Dict[str, Any]:
    return layout.summary()


def dump_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


__all__ = [
    "console",
    "load_layout",
    "print_layers",
    "layer_lines",
    "print_checks",
    "print_runs",
    "print_agents",
    "summary_payload",
    "dump_json",
]
