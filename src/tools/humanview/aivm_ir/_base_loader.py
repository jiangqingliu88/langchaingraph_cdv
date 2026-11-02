import re
import io
import os
from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.utils import column_index_from_string

from .ir_core import (
    Ontology, TestPointIR, Provenance, Category, Component, RawColumn,
    CoverageCell, CellRole, CellType, DimensionValue, Dimension, TestNumKind,
)

TP_ID_PREFIX = "NPU_V2-CMDSCHED-"
TP_ID_RE = re.compile(rf"^{re.escape(TP_ID_PREFIX)}[A-Z0-9]+")

# 组件推断：按词边界匹配 sub_feature / feature 文本。LMEM 放最后避免 lsu 误伤。
_COMPONENT_ORDER = [Component.GLSU, Component.LLSU, Component.NIU,
                    Component.VPU, Component.MPU, Component.LMEM]
_COMPONENT_PATTERNS = [(c, re.compile(rf"\b{re.escape(c.value)}\b", re.I))
                       for c in _COMPONENT_ORDER]

# 从 TP id 解析 Category：…-IF02  /  -CR01-F  /  -C02-F
# 注意：id 末尾的 '-F' / '-C' 是『功能域标记』（feature 编号后缀），不是专题码，
# 例如 NPU_V2-CMDSCHED-CR01-F 的专题是 CR 而不是 F。因此先剥掉尾部 -[A-Z] 再取码。
_ID_TAIL_SUFFIX = re.compile(r"-[A-Z]+$")   # 剥 -F / -P01 整段功能域后缀
_CAT_CODE = re.compile(rf"{re.escape(TP_ID_PREFIX)}([A-Z]+?)\d")  # 首个字母段，避免 F21-P01 吃到 F           # 末尾单字母功能域标记
_CAT_RE = re.compile(rf"{re.escape(TP_ID_PREFIX)}([A-Z]+)\d")


def _norm_test_num(v: str) -> str | int | None:
    """归一化 G 列：纯空白 -> None；纯数字 -> int；否则保留原文（公式/备注）。"""
    if not v:
        return None
    s = v.strip()
    if s == "":
        return None
    if s.startswith("="):
        return None                          # 块级汇总公式（=SUM(...) 不是本格 test_num）
    try:
        return int(s)
    except ValueError:
        return s


def infer_category(tp_id: str) -> Category:
    core = _ID_TAIL_SUFFIX.sub("", tp_id or "")   # NPU_...-CR01-F -> ...-CR01
    m = _CAT_CODE.match(core)
    if m:
        cand = Category.from_code(m.group(1))
        if cand is not Category.UNKNOWN:
            return cand
    # 兜底：扫整个 id 里的专题码
    for cat in Category:
        if cat is Category.UNKNOWN:
            continue
        if re.search(rf"{cat.value}\d", tp_id.upper()):
            return cat
    return Category.UNKNOWN


def infer_components(tp: TestPointIR) -> list[str]:
    """从 feature_text + 所有 sub 文本里按词边界推断涉及模块。"""
    # 组件线索：feature_text(一级) + 所有 sub 列(C/D/E) + 已识别的 test_name(F 列用例名)。
    # 只扫 raw_rows 的 sub_feature 会漏掉『头行 C 列』那条（源表 F01 的
    # "支持GLSU模块的配置和工作…" 写在 C 列），导致 F 类 TP 组件推断为空。
    subs = " ".join(
        (r.get(RawColumn.SUB_FEATURE.value, "") or "")
        + " " + (r.get(RawColumn.SUB_SUB_FEATURE.value, "") or "")
        + " " + (r.get(RawColumn.SUB_SUB_SUB_FEATURE.value, "") or "")
        + " " + (r.get(RawColumn.TEST_NAME.value, "") or "")
        for r in tp.raw_rows
    )
    blob = tp.feature_text + " " + subs
    hit: list[str] = []
    for c, pat in _COMPONENT_PATTERNS:
        if pat.search(blob) and c.value not in hit:
            hit.append(c.value)
    return hit


