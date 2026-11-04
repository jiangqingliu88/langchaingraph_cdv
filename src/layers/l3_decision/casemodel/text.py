"""纯文本渲染 —— CLI 的输出，以及界面「导出报告」的那份文本。

不含任何判定逻辑：它只把 `AnalysisResult` 摆成可读的形状。所以这里没有 if
判断业务规则，只有排版。界面的导出报告复用这里的 `report()` —— 两处输出
不会各说各话。

> 原先在 `view/text.py`。界面搬去工作台之后，「表现层」就只剩这一个文件，
> 那一层已经没有存在的理由，于是文件上提到包根 —— 与 `api.py`、`cli.py` 平级。

渲染顺序与「从骨架到取值」的阅读顺序一致：
对象 → 组织树 → 专题 → 维度/字段 → 交叉矩阵 → 覆盖 → 诊断。
"""
from __future__ import annotations

import unicodedata
from typing import Dict, List, Sequence

from .analysis import (AnalysisResult, CATEGORY_NAMES, group_by_category,
                       rule_docs)

BOX = "─" * 78


def rule(width: int = 78) -> str:
    return "─" * width


def display_width(text: str) -> int:
    """终端显示宽度 —— 中日韩全角字符占 2 列。

    表格里混排中英文时用 len() 补空格必然错位（'指令' 是 2 个字符却占 4 列），
    所以切分与补齐都按显示宽度算。
    """
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in text or "")


def cut(text: str, width: int) -> str:
    """按显示宽度截断，超长补省略号。"""
    text = text or ""
    if display_width(text) <= width:
        return text
    out, used = [], 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > max(1, width - 1):
            break
        out.append(ch)
        used += w
    return "".join(out) + "…"


def pad(text: str, width: int, align: str = "<") -> str:
    """按显示宽度补齐 —— 表格列对齐用。"""
    text = text or ""
    fill = max(0, width - display_width(text))
    if align == ">":
        return " " * fill + text
    if align == "^":
        left = fill // 2
        return " " * left + text + " " * (fill - left)
    return text + " " * fill


def bar(ratio: float, width: int = 12) -> str:
    filled = int(round(max(0.0, min(1.0, ratio)) * width))
    return "█" * filled + "░" * (width - filled)


def section(title: str, extra: str = "") -> str:
    head = f"{BOX}\n{title}"
    if extra:
        head += f" —— {extra}"
    return head + f"\n{BOX}"


# ════════════════════════════════════════════════════════════
# 概览
# ════════════════════════════════════════════════════════════

def render_layers(result: AnalysisResult) -> str:
    model = result.model
    out = [section("分层结构", model.object_label)]
    out.append(f"{pad('层', 5)} {pad('名称', 22)} {pad('作用', 16)} "
               f"{pad('数量', 4, '>')}  明细")
    out.append(rule())
    for row in model.layer_rows():
        out.append(f"{pad(row['layer'], 5)} {pad(row['name'], 22)} "
                   f"{pad(row['role'], 16)} {pad(str(row['count']), 4, '>')}  "
                   f"{row['detail']}")
    return "\n".join(out)


def render_summary(result: AnalysisResult) -> str:
    s = result.summary()
    gen = result.generation
    out = [section("生成结果", f"源 {result.model.source}")]
    out.append(f"  驱动             : "
               f"{'专题（themes）' if gen.driver == 'themes' else '交叉组（cross_groups）'}")
    out.append(f"  case 数          : {s['case_count']}")
    if s["truncated"]:
        out.append(f"  组合规模         : {s['case_total_before_cap']}"
                   f"（超过上限，已丢弃 {s['dropped']} 个）")
    out += [
        f"  组织树叶子       : {s['org_leaf_count']}",
        f"  专题             : {s['theme_count']} 个"
        f"（{'、'.join(gen.priorities_used) or '—'}）",
        f"  seed             : {gen.seed}（同模型同 seed 结果完全一致）",
        f"  方法             : {'、'.join(gen.methods_used) or '—'}",
        f"  取值覆盖率       : {result.coverage_ratio:.1%}",
        f"  诊断             : 错误 {s['error_count']}"
        f" / 警告 {s['warning_count']} / 提示 {s['info_count']}",
    ]
    for note in gen.notes:
        out.append(f"  注意             : {note}")
    return "\n".join(out)


def render_score(result: AnalysisResult) -> str:
    out = [section("完备性评分", f"{result.score.total:.1f} / 100")]
    out.append(f"  {pad('评分项', 12)} {pad('子分', 6, '>')} "
               f"{pad('加权', 7, '>')}   扣分原因")
    out.append(rule())
    for name, sub, weighted, reasons in result.score.row_reasons():
        out.append(f"  {pad(name, 12)} {sub:>6.2f} {weighted:>7.1f}   "
                   f"{'；'.join(reasons) if reasons else '—'}")
    return "\n".join(out)


# ════════════════════════════════════════════════════════════
# 功能组织树与专题
# ════════════════════════════════════════════════════════════

