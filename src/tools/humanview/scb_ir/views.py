"""SCB 分解视图：SCB × 格子矩阵 + 契约→类→检查项树 + Markdown。"""
from __future__ import annotations

from typing import Any, Dict

from .ir_core import SCB_CLASSES, SCBDoc
from .validate import build_matrix, scb_status

EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "na": "—"}


def matrix_markdown(doc: SCBDoc) -> str:
    matrix = build_matrix(doc)
    cells = matrix["cells"]
    lines = ["## SCB × 格子", "",
             "| SCB | 契约 | 类 | " + " | ".join(cells) + " | 执行/通过/失败 | 状态 |",
             "|---|---|---|" + "---|" * len(cells) + "---|---|---|"]
    by_id = {s.id: s for s in doc.checks}
    for row in matrix["rows"]:
        s = by_id.get(row["scb"])
        marks = " | ".join(EMOJI.get(row["cells"].get(c, "na"), "?") for c in cells)
        counts = f"{s.execute_count}/{s.pass_count}/{s.fail_count}" if s else "—"
        lines.append(f"| {row['scb']} | {row['contract']} | {row['class']} | "
                     f"{marks} | {counts} | {EMOJI.get(row['status'], '?')} |")
    return "\n".join(lines)


def tree_markdown(doc: SCBDoc) -> str:
    lines = ["## 分解树"]
    by_contract: Dict[str, list] = {}
    for scb in doc.checks:
        by_contract.setdefault(scb.contract or "(未回指契约)", []).append(scb)
    for contract in sorted(by_contract):
        lines.append(f"- **{contract}**")
        by_class: Dict[str, list] = {}
        for scb in by_contract[contract]:
            by_class.setdefault(scb.klass or "?", []).append(scb)
        for klass in sorted(by_class):
            lines.append(f"  - {klass} {SCB_CLASSES.get(klass, '')}")
            for scb in by_class[klass]:
                lines.append(f"    - {scb.id}：{scb.name}（"
                             f"exec={scb.execute_count} pass={scb.pass_count} "
                             f"fail={scb.fail_count}）")
    return "\n".join(lines)


def render_markdown(doc: SCBDoc, validation: Dict[str, Any]) -> str:
    lines = [f"# Scoreboard 分解 IR —— {doc.module or '(未命名模块)'}", "",
             f"- 检查项：{len(doc.checks)}　契约：{len(doc.contracts)}　"
             f"格子：{len(doc.cells)}", ""]
    metrics = validation.get("metrics") or []
    if metrics:
        lines += ["| 度量 | 覆盖 | 总数 | % |", "|---|---|---|---|"]
        lines += [f"| {m['name']} | {m['covered']} | {m['total']} | {m['pct']}% |"
                  for m in metrics]
        lines.append("")
    lines += [matrix_markdown(doc), "", tree_markdown(doc)]
    if validation.get("errors"):
        lines += ["", "## 错误", *[f"- {e}" for e in validation["errors"]]]
    if validation.get("warnings"):
        lines += ["", "## 警告", *[f"- {w}" for w in validation["warnings"]]]
    return "\n".join(lines) + "\n"