def _discover_columns(ws, header_rows=(1, 2, 3)) -> dict[int, RawColumn]:
    """自发现列索引 -> RawColumn。扫描前几行：writer 只有第1行表头，
    源表第1行是说明、第2/3行是中/英表头，全部兼容。"""
    mapping = RawColumn.xlsx_header_map()
    col_map: dict[int, RawColumn] = {}
    # 双表头兼容：源表第 1 行是说明、第 2/3 行是『一级分类/二级分类/…』和
    # 『feature 提取/sub_feature（可选）/…』两层，同一列在两行里会命中两个不同
    # 的 key。因此先建列→key 的候选列表，再按『最具体』（含括号说明的优先）定稿，
    # 避免 C/D 两列都被误映射成 sub_feature。
    candidates: dict[int, list[str]] = {}
    for row in header_rows:
        if row > ws.max_row:
            break
        for col in range(1, ws.max_column + 1):
            v = ws.cell(row=row, column=col).value
            if v is None:
                continue
            key = str(v).strip().lower().replace("（", "(").replace("）", ")").replace(" ", "")
            if key in mapping:
                candidates.setdefault(col, []).append(key)
    specificity = lambda k: (0 if "(" in k or k in {"seq","feature","sub_feature","sub_sub_feature","sub_sub_sub_feature","test_name","test_num","doc_section","chapter"} else 1, k)
    for col, keys in candidates.items():
        if col in col_map:
            continue
        # 优先取『更具体』的那个表头（即带（可选）说明的）
        chosen = max(keys, key=specificity)
        col_map[col] = mapping[chosen]
    return col_map


def _cell(ws, row: int, col: int) -> str:
    """读单元格值；碰上 openpyxl 的 MergedCell 代理，回退到合并区左上角真值。

    源表 A 列存在『同一 TP id 占多行』的合并单元格（BO02-F02、R02(RD-RR) 等），
    拆行后只有首行有字、其余是 MergedCell。此前这里直接 str(MergedCell)==''
    导致：锚点只在首行命中一次、后续合并行被当成『无锚点叶子』吞掉，或者
    data_only 路径下合并区每行都回显同一个 id 而被误切成 N 个假 TP。
    统一走左上角取值后，合并块在 loader 眼里就是『一个锚点 + N-1 个归属行』。
    """
    c = ws.cell(row=row, column=col)
    v = c.value
    if isinstance(v, MergedCell) or v is None:
        for rng in ws.merged_cells.ranges:
            if c.coordinate in rng:
                v = ws.cell(row=rng.min_row, column=rng.min_col).value
                break
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def _anchor_text(ws, row: int, col: int) -> str:
    """锚点列专用：合并单元格按『整块首行』读，避免合并区内重复 id。"""
    c = ws.cell(row=row, column=col)
    for rng in ws.merged_cells.ranges:
        if c.coordinate in rng and rng.min_row != row:
            return _cell(ws, rng.min_row, col)
    return _cell(ws, row, col)


def _build_raw(ws, row: int, col2key: dict[int, RawColumn]) -> dict[str, str]:
    out: dict[str, str] = {}
    for col, key in col2key.items():
        out[key.value] = _cell(ws, row, col)
    return out


