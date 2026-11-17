下面是一个可直接运行的 Python 脚本，把你前面讨论的“四层证据链”做成**人类可读**的视图：终端彩色表、Markdown 表、自包含 HTML 热力图。数据用一个 JSON 文件描述，既支持手工维护，也支持后续从 `urg` 报告和仿真日志自动生成。

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cmdsched_evidence_view.py
CMD_SCH 用例证据人类可读视图生成器

四张视图：
  视图1 用例 × 证据层矩阵      —— 哪个用例提供了哪层证据
  视图2 功能契约 × 证据层热力图 —— 哪个 Feat 的证据链还缺
  视图3 功能组 × 生命周期路径   —— 哪个功能在哪条路径上证据不足
  视图4 缺口与豁免看板         —— 缺口怎么补、豁免有没有记录

用法：
  python3 cmdsched_evidence_view.py --input evidence.json --format all --out ./evidence_report
  python3 cmdsched_evidence_view.py                    # 用内置示例数据跑通
"""
import argparse
import html
import json
import os
import sys
import unicodedata
from pathlib import Path

# ---------- 状态 -> 展示映射 ----------
STATUS_COLOR = {"green": "\033[92m", "yellow": "\033[93m", "red": "\033[91m", "na": "\033[90m"}
STATUS_RESET = "\033[0m"
STATUS_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "na": "—"}
STATUS_HTML = {"green": "#2e7d32", "yellow": "#f9a825", "red": "#c62828", "na": "#9e9e9e"}
STATUS_TEXT = {"green": "通过", "yellow": "部分", "red": "缺失", "na": "不适用"}

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def colorize(text: str, status: str) -> str:
    if not USE_COLOR:
        return text
    return f"{STATUS_COLOR.get(status, '')}{text}{STATUS_RESET}"


def dwidth(s: str) -> int:
    """中文按 2 宽度计算，用于终端对齐。"""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def pad(s: str, width: int, align: str = "left") -> str:
    gap = max(0, width - dwidth(s))
    return (" " * gap + s) if align == "right" else (s + " " * gap)


# ---------- 数据加载 ----------
def load_data(path: str | None) -> dict:
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return DEMO


# ---------- 视图1：用例 × 证据层矩阵 ----------
def view1_rows(data: dict) -> list[dict]:
    return data["cases"]


def render_view1_terminal(data: dict):
    cols = [("用例", 26), ("功能覆盖", 12), ("SVA", 12), ("Scoreboard", 14), ("PATH", 16), ("结论", 16)]
    print("\n" + colorize("视图1：用例 × 证据层矩阵", "green"))
    print("-" * 100)
    print("".join(pad(c, w) for c, w in cols))
    for c in view1_rows(data):
        row = [
            pad(c["name"], 26),
            colorize(pad(STATUS_EMOJI[c["coverage"]["status"]], 12), c["coverage"]["status"]),
            colorize(pad(STATUS_EMOJI[c["sva"]["status"]], 12), c["sva"]["status"]),
            colorize(pad(STATUS_EMOJI[c["scoreboard"]["status"]], 14), c["scoreboard"]["status"]),
            colorize(pad(STATUS_EMOJI[c["path"]["status"]], 16), c["path"]["status"]),
            c["conclusion"],
        ]
        print("".join(row))
    print("-" * 100)


def render_view1_markdown(data: dict) -> str:
    lines = ["### 视图1：用例 × 证据层矩阵", "",
             "| 用例 | 功能覆盖 | SVA | Scoreboard | PATH | 结论 |",
             "|---|---|---|---|---|---|"]
    for c in view1_rows(data):
        lines.append(
            f"| {c['name']} | {STATUS_EMOJI[c['coverage']['status']]} {c['coverage']['detail']} "
            f"| {STATUS_EMOJI[c['sva']['status']]} {c['sva']['detail']} "
            f"| {STATUS_EMOJI[c['scoreboard']['status']]} {c['scoreboard']['detail']} "
            f"| {STATUS_EMOJI[c['path']['status']]} {c['path']['detail']} "
            f"| {c['conclusion']} |")
    return "\n".join(lines)


def render_view1_html(data: dict) -> str:
    rows = ""
    for c in view1_rows(data):
        cells = "".join(
            f'<td style="background:{STATUS_HTML[c[k]["status"]]}33;color:{STATUS_HTML[c[k]["status"]]}">'
            f'{STATUS_EMOJI[c[k]["status"]]} {html.escape(c[k]["detail"])}</td>'
            for k in ("coverage", "sva", "scoreboard", "path"))
        rows += f"<tr><td><b>{html.escape(c['name'])}</b></td>{cells}<td>{html.escape(c['conclusion'])}</td></tr>"
    return f"""<section><h2>视图1：用例 × 证据层矩阵</h2>
