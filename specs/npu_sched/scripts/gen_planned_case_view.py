#!/usr/bin/env python3
"""Render all planned CMDSCHED cases as a clearly-marked PLACEHOLDER view.

This is NOT evidence: it reads docs/specs/cmdsched_cases.csv and
docs/specs/cmdsched_testpoints.csv only. It never writes evidence/json, so it
cannot make the V00 gates green.
"""
from __future__ import annotations

import csv
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_DIR = ROOT / "docs" / "specs"
OUT = ROOT / "data" / "case_plan_view.html"


def read_rows(name):
    with (SPEC_DIR / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def split(value):
    return [item for item in (value or "").split("|") if item]


def esc(value):
    return html.escape(str(value))


def badge(text, kind):
    return f'<span class="badge {kind}">{esc(text)}</span>'


def table(headers, rows):
    lines = ["<table>", "<thead><tr>"]
    lines += [f"<th>{esc(header)}</th>" for header in headers]
    lines += ["</tr></thead>", "<tbody>"]
    for row in rows:
        lines.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    lines += ["</tbody>", "</table>"]
    return "\n".join(lines)


def main():
    cases = read_rows("cmdsched_cases.csv")
    tps = read_rows("cmdsched_testpoints.csv")
    contracts = {row["contract_id"]: row for row in read_rows("cmdsched_contracts.csv")}
    features = {row["feature_id"]: row for row in read_rows("cmdsched_features.csv")}

    case_tps = {}
    for tp in tps:
        case_tps.setdefault(tp["case_plan"], []).append(tp)
    for case in cases:
        missing = [tp["tp_id"] for tp in case_tps.get(case["case_id"], []) if tp["contract_id"] not in contracts]
        if missing:
            raise SystemExit(f"{case['case_id']}: unknown contract in TPs {missing}")

    covergroups = sorted({cg for case in cases for cg in split(case["covergroups"])})
    contract_set = {cid for case in cases for cid in split(case["contract_ids"])}

    nav = " · ".join(
        f'<a href="#{esc(case["case_id"])}">{esc(case["case_id"])}</a>'
        for case in cases
    )
    summary_rows = []
    for case in cases:
        tp_ids = case_tps.get(case["case_id"], [])
        summary_rows.append([
            f'<a href="#{esc(case["case_id"])}"><code>{esc(case["case_id"])}</code></a>',
            esc(case["batch"]),
            esc(case["owner"]),
            str(len(split(case["contract_ids"]))),
            str(len(tp_ids)),
            esc(case["covergroups"].replace("|", " / ")),
            badge("PLANNED", "planned"),
        ])

    sections = []
    for case in cases:
        cid = case["case_id"]
        tp_ids = case_tps.get(cid, [])
        contract_rows = []
        for contract_id in split(case["contract_ids"]):
            contract = contracts.get(contract_id, {})
            contract_rows.append([
                f'<code>{esc(contract_id)}</code>',
                esc(contract.get("category", "-")),
                esc(contract.get("check_method", "-")),
                esc(contract.get("spec_ref", "-")),
                badge(contract.get("status", "unknown"), "assume"),
            ])
        tp_rows = []
        for tp in tp_ids:
            feature = features.get(tp["feature_id"], {})
            path = "/".join(
                value for value in (
                    feature.get("feature_l1"), feature.get("feature_l2"), feature.get("feature_l3")
                ) if value and value != "-"
            ) or tp["feature_id"]
            tp_rows.append([
                f'<code>{esc(tp["tp_id"])}</code>',
                esc(path),
                esc(tp["topic"]),
                f'<code>{esc(tp["contract_id"])}</code>',
                esc(tp["priority"]),
                badge(tp["status"], "planned"),
            ])
        checks = " ".join(f'<code>{esc(item)}</code>' for item in split(case["checks"]))
        cgs = " ".join(f'<code>{esc(item)}</code>' for item in split(case["covergroups"]))
        sections.append(f"""
<section class="case" id="{esc(cid)}">
  <h2><code>{esc(cid)}</code> {badge("PLACEHOLDER / NOT RUN", "placeholder")}</h2>
  <p class="meta">{esc(case["test_name"])} · batch {esc(case["batch"])} · owner {esc(case["owner"])} · status {esc(case["status"])}</p>
  <div class="warn"><strong>这不是证据。</strong>该 case 来自 target plan，尚未生成 case YAML / UVM test / 仿真 log / URG 报告，不能用于签核。</div>
  <h3>Covergroups / Checks（计划）</h3>
  <p>{cgs or "-"}</p>
  <p>{checks or "-"}</p>
  <h3>契约（{len(contract_rows)}）</h3>
  {table(["contract", "category", "method", "spec_ref", "status"], contract_rows)}
  <h3>测试点（{len(tp_rows)}）</h3>
  {table(["tp_id", "feature", "topic", "contract", "priority", "status"], tp_rows)}
  <h3>Evidence</h3>
  <p class="placeholder">NOT RUN · 无 JSON / log / cov / 波形</p>
</section>""")

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CMDSCHED planned case view (PLACEHOLDER)</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; background: #f8fafc; color: #1f2937;
         font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }}
  header {{ background: #7c2d12; color: #fff; padding: 26px 34px; }}
  header h1 {{ margin: 0 0 6px; font-size: 26px; }}
  header p {{ margin: 0; color: #fed7aa; font-size: 13px; }}
  main {{ max-width: 1500px; margin: 0 auto; padding: 22px 26px 50px; }}
  .warn {{ background: #fff7ed; border-left: 4px solid #ea580c; padding: 10px 14px;
           color: #9a3412; font-size: 13px; margin: 10px 0 16px; }}
  .cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }}
  .card {{ background: #fff; border-radius: 10px; padding: 14px 18px;
           min-width: 140px; box-shadow: 0 1px 3px rgba(15,23,42,.08); }}
  .card-label {{ color: #64748b; font-size: 12px; margin-bottom: 6px; }}
  .card-value {{ font-size: 20px; font-weight: 700; }}
  nav {{ background: #fff; border-radius: 10px; padding: 12px 18px; margin-bottom: 18px;
         font-size: 13px; box-shadow: 0 1px 3px rgba(15,23,42,.08); }}
  h2 {{ margin: 0 0 8px; font-size: 20px; }}
  h3 {{ margin: 18px 0 8px; font-size: 15px; color: #334155; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           box-shadow: 0 1px 3px rgba(15,23,42,.06); }}
  th, td {{ border-bottom: 1px solid #e2e8f0; padding: 8px 10px;
            text-align: left; vertical-align: top; font-size: 13px; }}
  th {{ background: #eef2f7; color: #334155; font-weight: 600; }}
  code {{ background: #eef2f7; padding: 1px 5px; border-radius: 4px;
          font-family: ui-monospace, Consolas, monospace; font-size: 12px; }}
  a {{ color: #2563eb; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .case {{ background: #fff; border-radius: 12px; padding: 20px 22px;
           margin: 22px 0; box-shadow: 0 1px 4px rgba(15,23,42,.08); }}
  .meta {{ color: #64748b; font-size: 13px; margin: 0 0 10px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px;
            font-size: 12px; font-weight: 700; }}
  .badge.planned {{ background: #fef3c7; color: #92400e; }}
  .badge.placeholder {{ background: #ffedd5; color: #9a3412; }}
  .badge.assume {{ background: #e0e7ff; color: #3730a3; }}
  .placeholder {{ background: #f8fafc; border: 1px dashed #cbd5e1;
                  padding: 10px 12px; color: #64748b; font-size: 13px; }}
  footer {{ max-width: 1500px; margin: 0 auto; padding: 0 26px 30px;
            color: #64748b; font-size: 12px; }}
</style>
</head>
<body>
<header>
  <h1>CMDSCHED planned case view</h1>
  <p>PLACEHOLDER · 全部来自 docs/specs/cmdsched_cases.csv · 不是仿真证据，不可签核</p>
</header>
<main>
  <div class="warn">
    本页把 target plan 的 12 个 case 全部列出，但状态是 <strong>planned / NOT RUN</strong>。
    没有 case YAML、UVM test、仿真 log、URG、SCB/Checker/SVA 或波形。
    <a href="case_view.html">返回可执行 case view（V00，4 条）</a>
  </div>
  <div class="cards">
    <div class="card"><div class="card-label">Planned cases</div><div class="card-value">{len(cases)}</div></div>
    <div class="card"><div class="card-label">Contracts</div><div class="card-value">{len(contract_set)}</div></div>
    <div class="card"><div class="card-label">Test points</div><div class="card-value">{len(tps)}</div></div>
    <div class="card"><div class="card-label">Covergroups</div><div class="card-value">{len(covergroups)}</div></div>
    <div class="card"><div class="card-label">Evidence</div><div class="card-value">0</div></div>
  </div>
  <nav>Cases: {nav}</nav>
  <section>
    <h2>计划概览</h2>
    {table(["case", "batch", "owner", "contracts", "TPs", "covergroups", "status"], summary_rows)}
  </section>
  {''.join(sections)}
</main>
<footer>
  数据源：docs/specs/cmdsched_cases.csv、cmdsched_testpoints.csv、cmdsched_contracts.csv、cmdsched_features.csv。
  本页是占位视图，不写入 evidence/，不参与 V00 门禁。
</footer>
</body>
</html>
"""
    OUT.write_text(html_text, encoding="utf-8", newline="\n")
    print(f"[PLACEHOLDER] {OUT.relative_to(ROOT).as_posix()} "
          f"cases={len(cases)} contracts={len(contract_set)} tps={len(tps)}")
    sys.exit(0)


if __name__ == "__main__":
    main()