def render_org_tree(result: AnalysisResult) -> str:
    model = result.model
    out = [section("功能组织树",
                   f"{len(model.tree_nodes)} 个节点 / {len(model.leaf_nodes)} 个叶子"
                   f"（只有叶子生成 case）")]
    if not model.org_root:
        out.append("  （模型没有声明 sub_objects）")
        return "\n".join(out)

    out.append(f"  {pad('节点', 34)} {pad('代号', 7)} {pad('专题', 30)} case")
    out.append(rule())

    def emit(node, prefix: str, is_last: bool) -> None:
        connector = "└─ " if is_last else "├─ "
        cases = result.cases_for_node(node.id) if node.is_leaf else []
        themes = sorted({c.theme for c in cases if c.theme})
        mark = "✓" if cases else ("·" if not node.is_leaf else "✗")
        name = f"{prefix}{connector}{node.name}"
        detail = "、".join(themes) or ("分支" if not node.is_leaf else "无")
        out.append(f"  {pad(cut(name, 34), 34)} {pad(node.code, 7)} "
                   f"{pad(cut(detail, 28), 30)} "
                   f"{mark}{len(cases) if cases else ''}")
        child_prefix = prefix + ("   " if is_last else "│  ")
        for i, child in enumerate(node.children):
            emit(child, child_prefix, i == len(node.children) - 1)

    for i, root in enumerate(model.org_root):
        emit(root, "", i == len(model.org_root) - 1)
    return "\n".join(out)


def render_themes(result: AnalysisResult) -> str:
    model = result.model
    rows = result.theme_rows()
    out = [section("专题", f"{len(rows)} 个，"
                          f"{len({r['priority'] for r in rows})} 个优先级")]
    if not rows:
        out.append("  （模型没有声明 themes，生成退化为按交叉组）")
        return "\n".join(out)

    out.append(f"  {pad('优先级', 6)} {pad('专题', 12)} {pad('名称', 24)} "
               f"{pad('作用目标', 20)} {pad('维度', 18)} {pad('方法', 6)} case")
    out.append(rule())
    for r in rows:
        out.append(f"  {pad(r['priority'], 6)} {pad(r['id'], 12)} "
                   f"{pad(cut(r['name'], 22), 24)} {pad(cut(r['target'], 18), 20)} "
                   f"{pad(cut(r['dimensions'], 16), 18)} {pad(r['method'], 6)} "
                   f"{r['case_count']}")
    out.append("")
    out.append("  · 作用于功能组织树的专题用 applies_to 指定节点；"
               "留空表示不作用于树（全局正交关注点）")
    out.append("  · dimensions 留空表示各维度随机组合")
    return "\n".join(out)


# ════════════════════════════════════════════════════════════
# 矩阵与覆盖
# ════════════════════════════════════════════════════════════

