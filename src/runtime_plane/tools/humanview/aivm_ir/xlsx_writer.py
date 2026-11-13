from enum import Enum
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

from .ir_core import Ontology, TestPointIR, CoverageCell, Category, CellRole, CellType, RawColumn

# 输出表头：与源表列一一对应，保证 roundtrip 可再被 loader 读懂
HEADER = [
    "序号", "Feature 提取", "Sub_Feature（可选）", "Sub_Sub_Feature（可选）",
    "Sub_Sub_Sub_Feature（可选）", "TestName", "TestNum", "", "Doc Section", "章节",
]
# 列 -> RawColumn 键的写入映射（None 表示该列是占位/不填）
WRITE_COLS: list[tuple[int, RawColumn | None]] = [
    (1, RawColumn.SEQ),
    (2, RawColumn.FEATURE),
    (3, RawColumn.SUB_FEATURE),
    (4, RawColumn.SUB_SUB_FEATURE),
    (5, RawColumn.SUB_SUB_SUB_FEATURE),
    (6, RawColumn.TEST_NAME),
    (7, RawColumn.TEST_NUM),
    (8, None),
    (9, RawColumn.DOC_SECTION),
    (10, RawColumn.CHAPTER),
]

_HDR_FILL = PatternFill("solid", fgColor="D9E1F2")
_TP_FILL = PatternFill("solid", fgColor="FFF2CC")


def _cat_str(p: Category | str) -> str:
    return p.value if isinstance(p, Enum) else str(p)


def _tp_label(tp: TestPointIR) -> str:
    """A 列：TP 编号 + 整段 feature_text，与 loader 的解析约定对称。"""
    parts = [tp.tp_id]
    if tp.feature_text:
        parts.append(tp.feature_text)
    return " ".join(parts)


def _tp_header_row(tp: TestPointIR) -> dict[int, str]:
    """A=id（回读锚点）；B=id+feature_text；C=头行概述（若有），与源表同构。

    源表 TP 头行常在 C 列带概述（『握手数据必稳态』/『不同条件下成立的时序』），
    loader 把它收成 role=HEADER 的一格且不出 bin。概述回填进 C 列而不是另起一行，
    否则回读时叶子循环会再吃一格，逐格守恒被破坏（此前 320→376 即此因）。
    """
    hdr = {
        1: tp.orig_id,  # A：源表锚点原文；重复块(#2/#3)保留后缀，保证 roundtrip 顺序一致
        2: getattr(tp,"_src_b",None) or tp.feature_text or "",  # B：源表原文（id 已单独在 A）
        3: "",  # C：头行概述由 HEADER 叶子格承载，不能重复写，否则回读多一格
        6: tp.test_name or "",
        7: "" if tp.test_num is None else str(tp.test_num),
        9: tp.provenance.doc_section,
        10: tp.provenance.chapter or "",
    }
    for cell in tp.coverage_cells:
        if cell.role is CellRole.HEADER and cell.raw_text:
            hdr[3] = cell.raw_text   # C=二级分类，回读即 hdr_cell
            break
    return hdr

def _col_index(key: RawColumn) -> int:
    """列索引查表，与 WRITE_COLS 单一事实源对齐。"""
    for col_idx, k in WRITE_COLS:
        if k is key:
            return col_idx
    raise KeyError(key)


def _leaf_rows(tp: TestPointIR) -> list[dict[int, str]]:
    rows: list[dict[int, str]] = []
    for c in tp.coverage_cells:
        if not c.raw_text:
            continue
        # 头行概述格若已由 _tp_header_row 合进头行 C 列(header_owned)，此处不再另起行，
        # 否则同一概述在 RT 里出现两次 → 439→495 式重复收格。
        if c.meta.get("header_owned"):
            continue
        cells: dict[int, str] = {}
        col = c.meta.get("col")
        if c.role is CellRole.HEADER or c.cell_type is CellType.DESCRIPTOR:
            # 概述/分组格：按源表原列位(C/D/E)落一格，不带 A 列(锚点由头行独占)。
            # 首格通常与 _tp_header_row 写的 C 列同格，xlsx 里自然合一，不重复。
            cells[col or 3] = c.raw_text
        else:
            cells[col or 4] = c.raw_text          # 组合格落 D(或源表实际列)
            if c.legality:
                cells[5] = c.legality             # 约束跟 E 列
        rows.append(cells)
    return rows                                   # 无叶子格就返回空，不补占位行

def _raw_rows(tp: TestPointIR) -> list[dict[int, str]]:
    """原始行回放，但剥掉 A 列(seq)：锚点身份已由 _tp_header_row 独占写入，
    否则同一 TP 的 raw 首行又带 id，重读时会被当成第二个 TP（此前 RT 64→107 的根因）。"""
    out: list[dict[int, str]] = []
    for raw in tp.raw_rows:
        d = {col_idx: raw.get(key.value, "")
             for col_idx, key in WRITE_COLS if key is not None and key is not RawColumn.SEQ}
        if d:
            out.append(d)
    return out


def write_ontology_to_xlsx(onto: Ontology, path: str,
                           view: str = "leaves") -> None:
    """view: 'leaves' 叶子格（默认，M1 视角）/ 'dims' 维度 / 'raw' 原样回放。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "01_文档需求拆解"

    for col_idx, h in enumerate(HEADER, 1):
        c = ws.cell(row=1, column=col_idx, value=h)
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center", wrap_text=True)
        c.fill = _HDR_FILL

    row = 2
    for tp in onto.testpoints:
        # TP 头行
        for col, v in _tp_header_row(tp).items():
            cc = ws.cell(row=row, column=col, value=v)
            cc.fill = _TP_FILL
            cc.font = Font(bold=(col == 2))
        row += 1

        if view == "raw" and tp.raw_rows:
            body = _raw_rows(tp)
        elif view == "leaves" and tp.coverage_cells:
            body = _leaf_rows(tp)         # 叶子格视图：锚点已由头行承担，body 不带 A 列
        elif tp.coverage_cells:
            body = _leaf_rows(tp)
        elif tp.raw_rows:
            body = _raw_rows(tp)          # 纯定向/配置 TP：回放原行（已剥 A 列）
        else:
            body = []                     # 单行 TP（如 CR01-F）：头行即全部，不补占位

        for cells in body:
            for col, v in cells.items():
                ws.cell(row=row, column=col, value=v)
            row += 1

    widths = [6, 42, 42, 34, 26, 18, 10, 4, 30, 24]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    ws.freeze_panes = "A2"
    wb.save(path)
    print(f"[writer] {path} written, {row - 2} data rows  (view={view})")


def write_ontology_to_json(onto: Ontology, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(onto.to_json())
    print(f"[writer] {path} written")
