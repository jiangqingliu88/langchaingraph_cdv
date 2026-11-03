"""Case 关联视图的三种呈现 —— 终端 / Markdown / 自包含 HTML。

数据形状见 `builder.build_case_view`（`case_associate_view_v1`）。
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List

EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "na": "—"}
COLOR = {"green": "#2e7d32", "yellow": "#f9a825", "red": "#c62828",
         "na": "#9e9e9e"}
TEXT = {"green": "通过", "yellow": "部分", "red": "缺失", "na": "不适用"}

_LAYER_KEYS = (("coverage", "功能覆盖"), ("sva", "SVA"),
               ("scoreboard", "Scoreboard"), ("path", "PATH"))


def render_markdown(data: Dict[str, Any]) -> str:
    lines = [f"# Case 证据视图 —— {data.get('run', '')}", ""]
    lines += ["## 视图1：用例 × 证据层", "",
              "| 用例 | 功能覆盖 | SVA | Scoreboard | PATH | 结论 |",
              "|---|---|---|---|---|---|"]
    for c in data.get("cases") or []:
        cells = " | ".join(
            f"{EMOJI.get(c[k]['status'], '?')} {c[k]['detail']}"
            for k, _name in _LAYER_KEYS)
        lines.append(f"| {c.get('name')} | {cells} | {c.get('conclusion')} |")
    lines += ["", "## 视图2：功能契约 × 证据层", "",
              "| Feat | 描述 | 功能覆盖 | SVA | Scoreboard | PATH | 状态 |",
              "|---|---|---|---|---|---|---|"]
    for f in data.get("features") or []:
        cells = " | ".join(EMOJI.get(f.get(k), "?") for k, _n in _LAYER_KEYS)
        lines.append(f"| {f.get('id')} | {f.get('desc')} | {cells} | "
                     f"{f.get('status')} |")
    matrix = data.get("matrix") or {}
    groups = matrix.get("groups") or []
    lines += ["", "## 视图3：功能组 × 生命周期路径", "",
              "| 路径 | " + " | ".join(groups) + " |",
              "|---|" + "---|" * len(groups)]
    for row in matrix.get("rows") or []:
        cells = " | ".join(EMOJI.get(row["cells"].get(g, "na"), "?") for g in groups)
        lines.append(f"| {row.get('path')} | {cells} |")
    lines += ["", "## 视图4：缺口与豁免", "",
              "| 类型 | 项 | 根因 | 补齐动作 | 责任人 | 状态 |",
              "|---|---|---|---|---|---|"]
    for g in data.get("gaps") or []:
        lines.append(f"| {g.get('type')} | {g.get('item')} | {g.get('root')} | "
                     f"{g.get('action')} | {g.get('owner')} | {g.get('status')} |")
    return "\n".join(lines) + "\n"


def _html_table(headers: List[str], rows: List[str]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    return (f"<table><thead><tr>{head}</tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


def _html_status(status: str, detail: str = "") -> str:
    color = COLOR.get(status, COLOR["na"])
    text = f"{EMOJI.get(status, '?')} {html.escape(detail)}"
    return f'<td style="background:{color}22;color:{color}">{text}</td>'


def render_html(data: Dict[str, Any]) -> str:
    cases = "".join(
        "<tr><td><b>" + html.escape(str(c.get("name"))) + "</b></td>"
        + "".join(_html_status(c[k]["status"], c[k].get("detail", ""))
                  for k, _n in _LAYER_KEYS)
        + f"<td>{html.escape(str(c.get('conclusion')))}</td></tr>"
        for c in data.get("cases") or [])
    features = "".join(
        "<tr><td>" + html.escape(str(f.get("id"))) + "</td><td>"
        + html.escape(str(f.get("desc"))) + "</td>"
        + "".join(_html_status(f.get(k, "na")) for k, _n in _LAYER_KEYS)
        + f"<td>{html.escape(str(f.get('status')))}</td></tr>"
        for f in data.get("features") or [])
    matrix = data.get("matrix") or {}
    groups = matrix.get("groups") or []
    mrows = "".join(
        "<tr><td>" + html.escape(str(row.get("path"))) + "</td>"
        + "".join(_html_status(row["cells"].get(g, "na")) for g in groups)
        + "</tr>" for row in matrix.get("rows") or [])
    gaps = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(g.get(k, '')))}</td>"
                         for k in ("type", "item", "root", "action", "owner", "status"))
        + "</tr>" for g in data.get("gaps") or [])
    css = ("body{font-family:system-ui,'Microsoft YaHei';margin:24px}"
           "table{border-collapse:collapse;margin:12px 0 28px}"
           "th,td{border:1px solid #ddd;padding:5px 9px;font-size:13px}"
           "th{background:#f5f5f5}h2{margin-top:28px}")
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>Case 证据视图 —— {html.escape(str(data.get('run', '')))}</title>"
        f"<style>{css}</style></head><body>"
        f"<h1>Case 证据视图 —— {html.escape(str(data.get('run', '')))}</h1>"
        "<h2>视图1：用例 × 证据层</h2>"
        + _html_table(["用例", "功能覆盖", "SVA", "Scoreboard", "PATH", "结论"],
                      [cases]) +
        "<h2>视图2：功能契约 × 证据层</h2>"
        + _html_table(["Feat", "描述", "功能覆盖", "SVA", "Scoreboard", "PATH", "状态"],
                      [features]) +
        "<h2>视图3：功能组 × 生命周期路径</h2>"
        + _html_table(["路径"] + groups, [mrows]) +
        "<h2>视图4：缺口与豁免</h2>"
        + _html_table(["类型", "项", "根因", "补齐动作", "责任人", "状态"], [gaps])
        + "</body></html>")


def render_terminal(data: Dict[str, Any]) -> str:
    """纯文本版（不依赖 rich，GUI/CI 日志都能贴）。"""
    out = [f"Case 证据视图 —— {data.get('run', '')}"]
    out.append("\n视图1：用例 × 证据层")
    for c in data.get("cases") or []:
        marks = " ".join(f"{EMOJI.get(c[k]['status'], '?')}{name}"
                         for k, name in _LAYER_KEYS)
        out.append(f"  {c.get('name'):<36} {marks}  {c.get('conclusion')}")
    out.append("\n视图2：功能契约 × 证据层")
    for f in data.get("features") or []:
        marks = " ".join(f"{EMOJI.get(f.get(k), '?')}" for k, _n in _LAYER_KEYS)
        out.append(f"  {f.get('id'):<12} {f.get('desc'):<24} {marks}  {f.get('status')}")
    out.append("\n视图3：功能组 × 生命周期路径")
    matrix = data.get("matrix") or {}
    groups = matrix.get("groups") or []
    out.append("  " + "路径".ljust(30) + " ".join(g[:8].ljust(9) for g in groups))
    for row in matrix.get("rows") or []:
        out.append("  " + str(row.get("path"))[:28].ljust(30)
                   + " ".join(EMOJI.get(row["cells"].get(g, "na"), "?").ljust(9)
                              for g in groups))
    out.append("\n视图4：缺口与豁免")
    for g in data.get("gaps") or []:
        out.append(f"  [{g.get('type')}] {g.get('item')} —— {g.get('root')}"
                   f" → {g.get('action')}（{g.get('owner')} / {g.get('status')}）")
    return "\n".join(out)


def write_reports(data: Dict[str, Any], prefix: str | Path) -> Dict[str, str]:
    """写 `<prefix>.json/.md/.html`，返回路径。"""
    p = Path(prefix)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = {"json": str(p.with_suffix(".json")),
           "markdown": str(p.with_suffix(".md")),
           "html": str(p.with_suffix(".html"))}
    Path(out["json"]).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    Path(out["markdown"]).write_text(render_markdown(data), encoding="utf-8")
    Path(out["html"]).write_text(render_html(data), encoding="utf-8")
    return out