def render_matrix(result: AnalysisResult) -> str:
    m = result.matrix
    if m is None or not m.dimensions:
        return section("维度交叉矩阵", "（没有维度）")
    out = [section("维度交叉矩阵",
                   f"{len(m.dimensions)} 个维度 / {m.total_pairs()} 对，"
                   f"已声明 {m.declared_count()} 对")]
    labels = [d.label for d in m.dimensions]
    cell_w = max(6, min(12, 66 // max(1, len(labels))))
    out.append(" " * 18 + "".join(pad(cut(l, cell_w), cell_w, "^") for l in labels))
    for i, label in enumerate(labels):
        row = f"  {pad(cut(label, 12), 12)}   "
        for j in range(len(labels)):
            if i == j:
                row += pad("—", cell_w, "^")
            else:
                c = m.cells.get((min(i, j), max(i, j)))
                row += pad(c.mark if c else "", cell_w, "^")
        out.append(row)
    out.append("")
    out.append("  ★ 必需交叉   ✓ 可选交叉   ✗ 禁止交叉   （空）未声明")
    return "\n".join(out)


def render_coverage(result: AnalysisResult) -> str:
    out = [section("字段取值覆盖",
                   "分母是字段声明的取值点，分子是被 case 命中的")]
    for dcov in result.dimension_coverage:
        out.append(f"  [{dcov.key}] {dcov.name}"
                   f"  {dcov.hit_count}/{dcov.total} ({dcov.ratio:.0%})")
        for f in dcov.fields:
            tail = "  （联动派生，取值跟随被联动字段）" if f.derived else ""
            out.append(f"      {pad(f.field, 16)} {pad(f.type_name, 6)} "
                       f"{bar(f.ratio)} {f.hit_count}/{f.total}{tail}")
            if f.missing:
                out.append(f"          未命中: {'、'.join(f.missing)}")
    return "\n".join(out)


# ════════════════════════════════════════════════════════════
# 外部核对与诊断
# ════════════════════════════════════════════════════════════

def render_external(result: AnalysisResult) -> str:
    ext = result.external
    if ext is None:
        return ""
    out = [section("真实 case 核对", f"源 {ext.source or '（未记录）'}")]
    out.append(f"  真实 case 数     : {ext.case_count}")
    out.append(f"  真实取值覆盖     : {ext.coverage_ratio:.1%}"
               f"     （模型生成覆盖 {ext.generated_ratio:.1%}）")
    out.append(f"  重复 case        : {len(ext.duplicates)} 组")
    out.append(f"  缺环境指纹       : {ext.cases_without_environment}")
    out.append(f"  模型落后于实现   : {len(ext.unknown_fields)} 个未声明字段 + "
               f"{len(ext.undeclared_values)} 个未声明取值 + "
               f"{len(ext.unknown_themes)} 个未声明专题")
    out.append(f"  实现落后于模型   : {len(ext.generated_only)} 个取值")
    out.append("")
    out.append("  注：真实 case 的缺陷不计入模型完备性评分 —— 评分必须只是"
               "模型的属性，否则换一份 case 列表分数就变，不再可复现。")

    for title, items in (
            ("真实缺口：模型覆盖了、真实 case 没写",
             [f"[{d}] {f} = {v}" for d, f, v in ext.generated_only]),
            ("重复 case",
             [f"{desc}  ← {'、'.join(ids)}" for desc, ids in ext.duplicates]),
            ("模型未声明的字段（模型落后于实现）",
             [f"{c} 用了 '{f}'" for c, f in ext.unknown_fields]),
            ("模型未声明的取值（模型落后于实现）",
             [f"{c}: {f} = {v}" for c, f, v in ext.undeclared_values]),
            ("模型未声明的专题",
             [f"{c}: {t}" for c, t in ext.unknown_themes]),
            ("case_id 命名不合规",
             [f"{c}: {r}" for c, r in ext.invalid_ids]),
    ):
        if items:
            out.append("")
            out.append(f"  ── {title} ({len(items)}) ──")
            out.extend(f"    {x}" for x in items)

    if ext.node_coverage or ext.theme_coverage:
        out.append("")
        out.append("  ── 真实 case 落到了哪些结构/轮次 ──")
        for node in result.model.leaf_nodes:
            n = ext.node_coverage.get(node.id, 0)
            out.append(f"    {'✓' if n else '✗'} "
                       f"{pad(cut(node.path_label(), 30), 30)} {n} 个真实 case")
        for t in result.model.themes:
            n = ext.theme_coverage.get(t.id, 0)
            out.append(f"    {'✓' if n else '✗'} {t.priority} "
                       f"{pad(cut(t.label, 24), 24)} {n} 个真实 case")
    return "\n".join(out)


def render_issues(result: AnalysisResult) -> str:
    out = [section("诊断明细",
                   f"错误 {result.summary()['error_count']}"
                   f" / 警告 {result.summary()['warning_count']}"
                   f" / 提示 {result.summary()['info_count']}")]
    if not result.issues:
        out.append("  无。")
        return "\n".join(out)
    for cat, items in group_by_category(result.issues).items():
        out.append(f"  ── {CATEGORY_NAMES.get(cat, cat)} ({len(items)}) ──")
        out.extend(f"     {i}" for i in items)
    return "\n".join(out)


# ════════════════════════════════════════════════════════════
# 规则清单
# ════════════════════════════════════════════════════════════

def render_rules() -> str:
    """规则清单 —— 从规格注册表读，所以永远不会与实现漂移。"""
    docs = rule_docs()
    out = [section("校验规则", f"共 {len(docs)} 条")]
    by_cat: Dict[str, List[tuple]] = {}
    for rid, severity, cat, desc in docs:
        by_cat.setdefault(cat, []).append((rid, severity, desc))
    for cat in sorted(by_cat, key=lambda c: list(CATEGORY_NAMES).index(c)
                      if c in CATEGORY_NAMES else 99):
        out.append(f"  ── {CATEGORY_NAMES.get(cat, cat)} ({len(by_cat[cat])}) ──")
        for rid, severity, desc in by_cat[cat]:
            out.append(f"     {pad(rid, 34)} {pad(severity, 8)} {desc}")
    return "\n".join(out)


# ════════════════════════════════════════════════════════════
# 组合
# ════════════════════════════════════════════════════════════

def sections(result: AnalysisResult, with_external: bool = True) -> List[str]:
    parts = [render_layers(result), render_org_tree(result), render_themes(result),
             render_summary(result), render_score(result), render_matrix(result)]
    if with_external:
        ext = render_external(result)
        if ext:
            parts.append(ext)
    parts.append(render_coverage(result))
    parts.append(render_issues(result))
    return parts


def report(result: AnalysisResult) -> str:
    return "\n\n".join(sections(result))


def render_cases(cases: Sequence[object], *, title: str = "case 属性表") -> str:
    out = [section(title, f"{len(cases)} 个")]
    for c in cases:
        out.append(f"  {c.case_id}   优先级 {c.priority or '—'}   专题 {c.theme or '—'}")
        out.append(f"      树路径   {c.tree_path or '（不作用功能组织树）'}")
        out.append(f"      字段     "
                   + "；".join(f"{k}={v}" for k, v in c.fields.items()))
        out.append(f"      检查     {'、'.join(c.checks) or '（无）'}")
    return "\n".join(out)
