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
_LAYER_LABEL = {key: name for key, name in _LAYER_KEYS}
_STATUS_ORDER = {"red": 3, "yellow": 2, "green": 1, "na": 0}


def _worst_status(statuses) -> str:
    """多值 → 一个展示态：红 > 黄 > 绿 > na。"""
    return max((s or "na" for s in statuses),
               key=lambda s: _STATUS_ORDER.get(s, 0))


def _conclusion_from_layers(layers: Dict[str, str]) -> str:
    if all(v == "green" for v in layers.values()):
        return "已验证"
    reds = [_LAYER_LABEL[k] for k, v in layers.items() if v == "red"]
    yellows = [_LAYER_LABEL[k] for k, v in layers.items() if v == "yellow"]
    if reds:
        return "证据链不完整（" + "、".join(reds) + "）"
    if yellows:
        return "待补（" + "、".join(yellows) + "）"
    return "不适用"


def _group_cases(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """视图1 按**逻辑用例**聚合 —— `data["cases"]` 是执行实例（CASE×TST）。

    同一 CASE 会在多个 seed/轮次下重复出现（`npu_dep_test` 会有几十行），
    那是**执行实例**不是逻辑用例。视图1 回答"哪个逻辑用例有什么证据"，
    所以按 `case_id`（没有 CASE 的批次测试按测试名）归并，并给出执行次数；
    逐实例的账在 EVD 表里。不聚合会让读的人以为数据重复了。
    """
    groups: Dict[str, Dict[str, Any]] = {}
    for c in cases or []:
        case_id = str(c.get("case_id") or "")
        key = case_id or str(c.get("name") or "")
        slot = groups.setdefault(key, {
            "name": key, "kind": "用例" if case_id else "批次",
            "execs": 0, "tests": [],
            "layers": {k: [] for k, _n in _LAYER_KEYS},
        })
        slot["execs"] += 1
        test = str(c.get("name") or "")
        if test and test not in slot["tests"]:
            slot["tests"].append(test)
        for key_layer, _n in _LAYER_KEYS:
            slot["layers"][key_layer].append(
                (c.get(key_layer) or {}).get("status") or "na")
    rows = []
    for key in sorted(groups):
        slot = groups[key]
        layers = {k: _worst_status(v) for k, v in slot["layers"].items()}
        slot["layers"] = layers
        slot["conclusion"] = _conclusion_from_layers(layers)
        slot["tests"] = slot["tests"][:3]
        rows.append(slot)
    return rows


def render_markdown(data: Dict[str, Any]) -> str:
    lines = [f"# Case 证据视图 —— {data.get('run', '')}", ""]
    lines += _render_three_sets(data)
    grouped = _group_cases(data.get("cases") or [])
    lines += [f"## 视图1：用例 × 证据层（{len(grouped)} 个逻辑用例 / "
              f"{len(data.get('cases') or [])} 次执行）", "",
              "| 逻辑用例 | 类型 | 执行 | 功能覆盖 | SVA | Scoreboard | PATH | 结论 |",
              "|---|---|---|---|---|---|---|---|"]
    for c in grouped:
        cells = " | ".join(
            f"{EMOJI.get(c['layers'][k], '?')} {TEXT.get(c['layers'][k], '')}"
            for k, _name in _LAYER_KEYS)
        lines.append(f"| {c.get('name')} | {c.get('kind')} | ×{c.get('execs')} "
                     f"| {cells} | {c.get('conclusion')} |")
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
    lines += _render_v2(data)
    return "\n".join(lines) + "\n"


def _empty_group(key: str) -> Dict[str, Any]:
    return {"group": key, "name": "", "description": "", "coverage_type": "",
            "scope": "", "coverpoints": [], "requirements": [], "checks": [],
            "required_layers": [], "cells": [], "cases": [], "observed": False}


def _merge_group(slot: Dict[str, Any], g: Dict[str, Any], cid: str) -> None:
    for field in ("coverpoints", "requirements", "checks", "required_layers"):
        bucket = slot.setdefault(field, [])
        for v in g.get(field) or []:
            if v and v not in bucket:
                bucket.append(v)
    for field in ("name", "description", "coverage_type", "scope"):
        if not slot.get(field) and g.get(field):
            slot[field] = g[field]
    if g.get("cell") and g["cell"] not in slot["cells"]:
        slot["cells"].append(g["cell"])
    if cid and cid not in slot["cases"]:
        slot["cases"].append(cid)


def _group_rows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """覆盖率组总览：**契约要求的全部组** + 已跑出的证据（observed 标记）。

    只列"跑过的组"会把漏测的组藏起来 —— 签核第一问是"该覆盖哪些组"。
    """
    merged: Dict[str, Dict[str, Any]] = {
        str(g.get("group")): {**g, "observed": False}
        for g in data.get("contract_groups") or [] if g.get("group")}
    for case in data.get("cases") or []:
        cid = case.get("case_id") or case.get("task")
        for g in case.get("groups_evidence") or []:
            key = str(g.get("group") or "")
            if not key:
                continue
            slot = merged.setdefault(key, _empty_group(key))
            slot["observed"] = True
            _merge_group(slot, g, cid)
    return [merged[k] for k in sorted(merged)]


def _render_group_overview(data: Dict[str, Any]) -> List[str]:
    """**覆盖率组总览** —— 这一轮到底必须覆盖哪些组、各测什么。"""
    groups = _group_rows(data)
    if not groups:
        return []
    lines = ["## 覆盖率组总览（必须覆盖什么）", "",
             "| 覆盖率组 | 功能点 | 覆盖类型 | 作用域（模块/逻辑） | 覆盖点 | 需求 | 必需证据层 | 执行证据 | CELL |",
             "|---|---|---|---|---|---|---|---|---|"]
    for g in groups:
        lines.append(
            f"| {g['group']} | {g.get('name') or '—'} | {g.get('coverage_type') or '—'} | "
            f"{g.get('scope') or '—'} | {'、'.join(g['coverpoints']) or '—'} | "
            f"{'、'.join(g['requirements']) or '—'} | "
            f"{' + '.join(g['required_layers']) or '—'} | "
            f"{'有' if g.get('observed') else '**无**'} | "
            f"{'、'.join(g['cells'])} |")
    return lines + [""]


def _render_three_sets(data: Dict[str, Any]) -> List[str]:
    """四节渲染：每条 case 的 [Groups] / [SVA] / [SCB] / [Constraints]。"""
    rows = [c for c in data.get("cases") or [] if c.get("groups_evidence")]
    if not rows:
        return []
    return (_render_group_overview(data)
            + ["## 四集合证据（Groups / SVA / SCB / Constraints）", ""]
            + [line for c in rows for line in _render_one_case(c)])


def _backed_label(value: Any) -> str:
    """backed 的三态：True=是 / False=空骨架 / None=未登记（**不冒充否**）。"""
    if value is True:
        return "是"
    if value is False:
        return "**否（空骨架）**"
    return "未登记"


def _render_constraints(c: Dict[str, Any]) -> List[str]:
    """约束段：id + 是否真编译进模型（backed）+ 负责的维度。"""
    items = [s for s in c.get("constraint_items") or [] if isinstance(s, dict)]
    if not items:
        return ["", "**Constraints（约束）**", "", "（无：该用例的维度没有绑定约束策略）"]
    lines = ["", "**Constraints（约束）**", "",
             "| id | backed | 维度 | 说明 |", "|---|---|---|---|"]
    lines += [f"| {s.get('id')} | {_backed_label(s.get('backed'))} | "
              f"{'、'.join(s.get('dimensions') or []) or '—'} | "
              f"{s.get('reason') or '—'} |" for s in items]
    return lines


def _render_one_case(c: Dict[str, Any]) -> List[str]:
    """一条 case 的 Markdown 四节（Groups / SVA / SCB / Constraints）。"""
    cid = c.get("case_id") or c.get("task")
    lines = [f"### Case: {cid}　`case_status={c.get('case_status') or '—'}`", "",
             "**Groups**", "",
             "| group | 功能点 | 覆盖类型 | 作用域 | cell | functional | timing | data | path | result |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for g in c["groups_evidence"]:
        statuses = [str((g.get(k) or {}).get("status") or "")
                    for k in ("functional", "timing", "data", "path")]
        lines.append(f"| {g.get('group')} | {g.get('name') or '—'} | "
                     f"{g.get('coverage_type') or '—'} | {g.get('scope') or '—'} | "
                     f"{g.get('cell')} | {' | '.join(statuses)} | {g.get('result')} |")
    if c.get("sva_items"):
        lines += ["", "**SVA（断言）**", "",
                  "| id | 名称 | 规则 | cell | fail | cover_property_hit | status |",
                  "|---|---|---|---|---|---|---|"]
        lines += [f"| {s.get('id')} | {s.get('name') or '—'} | `{s.get('expr') or '—'}` | "
                  f"{s.get('cell')} | {s.get('fail')} | {s.get('cover_property_hit')} | "
                  f"{s.get('status')} |" for s in c["sva_items"]]
    if c.get("scb_items"):
        lines += ["", "**SCB（比对）**", "",
                  "| id | 名称 | 说明 | 证据粒度 | cell | exec | matched | mismatched | status |",
                  "|---|---|---|---|---|---|---|---|---|"]
        lines += [f"| {s.get('id')} | {s.get('name') or '—'} | "
                  f"{s.get('description') or '—'} | "
                  f"{s.get('evidence_level') or s.get('evidence_mode') or '—'} | "
                  f"{s.get('cell')} | {s.get('exec')} | {s.get('matched')} | "
                  f"{s.get('mismatched')} | {s.get('status')} |"
                  for s in c["scb_items"]]
    lines += _render_constraints(c)
    return lines + [""]


def _render_v2(data: Dict[str, Any]) -> List[str]:
    """v2 三张新表：分类树 / Case × CELL / 执行证据。空表不出标题。"""
    lines: List[str] = []
    tree = (data.get("case_tree") or {}).get("rows") or []
    if tree:
        lines += ["", "## 视图5：Case 分类树", "",
                  "| 分类 | 名称 | 父级 | 用例数 | 测试数 | 来源 |",
                  "|---|---|---|---|---|---|"]
        for row in tree:
            lines.append(f"| {row.get('id')} | {row.get('name')} | "
                         f"{row.get('parent') or '—'} | {row.get('cases')} | "
                         f"{row.get('tests')} | {row.get('source')} |")
    case_cell = (data.get("case_cell") or {}).get("rows") or []
    if case_cell:
        lines += ["", "## 视图6：Case × CELL", "",
                  "| CELL | CG | P | 颜色 | TP 数 | 声明用例 | 实际用例 |",
                  "|---|---|---|---|---|---|---|"]
        for row in case_cell:
            lines.append(f"| {row.get('cell_id')} | {row.get('cg')} | "
                         f"{row.get('p')} | {EMOJI.get(row.get('color'), '?')} | "
                         f"{row.get('tp_count')} | "
                         f"{'、'.join(row.get('declared_cases') or []) or '—'} | "
                         f"{'、'.join(row.get('observed_cases') or []) or '—'} |")
    runs = data.get("case_runs") or []
    if runs:
        lines += ["", "## 视图7：执行证据（EVD）", "",
                  "| EVD | CASE | TST | 测试 | seed | 阶段 | 波形 | legacy |",
                  "|---|---|---|---|---|---|---|---|"]
        for row in runs:
            lines.append(f"| {row.get('evd_id')} | {row.get('case_id') or '—'} | "
                         f"{row.get('tst_id')} | {row.get('test')} | "
                         f"{row.get('seed')} | {row.get('stage')} | "
                         f"{row.get('wave') or '—'} | "
                         f"{'是' if row.get('legacy') else '否'} |")
    return lines


def _html_table(headers: List[str], rows: List[str]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    return (f"<table><thead><tr>{head}</tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


def _html_plain_table(headers: List[str], rows: List[List[Any]]) -> str:
    """普通表格：单元格转义后原样输出（不做状态着色）。"""
    # `quote=False`：单元格是**文本节点**不是属性，引号无需转义 ——
    # 转义后 `2'd1` 会变成 `2&#x27;d1`，SVA 表达式就没法读了。
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(c), quote=False)}</td>" for c in row)
        + "</tr>" for row in rows)
    return _html_table(headers, [body])


def _html_group_overview(data: Dict[str, Any]) -> str:
    groups = _group_rows(data)
    if not groups:
        return ""
    rows = [[g["group"], g.get("name") or "—", g.get("coverage_type") or "—",
             g.get("scope") or "—",
             "、".join(g["coverpoints"]) or "—",
             "、".join(g["requirements"]) or "—",
             " + ".join(g["required_layers"]) or "—",
             "有" if g.get("observed") else "无",
             "、".join(g["cells"])] for g in groups]
    return ("<h2>覆盖率组总览（必须覆盖什么）</h2>"
            + _html_plain_table(
                ["覆盖率组", "功能点", "覆盖类型", "作用域（模块/逻辑）",
                 "覆盖点", "需求", "必需证据层", "执行证据", "CELL"], rows))


def _html_one_case(c: Dict[str, Any]) -> str:
    """一条 case 的四节 HTML（Groups / SVA / SCB / Constraints）。"""
    cid = c.get("case_id") or c.get("task")
    out: List[str] = [f"<h3>Case: {html.escape(str(cid))} · "
                      f"case_status={html.escape(str(c.get('case_status') or '—'))}</h3>"]
    grows = [[g.get("group"), g.get("name") or "—", g.get("coverage_type") or "—",
              g.get("scope") or "—", g.get("cell"),
              *[str((g.get(k) or {}).get("status") or "")
                for k in ("functional", "timing", "data", "path")],
              g.get("result")] for g in c["groups_evidence"]]
    out.append("<b>Groups</b>" + _html_plain_table(
        ["group", "功能点", "覆盖类型", "作用域", "cell", "functional",
         "timing", "data", "path", "result"], grows))
    srows = [[s.get("id"), s.get("name") or "—", s.get("expr") or "—",
              s.get("cell"), s.get("fail"), s.get("cover_property_hit"),
              s.get("status")] for s in c.get("sva_items") or []]
    if srows:
        out.append("<b>SVA（断言）</b>" + _html_plain_table(
            ["id", "名称", "规则", "cell", "fail",
             "cover_property_hit", "status"], srows))
    crows = [[s.get("id"), s.get("name") or "—", s.get("description") or "—",
              s.get("evidence_level") or s.get("evidence_mode") or "—",
              s.get("cell"), s.get("exec"), s.get("matched"),
              s.get("mismatched"), s.get("status")]
             for s in c.get("scb_items") or []]
    if crows:
        out.append("<b>SCB（比对）</b>" + _html_plain_table(
            ["id", "名称", "说明", "证据粒度", "cell", "exec",
             "matched", "mismatched", "status"], crows))
    out.append(_html_constraints(c))
    return "".join(out)


def _html_constraints(c: Dict[str, Any]) -> str:
    """约束段：id / backed / 维度 / 说明（空骨架必须显式标出）。"""
    items = [s for s in c.get("constraint_items") or [] if isinstance(s, dict)]
    if not items:
        return "<b>Constraints（约束）</b><p>无：该用例的维度没有绑定约束策略</p>"
    return "<b>Constraints（约束）</b>" + _html_plain_table(
        ["id", "backed", "维度", "说明"],
        [[s.get("id"), _backed_label(s.get("backed")).replace("**", ""),
          "、".join(s.get("dimensions") or []) or "—",
          s.get("reason") or "—"] for s in items])


def _html_three_sets(data: Dict[str, Any]) -> str:
    """每条 case 的四节（Groups / SVA / SCB / Constraints）—— 与 Markdown 同口径。"""
    return ("<h2>四集合证据（Groups / SVA / SCB / Constraints）</h2>"
            + "".join(_html_one_case(c) for c in data.get("cases") or []
                      if c.get("groups_evidence")))


def _html_v2(data: Dict[str, Any]) -> str:
    """v2 两张表：Case × CELL 与执行证据（EVD）。"""
    out: List[str] = []
    cell_rows = (data.get("case_cell") or {}).get("rows") or []
    if cell_rows:
        out.append("<h2>Case × CELL</h2>" + _html_plain_table(
            ["CELL", "CG", "P", "颜色", "TP 数", "声明用例", "实际用例"],
            [[r.get("cell_id"), r.get("cg"), r.get("p"), r.get("color"),
              r.get("tp_count"), "、".join(r.get("declared_cases") or []),
              "、".join(r.get("observed_cases") or [])] for r in cell_rows]))
    runs = data.get("case_runs") or []
    if runs:
        # 批次测试没有 CASE/CELL 是**事实**，不是缺数据：如实写"批次"，别用 `—`
        # 让人去猜"是不是忘填了"。
        out.append("<h2>执行证据（EVD）</h2>" + _html_plain_table(
            ["EVD", "CASE", "TST", "测试", "seed", "阶段", "CELL", "legacy"],
            [[r.get("evd_id"), r.get("case_id") or "批次", r.get("tst_id"),
              r.get("test"), r.get("seed"), r.get("stage"),
              "、".join(r.get("cells") or []) or ("—（批次不绑定 CELL）"
                                                   if not r.get("case_id") else "—"),
              "是" if r.get("legacy") else "否"] for r in runs]))
    return "".join(out)


def _html_status(status: str, detail: str = "") -> str:
    color = COLOR.get(status, COLOR["na"])
    text = f"{EMOJI.get(status, '?')} {html.escape(detail)}"
    return f'<td style="background:{color}22;color:{color}">{text}</td>'


def render_html(data: Dict[str, Any]) -> str:
    grouped = _group_cases(data.get("cases") or [])
    cases = "".join(
        "<tr><td><b>" + html.escape(str(c.get("name"))) + "</b></td>"
        f"<td>{html.escape(c.get('kind'))}</td>"
        f"<td>×{c.get('execs')}</td>"
        + "".join(_html_status(c["layers"][k], TEXT.get(c["layers"][k], ""))
                  for k, _n in _LAYER_KEYS)
        + f"<td>{html.escape(str(c.get('conclusion')))}</td></tr>"
        for c in grouped)
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
        f"<h2>视图1：用例 × 证据层（{len(grouped)} 个逻辑用例 / "
        f"{len(data.get('cases') or [])} 次执行）</h2>"
        + _html_table(["逻辑用例", "类型", "执行", "功能覆盖", "SVA",
                       "Scoreboard", "PATH", "结论"], [cases])
        + "<p>按 CASE 聚合（没有 CASE 的批次测试按测试名）；逐执行实例见下方 EVD 表。</p>" +
        "<h2>视图2：功能契约 × 证据层</h2>"
        + _html_table(["Feat", "描述", "功能覆盖", "SVA", "Scoreboard", "PATH", "状态"],
                      [features]) +
        "<h2>视图3：功能组 × 生命周期路径</h2>"
        + _html_table(["路径"] + groups, [mrows]) +
        "<h2>视图4：缺口与豁免</h2>"
        + _html_table(["类型", "项", "根因", "补齐动作", "责任人", "状态"], [gaps])
        + _html_group_overview(data)
        + _html_three_sets(data)
        + _html_v2(data)
        + "</body></html>")


def render_terminal(data: Dict[str, Any]) -> str:
    """纯文本版（不依赖 rich，GUI/CI 日志都能贴）。"""
    grouped = _group_cases(data.get("cases") or [])
    out = [f"Case 证据视图 —— {data.get('run', '')}"]
    out.append(f"\n视图1：用例 × 证据层（{len(grouped)} 个逻辑用例 / "
               f"{len(data.get('cases') or [])} 次执行）")
    for c in grouped:
        marks = " ".join(f"{EMOJI.get(c['layers'][k], '?')}{name}"
                         for k, name in _LAYER_KEYS)
        out.append(f"  {c.get('name'):<36} {c.get('kind')} ×{c.get('execs'):<3} "
                   f"{marks}  {c.get('conclusion')}")
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
