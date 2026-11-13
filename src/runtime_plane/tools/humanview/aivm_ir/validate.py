"""IR 一致性校验。

校验哲学：只审『语义上该成立』的东西，不审文本长得像什么。
  * CONSTRAINT_COMBO 格：若源表原文带『仅…允许』，CoverageCell.legality 必须捕获到；
  * CONFIG_ENUM 格：只校验『值在源表原文里』+『不误判成约束』，不做约束完备性断言；
  * HEADER / DESCRIPTOR：完全跳过，它们只是可追溯上下文；
  * test_num 与 execution_mode 的映射：走 Enum，不比字符串。

返回结构：{tp_id: {errors, infos, status, ...}} + 顶层 errors/infos。
[warn] 前缀的条目是非阻断告警，strict=False 时不会让 all_pass 失败。
"""
from __future__ import annotations

import re
from .ir_core import (
    Ontology, TestPointIR, TestNumKind, RawColumn, Category, Component,
    CellType, CellRole, CoverageCell,
)

_LEG = re.compile(r"仅.+?允许|仅.+?可|不允许|禁止|排他|独占")
_CONFIG_CELL_RE = re.compile(
    r"^\s*(13'?b|0x|0b|\d+\s*'[bB])"   # 位串 / 十六进制
    r"|bit\s*\[|bit\["                  # bit[…] 寄存器域
    r"|^\s*(spad|tile|mx)_", re.I       # spad_mode / tile_mode / mx_xxx
)


def _has_legality(text: str) -> bool:
    if not text or _CONFIG_CELL_RE.search(text):
        return False
    return bool(_LEG.search(text))


# ---------------------------------------------------------------- 单 TP 检查
def check_value_closure(tp: TestPointIR) -> list[str]:
    """DimensionValue.raw_text 必须能在源表原文里找到。
    source_row==0 的是推导/归纳格（如『无限制』），跳过。"""
    if not tp.raw_rows or not tp.dimensions:
        return []
    corpus = " ".join(" ".join(v for v in r.values() if v) for r in tp.raw_rows)
    errs: list[str] = []
    for dim in tp.dimensions:
        for dv in dim.value_domain:
            if dv.source_row > 0 and dv.raw_text and dv.raw_text not in corpus:
                errs.append(f"{tp.tp_id}/{dim.dim_id}: raw_text 不在源表: {dv.raw_text!r}")
    return errs


def check_legality_completeness(tp: TestPointIR) -> list[str]:
    """约束组合格（CONSTRAINT_COMBO）里，源表原文带『仅…允许』的，
    CoverageCell.legality 必须抓到。CONFIG_ENUM / HEADER / DESCRIPTOR 一律豁免——
    这是之前 23 条误报的根因。"""
    errs: list[str] = []
    for cell in tp.coverage_cells:
        if cell.cell_type is not CellType.CONSTRAINT_COMBO:
            continue
        if not _has_legality(cell.raw_text):
            continue
        if not cell.legality:
            errs.append(
                f"{tp.tp_id}#{cell.cell_id}: 源表有约束关键词但未提取 legality: "
                f"{cell.raw_text!r}")
    return errs


def check_coverage_driven(tp: TestPointIR) -> list[str]:
    """test_num ↔ execution_mode 的一致性，全部走 Enum。"""
    k = tp.test_num_kind
    if k is TestNumKind.ZERO and not tp.coverage_driven:
        return [f"{tp.tp_id}: test_num=0 但 coverage_driven=False"]
    if k is TestNumKind.EMPTY and tp.coverage_driven:
        return [f"[warn] {tp.tp_id}: test_num 为空却标了 coverage_driven，"
                f"请补 0 或改成 directed"]
    if k is TestNumKind.POSITIVE_INT and tp.coverage_driven and not tp.directed:
        return [f"{tp.tp_id}: test_num={tp.test_num} 为正整数却设为纯 coverage_driven"]
    return []


def check_category_component_consistency(tp: TestPointIR) -> list[str]:
    errs: list[str] = []
    if tp.category is Category.F and not tp.dut_components:
        errs.append(f"[warn] {tp.tp_id}: category=F 但未推断到 dut_components "
                    f"(feature_text={tp.feature_text!r})")
    blob = tp.feature_text.lower()
    for c in tp.dut_components:
        if c == Component.LMEM.value and "lmem" not in blob and "spad" not in blob:
            errs.append(f"{tp.tp_id}: 推断到 lmem，但 feature_text 无 lmem/spad 线索")
    return errs


def check_cell_type_sanity(tp: TestPointIR) -> list[str]:
    """类型自洽：配置枚举格不应带约束；HEADER 不应被标成 DIRECTED_CASE。"""
    errs: list[str] = []
    for cell in tp.coverage_cells:
        if cell.cell_type is CellType.CONFIG_ENUM and cell.legality:
            errs.append(f"{tp.tp_id}#{cell.cell_id}: 配置枚举格误带约束 "
                        f"{cell.legality!r} <- {cell.raw_text!r}")
        if cell.cell_type is CellType.DESCRIPTOR and cell.role is CellRole.LEAF and cell.raw_text:
            # 叶子位置却被判成纯说明：通常是分类器漏了新句式，记告警便于补全规则
            errs.append(f"[warn] {tp.tp_id}#{cell.cell_id}: 叶子格被判为 descriptor: "
                        f"{cell.raw_text!r}")
    return errs


def check_cover_bin_count(tp: TestPointIR) -> list[str]:
    bins = tp.cover_bin_cells()
    cfg = tp.config_enum_cells()
    if bins and tp.test_num_kind is TestNumKind.ZERO:
        return []  # coverage_driven + 有组合格：完美，不出提示
    if cfg and not bins and tp.test_num_kind is TestNumKind.ZERO:
        return [f"[info] {tp.tp_id}: test_num=0 但格子全是配置枚举("
                f"{len(cfg)}个)，将走『配置穷举覆盖』而非组合 bin"]
    return []


# ---------------------------------------------------------------- 入口
def validate_ontology(onto: Ontology, strict: bool = False) -> dict:
    report: dict = {
        "version": onto.version,
        "tps": {},
        "errors": [],
        "infos": [],
        "cell_type_totals": {},
    }
    from collections import Counter
    type_cnt: Counter = Counter()
    for tp in onto.testpoints:
        errs: list[str] = []
        errs += check_value_closure(tp)
        errs += check_legality_completeness(tp)
        errs += check_coverage_driven(tp)
        errs += check_category_component_consistency(tp)
        errs += check_cell_type_sanity(tp)
        infos = check_cover_bin_count(tp) if not strict else []
        for c in tp.coverage_cells:
            type_cnt[c.cell_type.value] += 1
        report["tps"][tp.tp_id] = {
            "errors": errs,
            "infos": infos,
            "status": "pass" if not [e for e in errs if not e.startswith("[")]
                     else "fail",
            "mode": tp.execution_mode.value,
            "num_kind": tp.test_num_kind.value,
            "cover_bins": len(tp.cover_bin_cells()),
            "config_enums": len(tp.config_enum_cells()),
            "directed_cases": len(tp.directed_case_cells()),
            "cell_types": tp.cell_type_breakdown(),
            "components": tp.dut_components,
        }
        report["errors"] += errs
        report["infos"] += infos

    report["cell_type_totals"] = dict(type_cnt)
    # 阻断性错误 = 非 [warn]/[info] 前缀
    blocking = [e for e in report["errors"] if not e.startswith("[")]
    report["all_pass"] = not blocking
    report["total_cover_bins"] = onto.total_coverage_points(material_only=True)
    report["total_config_enums"] = onto.total_config_enums()
    return report