def load_xlsx_to_ontology(path: str, version: str = "loaded") -> Ontology:
    # 用 BytesIO 打开：附件路径经沙盒传递时带 query 片段，openpyxl 会把它
    # 当非法 URI 拒掉（"does not support  file format"）。字节流绕过路径校验。
    _buf = open(path, "rb").read()
    wb = load_workbook(io.BytesIO(_buf), data_only=False)
    try:
        ws = wb["01_文档需求拆解"]
    except KeyError:
        raise RuntimeError(f"[loader] 找不到工作表 '01_文档需求拆解'，可用: {wb.sheetnames}")
    col2key = _discover_columns(ws)

    # 必须有的列，缺了直接报错而不是悄悄错位
    required = {RawColumn.FEATURE.value, RawColumn.TEST_NUM.value}
    missing = required - {k.value for k in col2key.values()}
    if missing:
        raise RuntimeError(f"[loader] 表头未识别到必需列 {missing}，实际列头: "
                          f"{[ws.cell(row=2,column=c).value for c in col2key]}")

    # 列位按『真实源表』固定，不依赖表头自发现（源表 A=id、B=feature_text，
    # 自发现会把 A 误映射成 SEQ，导致锚点读到空）。writer 回放时 id 写在 A 列，
    # 与这里完全一致，roundtrip 不受影响。
    SEQ_COL = next((c for c, k in col2key.items() if k is RawColumn.SEQ), 1)
    FEAT_COL = next((c for c, k in col2key.items() if k is RawColumn.FEATURE), 2)
    ANCHOR_COL = SEQ_COL

    def _anchor(row: int) -> str:
        a = _anchor_text(ws, row, ANCHOR_COL)
        if a and _anchor_id(a):
            return a
        return _cell(ws, row, FEAT_COL)  # 退化：B 列可能本身就是 "id + 文本"

    def _anchor_id(s: str) -> str | None:
        toks = (s or "").split()
        return toks[0] if toks and TP_ID_RE.match(toks[0]) else None

    # 数据起点：锚点列里第一个像 TP id 的行。源表=行4，writer 回放=行2。
    start_row = 2
    for probe in range(1, min(ws.max_row, 8) + 1):
        if _anchor_id(_anchor(probe)):
            start_row = probe
            break

    tps: list[TestPointIR] = []
    current: TestPointIR | None = None
    row = start_row
    _seen_tp_ids: set[str] = set()          # 合并单元格同一 id 跨行回显时去重

    while row <= ws.max_row:
        anchor = _anchor(row)
        tok0 = _anchor_id(anchor)
        # 合并块内『非首行』也会回显同一个 id：直接当归属行，不要开新 TP。
        if tok0 is not None and tok0 in _seen_tp_ids:
            if current is not None:
                row += 1
                continue
            tok0 = None                      # 极端：块首已被回收，安全降级
        is_header = tok0 is not None

        # 源表末行 'total num' / 汇总行：A 列像 TP id 但无 feature_text，直接跳过，
        # 否则会把 =SUM(...) 那行误收成一个 TP。
        # 源表末行形如 'NPU_V2-CMDSCHED-P06-RR total num' 的汇总行：
        # 锚点列 = id + 'total num'，feature 段只是 'total num'。提前丢弃，
        # 否则会把 =SUM(...) 那行误收成一个 TP。
        if is_header and "num" in anchor[len(tok0):].lower():
            row += 1
            continue

        if is_header:
            tp_id = tok0
            feature_text = anchor[len(tp_id):].strip()
            if not feature_text and row <= ws.max_row:
                b = _cell(ws, row, FEAT_COL)
                if not _anchor_id(b):
                    feature_text = b
            cat = infer_category(tok0)
            hdr_raw = _build_raw(ws, row, col2key)
            tn = _norm_test_num(hdr_raw.get(RawColumn.TEST_NUM.value, ""))
            current = TestPointIR(
                tp_id=tok0,
                feature_text=feature_text,
                feature_path=[cat.value] + ([feature_text] if feature_text else []),
                category=cat,
                test_name=hdr_raw.get(RawColumn.TEST_NAME.value, "") or None,
                test_num=tn,
                provenance=Provenance(
                    xlsx_rows=[row],
                    doc_section=hdr_raw.get(RawColumn.DOC_SECTION.value, ""),
                    chapter=hdr_raw.get(RawColumn.CHAPTER.value, ""),
                ),
            )
            # 头行概述（源表 C 列『握手数据必稳态』/『不同条件下成立的时序』等）：
            # 它是 TP 的分组标题，不是覆盖 bin。记下列位（C=二级），writer 回写时
            # 原样落回 C 列，roundtrip 后角色/类型零漂移——此前这里多 append 一格空
            # HEADER，导致回读时概述被吞、下游叶子整体错位、类型漂移（14→20）。
            hdr_cell_text = (
                hdr_raw.get(RawColumn.SUB_SUB_FEATURE.value, "")
                or hdr_raw.get(RawColumn.SUB_FEATURE.value, "")
            )
            _hdr_col = (_col_index(RawColumn.SUB_SUB_FEATURE)
                        if hdr_raw.get(RawColumn.SUB_SUB_FEATURE.value)
                        else _col_index(RawColumn.SUB_FEATURE))
            current.coverage_cells.append(CoverageCell(
                cell_id=f"{current.tp_id}#r{row}",
                raw_text=hdr_cell_text,
                source_row=row,
                role=CellRole.HEADER if hdr_cell_text else CellRole.HEADER,
                cell_type=CellType.DESCRIPTOR,   # 分组标题，永远不出 bin
                meta={"_col": _hdr_col} if hdr_cell_text else {},
            ))
            current.raw_rows.append(hdr_raw)
            _seen_tp_ids.add(tp_id)
            tps.append(current)
            row += 1
            continue

        # 叶子行：属于上一个 TP。只要 C / D / F 任一有内容就算有效格
        if current is None:
            row += 1
            continue
        raw = _build_raw(ws, row, col2key)
        current.raw_rows.append(raw)
        current.provenance.xlsx_rows.append(row)

        # 列位：writer 把叶子格原文放 D（sub_sub_feature）、约束放 E；
        # 源表则是 C=二级、D=三级。为让同一份 loader 同时吃『源表』和『回写表』，
        # 取非空的最右一列（sub_sub_sub 退化到 sub_sub 退化到 sub）。
        sub   = raw.get(RawColumn.SUB_FEATURE.value, "")
        subsub = raw.get(RawColumn.SUB_SUB_FEATURE.value, "")
        subsubsub = raw.get(RawColumn.SUB_SUB_SUB_FEATURE.value, "")
        # 源表：叶子格原文在 D(三级=sub_sub_feature)，头行概述在 C(二级)。
        # 回写表：原文统一在 D。故优先级 D > C，空 D 时 C 作为头行原文。
        # 原文列位（源表与回写表统一走 C=二级）：D(三级) 优先，否则 C(二级)。
        # 回写表 writer 把原文写进 C，约束写进 D，所以回读时原文归到 sub_feature 位。
        leaf_text = subsub or sub
        raw[RawColumn.SUB_FEATURE.value] = leaf_text
        test_name = raw.get(RawColumn.TEST_NAME.value, "")
        if test_name and current.test_name is None:
            current.test_name = test_name
        if current.test_num is None:
            tn = _norm_test_num(raw.get(RawColumn.TEST_NUM.value, ""))
            if tn is not None:
                current.test_num = tn

        # ⚠️ 不要用 test_name（F 列，固定是 'func_cov监测'）当覆盖点原文，
        # 否则 IF02 会生成 N 个标为 'func_cov监测' 的假 bin。
        # 源表 / 回写表同构：原文在 C 列且无 D 列内容 → 概述行(HEADER)；否则 LEAF。
        if leaf_text and not subsub:
            _role = CellRole.HEADER
        elif leaf_text.startswith("【头行】"):
            leaf_text = leaf_text[len("【头行】"):]
            _role = CellRole.HEADER
        else:
            _role = CellRole.LEAF
        # 叶子格语义由 CellType 统一判定：配置值/定向用例/组合格/说明，
        # 角色跟着类型走（此前写死 LEAF，导致回读时头行原文被当 LEAF 多算 bin）。
        _type = CellType.classify(
            leaf_text, test_name=test_name or None,
            test_num_kind=TestNumKind.from_value(
                current.test_num if current.test_num is not None
                else raw.get(RawColumn.TEST_NUM.value, "")))
        _role = CellRole.HEADER if leaf_text.startswith("【头行】") else (
            CellRole.HEADER if _type is CellType.DESCRIPTOR and not leaf_text else CellRole.LEAF)
        # 回写表 C 列有原文、D 列可能留空（约束空）；纯空行不生成格，
        # 避免与源表口径相比多出空 descriptor。
        # 纯空行（原文、约束皆无）不生成格：与源表口径对齐，避免回读多出空 descriptor。
        if leaf_text.startswith("【头行】"):
            leaf_text = leaf_text[len("【头行】"):]
        legality = _extract_legality(leaf_text)
        if not leaf_text and not legality:      # 纯空行不生成格
            row += 1; continue
        # 记住原文列位：源表 D(三级) 优先、否则 C(二级)；约束一律进 E。
        # writer 照此落列，loader 回读时用 leaf_text=D or C 还原，类型零漂移。
        _src_col = (_col_index(RawColumn.SUB_SUB_FEATURE)
                    if subsub else _col_index(RawColumn.SUB_FEATURE))
        _meta: dict[str, int] = {"_col": _src_col}
        if legality:
            _meta["_col_legality"] = _col_index(RawColumn.SUB_SUB_SUB_FEATURE)
        current.coverage_cells.append(CoverageCell(
            cell_id=f"{current.tp_id}#r{row}",
            raw_text=leaf_text,
            source_row=row, role=_role, cell_type=_type, legality=legality,
            meta=_meta,
        ))
        row += 1

    # 后处理：推断组件、按 test_num 定型态
    for tp in tps:
        tp.dut_components = infer_components(tp)
        if tp.test_num_kind is TestNumKind.ZERO:
            tp.coverage_driven = True
            tp.directed = False
        # 回填 provenance 文档信息（取首行 raw）
        if tp.raw_rows:
            r0 = tp.raw_rows[0]
            if not tp.provenance.doc_section:
                tp.provenance.doc_section = r0.get(RawColumn.DOC_SECTION.value, "")
            if not tp.provenance.chapter:
                tp.provenance.chapter = r0.get(RawColumn.CHAPTER.value, "")

    return Ontology(version=version, spec_rev="", xlsx_rev=path, testpoints=tps)


# 约束关键词只在『非配置枚举格』里生效：配置值形如 13'b… / 0x… / bit[…]
# 里出现『模式』『独占』是描述寄存器语义，不是时序约束。
_LEGALITY_HINT_RE = re.compile(r"仅.+?允许|仅.+?可|不允许|禁止|排他|独占")
_CONFIG_VALUE_RE = re.compile(
    r"^\s*(13'?b|0x|0b|\d+\s*'[bB])"          # 13'b… / 0x… / 32'b…
    r"|bit\s*\[|bit\["                          # bit[12:0]
)


_COL_MAP = {RawColumn.SUB_FEATURE: 3, RawColumn.SUB_SUB_FEATURE: 4,
            RawColumn.SUB_SUB_SUB_FEATURE: 5, RawColumn.TEST_NAME: 6,
            RawColumn.TEST_NUM: 7}


def _col_index(key: RawColumn) -> int:
    return _COL_MAP[key]


def _extract_legality(text: str) -> str:
    """从叶子格原文抠出『仅…允许』类约束；配置枚举值一律不算约束。"""
    if _CONFIG_VALUE_RE.search(text):
        return ""
    m = _LEGALITY_HINT_RE.search(text)
    return m.group(0) if m else ""