<table><thead><tr><th>用例</th><th>功能覆盖</th><th>SVA</th><th>Scoreboard</th><th>PATH</th><th>结论</th></tr></thead>
<tbody>{rows}</tbody></table></section>"""


# ---------- 视图2：功能契约 × 证据层热力图 ----------
def render_view2_terminal(data: dict):
    cols = [("Feat", 8), ("描述", 24), ("功能覆盖", 10), ("SVA", 10), ("SB", 10), ("PATH", 10), ("状态", 22)]
    print("\n" + colorize("视图2：功能契约 × 证据层热力图", "green"))
    print("-" * 100)
    print("".join(pad(c, w) for c, w in cols))
    for f in data["features"]:
        print(
            pad(f["id"], 8) + pad(f["desc"], 24)
            + colorize(pad(STATUS_EMOJI[f["coverage"]], 10), f["coverage"])
            + colorize(pad(STATUS_EMOJI[f["sva"]], 10), f["sva"])
            + colorize(pad(STATUS_EMOJI[f["scoreboard"]], 10), f["scoreboard"])
            + colorize(pad(STATUS_EMOJI[f["path"]], 10), f["path"])
            + f["status"])
    print("-" * 100)


def render_view2_markdown(data: dict) -> str:
    lines = ["### 视图2：功能契约 × 证据层热力图", "",
             "| Feat | 描述 | 功能覆盖 | SVA | Scoreboard | PATH | 状态 |",
             "|---|---|---|---|---|---|---|"]
    for f in data["features"]:
        lines.append(
            f"| {f['id']} | {f['desc']} | {STATUS_EMOJI[f['coverage']]} "
            f"| {STATUS_EMOJI[f['sva']]} | {STATUS_EMOJI[f['scoreboard']]} "
            f"| {STATUS_EMOJI[f['path']]} | {f['status']} |")
    return "\n".join(lines)


def render_view2_html(data: dict) -> str:
    rows = ""
    for f in data["features"]:
        cells = "".join(
            f'<td style="background:{STATUS_HTML[f[k]]}33;color:{STATUS_HTML[f[k]]}">{STATUS_EMOJI[f[k]]}</td>'
            for k in ("coverage", "sva", "scoreboard", "path"))
        rows += f"<tr><td>{html.escape(f['id'])}</td><td>{html.escape(f['desc'])}</td>{cells}<td>{html.escape(f['status'])}</td></tr>"
    return f"""<section><h2>视图2：功能契约 × 证据层热力图</h2>
<table><thead><tr><th>Feat</th><th>描述</th><th>功能覆盖</th><th>SVA</th><th>Scoreboard</th><th>PATH</th><th>状态</th></tr></thead>
<tbody>{rows}</tbody></table></section>"""


# ---------- 视图3：功能组 × 生命周期路径 ----------
def render_view3_terminal(data: dict):
    groups = data["matrix"]["groups"]
    print("\n" + colorize("视图3：功能组 × 生命周期路径", "green"))
    print("-" * 100)
    print(pad("路径", 22) + "".join(pad(g, 8) for g in groups))
    for row in data["matrix"]["rows"]:
        line = pad(row["path"], 22)
        for g in groups:
            st = row["cells"].get(g, "na")
            line += colorize(pad(STATUS_EMOJI[st], 8), st)
        print(line)
    print("-" * 100)


def render_view3_markdown(data: dict) -> str:
    groups = data["matrix"]["groups"]
    lines = ["### 视图3：功能组 × 生命周期路径", "",
             "| 路径 | " + " | ".join(groups) + " |",
             "|---|" + "---|" * len(groups)]
    for row in data["matrix"]["rows"]:
        lines.append("| " + row["path"] + " | " +
                     " | ".join(STATUS_EMOJI[row["cells"].get(g, "na")] for g in groups) + " |")
    return "\n".join(lines)


def render_view3_html(data: dict) -> str:
    groups = data["matrix"]["groups"]
    head = "<th>路径</th>" + "".join(f"<th>{html.escape(g)}</th>" for g in groups)
    body = ""
    for row in data["matrix"]["rows"]:
        cells = "".join(
            f'<td style="background:{STATUS_HTML[row["cells"].get(g, "na")]}33;'
            f'color:{STATUS_HTML[row["cells"].get(g, "na")]}">{STATUS_EMOJI[row["cells"].get(g, "na")]}</td>'
            for g in groups)
        body += f"<tr><td>{html.escape(row['path'])}</td>{cells}</tr>"
    return f"""<section><h2>视图3：功能组 × 生命周期路径</h2>
