"""covg_ir 的视图 —— 纵横矩阵 / 路径清单 / 需求追溯（Markdown 人读）。"""
from __future__ import annotations

from typing import Any, Dict, List

from .ir_core import CovgIR
from .validate import build_matrix

EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "na": "—"}


def matrix_markdown(ir: CovgIR) -> str:
    matrix = build_matrix(ir)
    groups = matrix["groups"]
    lines = ["## 功能组 × 生命周期路径", "",
             "| 路径 | " + " | ".join(groups) + " |",
             "|---|" + "---|" * len(groups)]
    for row in matrix["rows"]:
        cells = " | ".join(EMOJI.get(row["cells"].get(g, "na"), "?")
                           for g in groups)
        lines.append(f"| {row['path']} | {cells} |")
    counts = matrix["counts"]
    lines += ["", f"格子：🟢 {counts['green']} / 🟡 {counts['yellow']} / "
                  f"🔴 {counts['red']} / — {counts['na']}"]
    return "\n".join(lines)


def paths_markdown(ir: CovgIR) -> str:
    lines = ["## 生命周期路径", "",
             "| 路径 | 阶段 | SVA | SCB | 定向序列 | 状态 |",
             "|---|---|---|---|---|---|"]
    for path in ir.paths:
        stages = " → ".join(
            (s.get("name") or s.get("id") or str(s)) if isinstance(s, dict) else str(s)
            for s in path.stages)
        lines.append(f"| {path.id} | {stages} | "
                     f"{'、'.join(path.bound_sva) or '—'} | "
                     f"{'、'.join(path.bound_scoreboard) or '—'} | "
                     f"{'、'.join(path.directed_seq) or '—'} | {path.status} |")
    return "\n".join(lines)


def traceability_markdown(ir: CovgIR, trace: Dict[str, Any]) -> str:
    lines = ["## 需求追溯", "",
             "| Feat | 功能组 | 路径 |", "|---|---|---|"]
    for feat in trace.get("feats") or []:
        groups = [g.id for g in ir.covergroups if feat in g.requirements]
        paths = [p.id for p in ir.paths if feat in p.feats]
        lines.append(f"| {feat} | {'、'.join(groups) or '—'} | "
                     f"{'、'.join(paths) or '—'} |")
    if trace.get("orphan_feats"):
        lines += ["", f"孤立需求：{'、'.join(trace['orphan_feats'])}"]
    if trace.get("orphan_coverpoints"):
        lines += ["", f"孤立覆盖点：{'、'.join(trace['orphan_coverpoints'][:20])}"]
    return "\n".join(lines)


def render_markdown(ir: CovgIR, validation: Dict[str, Any]) -> str:
    metrics = validation.get("metrics") or []
    lines = [f"# 功能覆盖率 IR —— {ir.module or '(未命名模块)'}", "",
             f"- 功能组：{len(ir.covergroups)}　路径：{len(ir.paths)}　"
             f"跨组交叉：{len(ir.crosses)}", ""]
    if metrics:
        lines.append("| 度量 | 覆盖 | 总数 | % |")
        lines.append("|---|---|---|---|")
        for m in metrics:
            lines.append(f"| {m['name']} | {m['covered']} | {m['total']} | "
                         f"{m['pct']}% |")
        lines.append("")
    lines.append(matrix_markdown(ir))
    lines.append("")
    lines.append(paths_markdown(ir))
    lines.append("")
    lines.append(traceability_markdown(
        ir, (validation.get("details") or {}).get("traceability") or {}))
    if validation.get("errors"):
        lines += ["", "## 错误", *[f"- {e}" for e in validation["errors"]]]
    if validation.get("warnings"):
        lines += ["", "## 警告", *[f"- {w}" for w in validation["warnings"]]]
    return "\n".join(lines) + "\n"
