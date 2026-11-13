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
    if tp_id:
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


def discover_column_headers(ws) -> list[dict]:
    """源表表头 → `[{key, label, sub_label}]`（按列序，只收能映射的列）。

    **GUI 的表头按这份走**，不写死。示例表的表头是两行：

        第 2 行：序号 / Feature 提取 / Sub_Feature（可选）/ Sub_Sub_Feature（可选）/ …
        第 3 行：feature 编号…（图例）/ 一级分类 / 二级分类 / 三级分类 / 四级分类 / …

    第 2 行是"headtitle"，第 3 行是中文释义。D/E 两列在第 2 行**同名**
    （都是 `Sub_Sub_Feature（可选）`），靠第 3 行的「三级分类 / 四级分类」
    区分；A 列第 3 行是一整段图例（含换行），不当释义拼进去。
    """
    col_map = _discover_columns(ws)
    out: list[dict] = []
    for col, raw in sorted(col_map.items()):
        top = re.sub(r"\s+", " ", str(ws.cell(2, col).value or "")).strip()
        sub = re.sub(r"\s+", " ", str(ws.cell(3, col).value or "")).strip()
        # 图例（多行/过长）不是释义 —— 不要拼进表头
        if "\n" in str(ws.cell(3, col).value or "") or len(sub) > 20:
            sub = ""
        label = top or sub or raw.value
        if top and sub and sub != top:
            label = f"{top}·{sub}"
        out.append({"key": raw.value, "label": label, "sub_label": sub})
    return out


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