<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></section>"""


# ---------- 视图4：缺口与豁免看板 ----------
def render_view4_terminal(data: dict):
    cols = [("类型", 10), ("项", 22), ("根因", 26), ("补齐动作", 26), ("责任人", 10), ("状态", 10)]
    print("\n" + colorize("视图4：缺口与豁免看板", "green"))
    print("-" * 110)
    print("".join(pad(c, w) for c, w in cols))
    for g in data["gaps"]:
        st = "green" if g["status"] == "已关闭" else ("yellow" if g["status"] == "进行中" else "red")
        print(pad(g["type"], 10) + pad(g["item"], 22) + pad(g["root"], 26)
              + pad(g["action"], 26) + pad(g["owner"], 10) + colorize(g["status"], st))
    print("-" * 110)


def render_view4_markdown(data: dict) -> str:
    lines = ["### 视图4：缺口与豁免看板", "",
             "| 类型 | 项 | 根因 | 补齐动作 | 责任人 | 状态 |",
             "|---|---|---|---|---|---|"]
    for g in data["gaps"]:
        lines.append(f"| {g['type']} | {g['item']} | {g['root']} | {g['action']} | {g['owner']} | {g['status']} |")
    return "\n".join(lines)


def render_view4_html(data: dict) -> str:
    rows = ""
    for g in data["gaps"]:
        st = "green" if g["status"] == "已关闭" else ("yellow" if g["status"] == "进行中" else "red")
        rows += (f"<tr><td>{html.escape(g['type'])}</td><td>{html.escape(g['item'])}</td>"
                 f"<td>{html.escape(g['root'])}</td><td>{html.escape(g['action'])}</td>"
                 f"<td>{html.escape(g['owner'])}</td>"
                 f"<td style='color:{STATUS_HTML[st]}'>{html.escape(g['status'])}</td></tr>")
    return f"""<section><h2>视图4：缺口与豁免看板</h2>
