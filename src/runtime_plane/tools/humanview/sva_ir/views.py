"""SVA 分解视图：SVA × 格子矩阵 + 契约→类→断言分解树 + Markdown。"""
from __future__ import annotations

from typing import Any, Dict

from .ir_core import SVA_CLASSES, SVADoc
from .validate import build_matrix, sva_status

EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "na": "—"}


def matrix_markdown(doc: SVADoc) -> str:
    matrix = build_matrix(doc)
    cells = matrix["cells"]
    lines = ["## SVA × 格子", "",
             "| SVA | 契约 | 类 | " + " | ".join(cells) + " | 状态 |",
             "|---|---|---|" + "---|" * len(cells) + "---|"]
    for row in matrix["rows"]:
        marks = " | ".join(EMOJI.get(row["cells"].get(c, "na"), "?") for c in cells)
        lines.append(f"| {row['sva']} | {row['contract']} | {row['class']} | "
                     f"{marks} | {EMOJI.get(row['status'], '?')} |")
    return "\n".join(lines)


def tree_markdown(doc: SVADoc) -> str:
    """契约 → 类 → SVA 的分解树（缩进列表，评审可以直接看漏了哪条契约）。"""
    lines = ["## 分解树"]
    by_contract: Dict[str, list] = {}
    for sva in doc.svas:
        by_contract.setdefault(sva.contract or "(未回指契约)", []).append(sva)
    for contract in sorted(by_contract):
        lines.append(f"- **{contract}**")
        by_class: Dict[str, list] = {}
        for sva in by_contract[contract]:
            by_class.setdefault(sva.klass or "?", []).append(sva)
        for klass in sorted(by_class):
            lines.append(f"  - {klass} {SVA_CLASSES.get(klass, '')}")
            for sva in by_class[klass]:
                lines.append(f"    - {sva.id}：{sva.name} "
                             f"（hit={sva.hit_count} fail={sva.fail_count}）")
    return "\n".join(lines)


def render_markdown(doc: SVADoc, validation: Dict[str, Any]) -> str:
    lines = [f"# SVA 分解 IR —— {doc.module or '(未命名模块)'}", "",
             f"- 断言：{len(doc.svas)}　契约：{len(doc.contracts)}　"
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