def _extract_legality(text: str) -> str:
    """抠出叶子格自带的『仅…允许/禁止』约束原文；无则空，空=无额外约束。"""
    m = re.search(r"仅.+?允许|仅.+?可|不允许|禁止|排他|独占", text or "")
    return m.group(0) if m else ""


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
    _C2  = next((c for c,k in col2key.items() if k is RawColumn.SUB_FEATURE), 3)
    _C3  = next((c for c,k in col2key.items() if k is RawColumn.SUB_SUB_FEATURE), 4)
    _C4  = next((c for c,k in col2key.items() if k is RawColumn.SUB_SUB_SUB_FEATURE), 5)

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
        """锚点 = A 列本格以合法 TP id 开头（严格模式）。

        只看 A 列，不走 _anchor_text 的合并回退，也不读 B/C/D 文本，
        彻底排除『叶子行被误判成新 TP』。A 格为多行时（R01/R02：首行 id + 续行
        '(回归加上RR…)'），以首个换行前的首行做 TP_ID_RE 校验。
        """
        raw = ws.cell(row=row, column=ANCHOR_COL).value
        if raw is None:
            return ""
        first = str(raw).split("\n")[0].strip()
        if not TP_ID_RE.match(first):
            return ""
        return re.sub(r"\s+", " ", str(raw)).strip()


    # A 列连续同 id（BO02-F02 × 4、R02 × 4）各算独立 TP：tp_id 保留原文，
    # 内部索引允许同名；区分靠 source_row / cell_id。
    _seen_same_id: dict[str, int] = {}

    @staticmethod
    def _anchor_id(s: str, *, keep_suffix: bool = False) -> str | None:
        """A 列锚点 -> tp_id。

        keep_suffix=False（解析专题/分组）：只取字母数字段，
            例 NPU_V2-CMDSCHED-R02（RD-RR）\n(回归…) -> NPU_V2-CMDSCHED-R02
        keep_suffix=True（建 TP，与源表逐格对齐）：保留首个空白前的原文、
        换行压空格，例 -> NPU_V2-CMDSCHED-BO02-F02。同族多行文本字节一致，
        可稳定回读命中。
        """
        toks = (s or "").split()
        if not toks or not TP_ID_RE.match(toks[0]):
            return None
        if keep_suffix:
            return str(s).split("\n")[0].strip()   # 与源表 A 列首行逐字一致
        # id = 首个空白前的整段。允许末尾 -F / -RR 等功能域/变体后缀，
        # 但停在全角括号（R02（RD-RR））与空白处，保证与源表 A 列逐格一致。
        # id = 首个空白前的整段（含全角括号，如 R02（RD-RR）），
        # 换行压成空格后再取第一段，保证同族多行文本字节一致。
        # id = A 列首个空白前的整段：保留 -F02、R02（RD-RR）这类后缀，
        # 只在换行/全角括号后截断，保证同族多行文本字节一致、与源表逐格对齐。
        head = re.sub(r"\s+", " ", (s or "").split("\n")[0].strip())
        # id = 首个 ASCII 空白前的整段，保留全角括号后缀（R02（RD-RR）），
        # 只在换行或 ASCII 空白处截断；同族多行文本字节一致，与源表 A 列逐格对齐。
        m = re.match(r"^(NPU_V2-CMDSCHED-[^\x00-\x7f\s]*(?:[^\s（(（]*)?)", head)
        if m and "（" in head:
            # 保留到首个全角左括号（含括号前缀）
            pre = head.split("（")[0]
            core = re.match(r"^(NPU_V2-CMDSCHED-.*)$", pre)
            return pre if core else None
        return m.group(1) if m else None


    # 数据起点：锚点列里第一个像 TP id 的行。源表=行4，writer 回放=行2。
    def _feat_text_local(row: int, tp_id: str) -> str:
        """往返守恒：feature_text 一律取 B列(Feature提取)原文，与 writer 回写位置一致。
        B列空时（BO02/R02 等 A列兼承载描述）退回 id 之后与 C列拼接。"""
        b = _cell(ws, row, FEAT_COL)
        if b and not _anchor_id(b):
            return b
        a = _anchor_text(ws, row, ANCHOR_COL)
        rest = a.replace(str(tp_id), " ", 1) if tp_id and a.startswith(str(tp_id)) else ""
        rest = re.sub(r"^[:：\\s]+", "", rest).strip()
        ccol = next((c for c, k in col2key.items() if k is RawColumn.SUB_FEATURE), 3)
        return rest or _cell(ws, row, ccol)

    start_row = 2
    for probe in range(1, min(ws.max_row, 8) + 1):
        if _anchor_id(_anchor(probe)):
            start_row = probe
            break

    tps: list[TestPointIR] = []
    current: TestPointIR | None = None
    row = start_row

    while row <= ws.max_row:
        anchor = _anchor(row)
        # 锚点 = A 列合法 TP id（严格模式，只看 A 列，杜绝叶子行误建 TP）
        tok0 = _anchor_id(anchor, keep_suffix=True)
        _orig_id = tok0
        if tok0:
            _seen_same_id[tok0] = _seen_same_id.get(tok0, 0) + 1
            if _seen_same_id[tok0] > 1:
                tok0 = f"{tok0}#{_seen_same_id[tok0]}"   # 内部去重键；原文存 orig_id
        is_header = tok0 is not None

        # ========== 路径 A：新 TP 头行 ==========
        if is_header:
            # 合计/汇总行（"...-P06-RR total num"、=SUM(...)）不算 TP
            _trail = re.sub(r"\s+", " ", anchor[len(_orig_id):].strip().lower())
            if re.search(r"^(total|合计|汇总|sub\s*total)", _trail) or "=sum" in anchor.lower():
                row += 1
                continue

            tp_id = tok0
            feature_text = _feat_text_local(row, _orig_id)
            cat = infer_category(_orig_id)
            hdr_raw = _build_raw(ws, row, col2key)
            tn = _norm_test_num(hdr_raw.get(RawColumn.TEST_NUM.value, ""))
            current = TestPointIR(
                tp_id=tok0,
                orig_id=_orig_id or tok0,
                feature_text=feature_text,
                feature_path=[cat.value] + ([feature_text] if feature_text else []),
                category=cat,
                test_num=tn,
                provenance=Provenance(
                    xlsx_rows=[row],
                    doc_section=hdr_raw.get(RawColumn.DOC_SECTION.value, ""),
                    chapter=hdr_raw.get(RawColumn.CHAPTER.value, ""),
                ),
            )
            current.raw_rows.append(hdr_raw)
            # 头行自带的 C/D/E 文字（如『握手数据必稳态』『spad』『C6 3』）
            # 也要登记成一格 HEADER，否则源表读入时漏收、写回后再读却收进来了，
            # 导致 roundtrip 叶子集合不一致。与叶子格共用 classify，仅 role 不同。
            _hdr_txt = (hdr_raw.get(RawColumn.SUB_SUB_FEATURE.value, "")
                        or hdr_raw.get(RawColumn.SUB_SUB_SUB_FEATURE.value, "")
                        or hdr_raw.get(RawColumn.SUB_FEATURE.value, ""))
            if _hdr_txt.strip():
                _hcol = (_C3 if hdr_raw.get(RawColumn.SUB_SUB_FEATURE.value, "").strip()
                         else (_C4 if hdr_raw.get(RawColumn.SUB_SUB_SUB_FEATURE.value, "").strip()
                               else _C2))
                current.coverage_cells.append(CoverageCell(
                    cell_id=f"{tok0}#r{row}h",
                    raw_text=_hdr_txt,
                    source_row=row,
                    role=CellRole.HEADER,
                    cell_type=CellType.classify(_hdr_txt, test_name=current.test_name,
                                                test_num_kind=current.test_num_kind),
                    meta={"col": _hcol, "header_owned": True},  # 由头行C列承载，leaf不再另写
                ))
            tps.append(current)
            row += 1
            continue   # 头行本身不再走叶子分支

        # ========== 路径 B：非锚点行 → 归属 current 的叶子格 ==========
        # 此前这里被 `continue` 短路，导致叶子段变成死代码 → material=0。
        row += 1
        if current is None:      # 表格前部孤儿说明行，安全跳过
            continue
        raw = _build_raw(ws, row - 1, col2key)
        current.raw_rows.append(raw)
        current.provenance.xlsx_rows.append(row - 1)
        sub     = raw.get(RawColumn.SUB_FEATURE.value, "")
        subsub  = raw.get(RawColumn.SUB_SUB_FEATURE.value, "")
        subsubsub = raw.get(RawColumn.SUB_SUB_SUB_FEATURE.value, "")
        if not current.test_name:
            current.test_name = raw.get(RawColumn.TEST_NAME.value, "") or None
        if current.test_num is None:
            _tn = _norm_test_num(raw.get(RawColumn.TEST_NUM.value, ""))
            if _tn is not None:
                current.test_num = _tn
        # 源表真实布局（列位由自发现确认）：
        #   C(二级) = 概述/分组标题，如『不同条件下成立的时序』『握手数据必稳态』
        #   D(三级) = 真实组合格，如『start_id0 先于…,done_id0 后于…』
        #   E(四级) = 该格约束备注，如『仅GLSU/LLSU load store并行执行运行允许』
        leaf_text = subsub or subsubsub or sub
        if not leaf_text.strip():
            continue
        # C 列(二级)默认是概述，但若本身就是时序组合句（先于/后于/同时/start_/done_），
        # 则按 LEAF 出覆盖 bin——源表 IF01 握手顺序就写在 C 列。纯说明句才留 HEADER。
        _is_seq = bool(re.search(r"先于|后于|同时|start_|done_|valid|ready", leaf_text))
        role = CellRole.HEADER if (not subsub and sub and not _is_seq) else CellRole.LEAF
        ctype = CellType.classify(leaf_text, test_name=current.test_name, test_num_kind=current.test_num_kind)
        current.coverage_cells.append(CoverageCell(
            cell_id=f"{current.tp_id}#r{row-1}",
            raw_text=leaf_text,
            source_row=row - 1,
            role=role,
            cell_type=ctype,
            legality=_extract_legality(leaf_text) if role is CellRole.LEAF else "",
            meta={"col": (_C3 if subsub else (_C4 if subsubsub else _C2))},
        ))

    for tp in tps:
        tp.dut_components = infer_components(tp)
        if tp.test_num_kind is TestNumKind.ZERO:
            tp.coverage_driven = True
            tp.directed = False
        if tp.raw_rows:
            r0 = tp.raw_rows[0]
            if not tp.provenance.doc_section:
                tp.provenance.doc_section = r0.get(RawColumn.DOC_SECTION.value, "")
            if not tp.provenance.chapter:
                tp.provenance.chapter = r0.get(RawColumn.CHAPTER.value, "")
    import sys
    res = Ontology(version=version, spec_rev="", xlsx_rev=path, testpoints=tps)
    import sys as __s, collections as __c
    return res