<table><thead><tr><th>类型</th><th>项</th><th>根因</th><th>补齐动作</th><th>责任人</th><th>状态</th></tr></thead>
<tbody>{rows}</tbody></table></section>"""


# ---------- 输出驱动 ----------
def render_terminal(data: dict):
    print(f"\n{'='*40} CMD_SCH 用例证据视图  {data.get('generated_at','')}  {'='*40}")
    render_view1_terminal(data)
    render_view2_terminal(data)
    render_view3_terminal(data)
    render_view4_terminal(data)


def render_markdown(data: dict, out_path: str):
    parts = [f"# CMD_SCH 用例证据视图（{data.get('generated_at','')}）", ""]
    parts += [render_view1_markdown(data), "", render_view2_markdown(data), "",
              render_view3_markdown(data), "", render_view4_markdown(data)]
    Path(out_path).write_text("\n".join(parts), encoding="utf-8")
    print(f"[markdown] 已生成 {out_path}")


HTML_CSS = """
body{font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;margin:24px;color:#222}
h1{border-bottom:2px solid #333;padding-bottom:8px}
h2{margin-top:32px;border-left:4px solid #1976d2;padding-left:8px}
table{border-collapse:collapse;margin:12px 0;font-size:13px}
th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}
th{background:#f5f5f5}
tr:nth-child(even){background:#fafafa}
.legend span{display:inline-block;margin-right:16px}
"""


def render_html(data: dict, out_path: str):
    legend = ('<div class="legend">'
              + "".join(f'<span style="color:{STATUS_HTML[k]}">■ {STATUS_TEXT[k]}</span>'
                        for k in ("green", "yellow", "red", "na"))
              + '</div>')
    body = (render_view1_html(data) + render_view2_html(data)
            + render_view3_html(data) + render_view4_html(data))
    doc = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>CMD_SCH 用例证据视图</title><style>{HTML_CSS}</style></head><body>
<h1>CMD_SCH 用例证据视图（{html.escape(data.get('generated_at',''))}）</h1>
{legend}{body}</body></html>"""
    Path(out_path).write_text(doc, encoding="utf-8")
    print(f"[html]     已生成 {out_path}")


# ---------- 内置示例数据 ----------
DEMO = {
    "generated_at": "2026-11-03",
    "cases": [
        {"name": "cmdsched_basic_test", "feats": ["Feat-1"], "desc": "直发到 done/rls",
         "coverage": {"status": "green", "detail": "cp_issue_path.direct"},
         "sva": {"status": "green", "detail": "start/done/rls inst_id 匹配"},
         "scoreboard": {"status": "green", "detail": "资源占用释放"},
         "path": {"status": "green", "detail": "P_DIRECT_FULL"}, "conclusion": "已验证"},
        {"name": "cmdsched_dep_test", "feats": ["Feat-19"], "desc": "RAW 存 ISTB 后发射",
         "coverage": {"status": "green", "detail": "raw_stored"},
         "sva": {"status": "green", "detail": "依赖未解除不 start"},
         "scoreboard": {"status": "green", "detail": "依赖顺序"},
         "path": {"status": "green", "detail": "P_STORED_ISSUED"}, "conclusion": "已验证"},
        {"name": "cmdsched_instb_test", "feats": ["Feat-19"], "desc": "满反压恢复",
         "coverage": {"status": "green", "detail": "full/backpressure"},
         "sva": {"status": "green", "detail": "cmd_ready 反压保持"},
         "scoreboard": {"status": "green", "detail": "不丢不重"},
         "path": {"status": "yellow", "detail": "P_BP_RECOVER 未命中 refill"},
         "conclusion": "待补 PATH 种子"},
        {"name": "cmdsched_rsp_test", "feats": ["Feat-20"], "desc": "多 xd=1 乱序返回",
         "coverage": {"status": "green", "detail": "tag_ooot/multi_xd"},
         "sva": {"status": "green", "detail": "rsp 反压保持 tag/data"},
         "scoreboard": {"status": "green", "detail": "按 tag 比对"},
         "path": {"status": "green", "detail": "P_OOO_RSP"}, "conclusion": "已验证"},
        {"name": "cmdsched_illegal_test", "feats": ["Feat-28"], "desc": "非法指令中断恢复",
         "coverage": {"status": "green", "detail": "cmd_int0"},
         "sva": {"status": "yellow", "detail": "block_en=0 屏蔽未断言"},
         "scoreboard": {"status": "green", "detail": "现场保存"},
         "path": {"status": "green", "detail": "P_ILLEGAL_BLOCK"}, "conclusion": "待补屏蔽 SVA"},
        {"name": "cmdsched_third_inst_test", "feats": ["Feat-10"], "desc": "第三条同组件阻塞",
         "coverage": {"status": "green", "detail": "third_blocked"},
         "sva": {"status": "green", "detail": "双槽占满不 start"},
         "scoreboard": {"status": "yellow", "detail": "槽位 inst_id 未比对"},
         "path": {"status": "green", "detail": "P_THIRD_BLOCK"}, "conclusion": "待补槽位比对"},
        {"name": "cmdsched_rmw_test", "feats": ["Feat-4"], "desc": "wr_lmem 读改写",
         "coverage": {"status": "green", "detail": "rmw_performed"},
         "sva": {"status": "green", "detail": "RMW 时序"},
         "scoreboard": {"status": "green", "detail": "先读后写回数据"},
         "path": {"status": "green", "detail": "P_RMW"}, "conclusion": "已验证"},
    ],
    "features": [
        {"id": "Feat-1", "desc": "组件配置启动", "coverage": "green", "sva": "green", "scoreboard": "green", "path": "green", "status": "可签核"},
        {"id": "Feat-4", "desc": "CPU 读写 LMEM", "coverage": "green", "sva": "green", "scoreboard": "green", "path": "green", "status": "可签核"},
        {"id": "Feat-10", "desc": "同组件双指令", "coverage": "green", "sva": "green", "scoreboard": "yellow", "path": "green", "status": "待补槽位比对"},
        {"id": "Feat-19", "desc": "乱序发射窗口", "coverage": "green", "sva": "green", "scoreboard": "green", "path": "yellow", "status": "待补反压恢复 PATH"},
        {"id": "Feat-20", "desc": "多 xd=1 乱序返回", "coverage": "green", "sva": "green", "scoreboard": "green", "path": "green", "status": "可签核"},
        {"id": "Feat-28", "desc": "异常指令中断", "coverage": "green", "sva": "yellow", "scoreboard": "green", "path": "green", "status": "待补屏蔽 SVA"},
        {"id": "Feat-30", "desc": "lmem 与 LLSU 并发", "coverage": "green", "sva": "red", "scoreboard": "yellow", "path": "red", "status": "证据链不完整"},
    ],
    "matrix": {
        "groups": ["ITYPE", "INSTB", "DEP", "ISSUE", "UNIT", "MEM", "RSP", "EXCP"],
        "rows": [
            {"path": "直发到 done", "cells": {"ITYPE": "green", "DEP": "green", "ISSUE": "green", "UNIT": "green", "MEM": "green"}},
            {"path": "存 ISTB 后发射", "cells": {"ITYPE": "green", "INSTB": "green", "DEP": "green", "ISSUE": "green", "UNIT": "green", "MEM": "green"}},
            {"path": "ISTB 满反压恢复", "cells": {"INSTB": "green", "ISSUE": "green", "MEM": "green", "RSP": "yellow"}},
            {"path": "多 xd=1 乱序返回", "cells": {"ITYPE": "green", "RSP": "green"}},
            {"path": "非法指令中断恢复", "cells": {"ITYPE": "green", "EXCP": "yellow"}},
        ],
    },
    "gaps": [
        {"type": "未命中 bin", "item": "P_BP_RECOVER", "root": "反压后 refill 种子不足",
         "action": "加 instb_fill_seq 定向种子", "owner": "刘江清", "status": "进行中"},
        {"type": "证据缺失", "item": "Feat-30 scoreboard", "root": "未比对 lmem/LLSU 并发资源",
         "action": "补 scoreboard 检查项", "owner": "待分配", "status": "未开始"},
        {"type": "证据缺失", "item": "Feat-28 block SVA", "root": "excep_en=0 屏蔽行为未断言",
         "action": "补 SVA", "owner": "待分配", "status": "未开始"},
        {"type": "豁免", "item": "excl_cfg", "root": "架构暂不支持独占 SPAD",
         "action": "已审批并记录理由", "owner": "验证负责人", "status": "已关闭"},
    ],
}


def main():
    ap = argparse.ArgumentParser(description="CMD_SCH 用例证据人类可读视图生成器")
    ap.add_argument("--input", default=None, help="evidence JSON，缺省用内置示例")
    ap.add_argument("--format", default="all", choices=["terminal", "markdown", "html", "all"])
    ap.add_argument("--out", default="./evidence_report", help="markdown/html 输出前缀")
    args = ap.parse_args()

    data = load_data(args.input)
    if args.format in ("terminal", "all"):
        render_terminal(data)
    if args.format in ("markdown", "all"):
        render_markdown(data, args.out + ".md")
    if args.format in ("html", "all"):
        render_html(data, args.out + ".html")


if __name__ == "__main__":
    main()
```

运行方式：

```bash
python3 cmdsched_evidence_view.py
# 或
python3 cmdsched_evidence_view.py --input evidence.json --format all --out ./evidence_report
```

生成内容：

- 终端：四张彩色表，🟢🟡🔴 一眼看出证据完整度；
- `evidence_report.md`：可直接贴进评审文档或飞书；
- `evidence_report.html`：自包含热力图，挂到 nightly 报告。

Markdown 输出大致长这样：

```markdown
### 视图1：用例 × 证据层矩阵

| 用例 | 功能覆盖 | SVA | Scoreboard | PATH | 结论 |
|---|---|---|---|---|---|
| cmdsched_basic_test | 🟢 cp_issue_path.direct | 🟢 start/done/rls inst_id 匹配 | 🟢 资源占用释放 | 🟢 P_DIRECT_FULL | 已验证 |
| cmdsched_instb_test | 🟢 full/backpressure | 🟢 cmd_ready 反压保持 | 🟢 不丢不重 | 🟡 P_BP_RECOVER 未命中 refill | 待补 PATH 种子 |
| cmdsched_rsp_test | 🟢 tag_ooot/multi_xd | 🟢 rsp 反压保持 tag/data | 🟢 按 tag 比对 | 🟢 P_OOO_RSP | 已验证 |

### 视图2：功能契约 × 证据层热力图

| Feat | 描述 | 功能覆盖 | SVA | Scoreboard | PATH | 状态 |
|---|---|---|---|---|---|---|
| Feat-19 | 乱序发射窗口 | 🟢 | 🟢 | 🟢 | 🟡 | 待补反压恢复 PATH |
| Feat-30 | lmem 与 LLSU 并发 | 🟢 | 🔴 | 🟡 | 🔴 | 证据链不完整 |
```

**接入真实数据**时，不需要改脚本，只改 JSON 生成逻辑：

- 功能覆盖：解析 `urg` 的 group/bin 文本报告，命中 green、部分 yellow；
- SVA：解析仿真日志里 `assert`/`SVA` 统计，0 fail 且触发过 green，未触发 yellow，fail red；
- Scoreboard：解析 scoreboard 比对日志的 pass/fail/missing；
- PATH：解析 PATH 组序列 coverpoint 命中，且绑定 SVA/scoreboard pass 才 green。

这样评审问“每组 100% 怎么证明路径通”，你直接打开 `evidence_report.html`，视图 1 看用例证据、视图 2 看需求证据链、视图 3 看路径与功能组交叉、视图 4 看缺口和豁免，**四张表替代口头解释**。



结论：**作为“用例验证完备性的判定框架”，方向是对的，四层证据链解决了“bin 命中 ≠ 功能验证”这个核心问题；但作为完整的“用例覆盖方法学”，还不完善，缺的是“用例集合怎么保证充分、用例粒度怎么对齐、用例之间冗余和缺口怎么管理、用例怎么驱动回归选择”这几块。**

分点说清楚。

---

### 一、已经完善的部分：判定框架成立

你现在这套方法解决了三个关键问题：

1. **判定标准明确**：一个功能契约要被判定为验证完成，必须同时具备功能覆盖、SVA、scoreboard、PATH 四层证据，而不是只看 bin 命中率。
2. **证据可追溯**：用例 × 证据矩阵把“哪个用例提供了哪层证据”显式化，评审可审计。
3. **缺口可管理**：视图 4 把“未命中 bin”“证据缺失”“豁免”分开记录，避免用覆盖率数字掩盖证据缺口。

这三条是很多覆盖率计划里缺失的，你已经补上了。

---

### 二、还不完善的部分：用例覆盖方法学缺五块

#### 1. 用例集合的“充分性”没有形式化准则（事前 vs 事后）

现在的四层证据链是**事后判定**：用例跑完了，看证据全不全。但**事前怎么保证用例集合本身充分**，没有明确准则。比如：
- 每个 Feat 至少需要几个用例？正向、边界、异常各几个？
- 每个功能组的分支是否都有对应用例？
- 每个反压源、每个异常类型、每个配置组合是否都有用例？
- 用例集合的最小充分集怎么定义？

缺一个 **“用例充分性准则”**，比如：

| 覆盖对象 | 充分性准则 |
|---|---|
| 每个 Feat | ≥1 正向用例 + ≥1 边界/反压用例 |
| 每个功能组的分支 bin | ≥1 用例命中 |
| 每个异常类型（cmd_int0/cmd_int1） | ≥1 定向用例 |
| 每个反压源（rd/wr/scalar/istb） | ≥1 用例 |
| 每个 CSR 配置组合 | ≥1 用例 |
| 每条主路径（PATH 组） | ≥1 端到端用例 |

没有这个准则，用例集合是否充分只能靠评审拍脑袋。

#### 2. 用例粒度与覆盖目标的对齐不够清晰

用例现在混在一起：`basic_test` 是单指令级，`raw_chain_seq` 是序列级，`illegal_seq` 是场景级，`random_mix_test` 是系统级。但**什么覆盖目标该用什么粒度的用例**，没有明确规则。方法学上应该定义：

| 用例粒度 | 对准的覆盖目标 | 典型用例 |
|---|---|---|
| 单指令级 | 单点功能 bin（ITYPE/UNIT/CSR） | `basic_test`、`instype_test` |
| 序列级 | 依赖、组合、槽位交叉 | `dep_test`、`hazard_scope_test`、`parallel_test` |
| 场景级 | 路径、反压、异常、乱序 | `instb_fill`、`xd1_seq`、`illegal_seq` |
| 系统级 | 端到端混合、防过拟合 | `random_mix_test` |

粒度不对齐，会出现“单指令用例去补路径 bin”或“场景用例去补单点 bin”的浪费。

#### 3. 状态机/时序覆盖没有独立建模

现在的覆盖点主要是“功能点 + 路径”，但 CMD_SCH 里有多个**状态机**：ISTB 链表状态、scoreboard 的 hazard 状态、反压 FSM、rsp_fifo 出队状态、中断 block 状态。这些状态机的**状态覆盖和状态转移覆盖**没有独立 coverpoint。路径覆盖只能近似，不能替代状态机覆盖。

方法学上应该补：
- 每个关键 FSM 的状态 coverpoint + 状态转移 coverpoint；
- 状态机的非法状态/非法转移用 `illegal_bins` 或 SVA 卡住；
- 状态机覆盖与 PATH 组交叉，验证“状态转移正确”而不只是“路径走完”。

#### 4. 异常/负向用例的覆盖完整性缺乏系统方法

现在异常用例是零散的：`illegal_seq`、`cimc_lmem_addr`、`lmem_llsu_conflict`。但**错误注入的种类、时机、组合**没有矩阵化。方法学上应该有一个 **错误注入矩阵**：

| 错误类型 | 注入时机 | 预期行为 | 对应用例 | 检查项 |
|---|---|---|---|---|
| 非法编码 | 指令下发 | cmd_int0 + block | `illegal_seq` | SVA + 现场保存 |
| 非 SPAD 地址 | 地址译码 | cmd_int0 | `illegal_seq` | scoreboard |
| CIMC 地址给 lmem | 发射前 | cmd_int1 | `illegal_seq` | SVA |
| 反压中复位 | 握手 | 不丢不重 | `bp_seq` | SVA |
| 中断中再中断 | block 期间 | 现场不覆盖 | `int_info_seq` | scoreboard |

没有这个矩阵，异常覆盖是否完整无法判定。

#### 5. 用例与随机回归的协同没有准则

定向用例补主路径和长尾，随机回归防过拟合和探索组合，但**两者的边界和切换条件**没有明确。方法学上应该定义：
- 定向用例负责：每个 Feat 的主路径、每个异常类型、每个反压源、每条 PATH；
- 随机回归负责：组合空间探索、防过拟合、种子基线稳定性；
- 切换条件：当定向用例覆盖的功能 bin 达到 100%、PATH 组达到 100% 后，随机回归只负责维持覆盖率和发现新组合，不再新增定向用例；
- 回归选择：用“用例对覆盖率缺口的贡献”做回归用例选择（regression selection），而不是全量跑。

#### 6. 用例覆盖的度量缺失

现在有功能覆盖率度量，但没有**用例覆盖率度量**：
- 用例对 Feat 的覆盖矩阵（每个 Feat 被几个用例覆盖）；
- 用例对 PATH 的覆盖矩阵；
- 用例对 bin 的贡献度（哪个用例贡献了哪些 bin）；
- 用例冗余度（两个用例覆盖的 bin 重叠率）；
- 最小回归集（用最少用例覆盖 100% 功能 bin + PATH）。

没有这些度量，“用例覆盖得够不够”只能靠功能覆盖率间接回答，不能直接回答“用例集合本身是否充分”。

---

### 三、完善建议：在文档里加一节“用例覆盖计划”

建议在现有覆盖率计划之外，补一节 **“用例覆盖计划”** ，包含五张表：

1. **用例分类表**：按粒度（单指令/序列/场景/系统）和类型（功能/边界/异常/性能/配置/回归）分类；
2. **用例-Feat-PATH-检查项映射表**：每个用例覆盖哪些 Feat、哪些 PATH、绑定哪些 SVA/scoreboard；
3. **用例充分性准则表**：每个覆盖对象至少需要多少用例、什么类型；
4. **错误注入矩阵**：异常用例的系统化覆盖；
5. **用例贡献与冗余矩阵**：用例对 bin/PATH 的贡献，识别冗余和缺口，构建最小回归集。

这五张表补上，用例覆盖方法学就从“事后判定框架”升级为“事前计划 + 事后判定 + 回归选择”的完整闭环。

---

### 四、一句话回答

**你现在这套用例覆盖方法学，作为“验证完备性判定框架”是完善的——四层证据链 + 用例×证据矩阵解决了 bin 命中不等于功能验证的问题；但作为完整的“用例覆盖方法学”还不完善，缺用例充分性准则、用例粒度对齐规则、状态机覆盖、错误注入矩阵、用例与随机回归协同准则、以及用例覆盖度量。补上这六块，才叫方法学完善；只做四层证据矩阵，叫判定框架完善。**