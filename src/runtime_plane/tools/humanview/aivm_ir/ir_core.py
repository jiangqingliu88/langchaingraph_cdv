from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
import json
import re
from typing import Any


# ============================================================
#  纯 Enum：内部状态，永不对外透出名字，序列化由 _json_default 接管
# ============================================================
class Category(Enum):
    CR = "CR"; IF = "IF"; C = "C"; F = "F"
    BP = "BP"; BO = "BO"; R = "R"; E = "E"; P = "P"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_code(cls, code: str) -> "Category":
        """按 '-CR01-' 这种中间码解析；失败返回 UNKNOWN。"""
        if not code:
            return cls.UNKNOWN
        cand = code.upper().strip().strip("-")
        for m in cls:
            if m is not cls.UNKNOWN and (cand == m.value or cand.startswith(m.value + ".")):
                return m
        return cls.UNKNOWN


class DimType(Enum):
    CATEGORICAL = "categorical"
    ORDINAL = "ordinal"
    NUMERIC = "numeric"
    SET = "set"
    COMPOSITE = "composite"


class Status(Enum):
    CONFIRMED = "confirmed"
    CANDIDATE = "candidate"
    SUSPECT = "suspect"
    REDUNDANT = "redundant"
    MISSING = "missing"


class ExecutionMode(Enum):
    DIRECTED = "directed"
    COVERAGE_DRIVEN = "coverage_driven"
    HYBRID = "hybrid"


class TestNumKind(Enum):
    ZERO = "zero"
    POSITIVE_INT = "positive_int"
    FORMULA = "formula"
    EMPTY = "empty"
    OTHER = "other"

    @classmethod
    def from_value(cls, raw: Any) -> "TestNumKind":
        if raw is None:
            return cls.EMPTY
        s = str(raw).strip()
        if s == "":
            return cls.EMPTY
        if s == "0":
            return cls.ZERO
        if s.startswith("="):
            return cls.FORMULA
        try:
            return cls.POSITIVE_INT if int(s) > 0 else cls.OTHER
        except ValueError:
            return cls.OTHER


# ============================================================
#  叶子格的角色与类型：解决「头行分组文本」与「配置枚举值」的语义歧义
# ============================================================
class CellRole(Enum):
    """格子在源表里的结构角色（由位置决定，不随文本变）。

    HEADER   = TP 头行自带的概述格（如 IF02 头行『不同条件下成立的时序』）。
               它是分组标题，默认不算覆盖 bin，但可被编译器显式 opt-in。
    LEAF    = 头行之下、D/C 列的真实枚举格，是 M1 的默认覆盖点来源。
    """
    HEADER = "header"
    LEAF = "leaf"


# ============================================================
#  叶子格类型识别用的『纯文本规则』。放模块级而不放 Enum 类体里：
#  Enum 元类会把类作用域的赋值也登记成 __members__，导致
#  `cls._CONFIG_PREFIX` 取到的是 CellType 成员对象而非元组（startswith 直接 TypeError）。
# ============================================================
_CFG_PREFIX: tuple[str, ...] = (
    "13'b", "13b'", "0x", "0b", "cfg_", "mode_", "tile_mode",
    "spad_mode", "mx_", "excl", "bit[", "bit [",
)
_CFG_WORDS: frozenset[str] = frozenset(
    {"spad", "tile", "exclusive", "独占", "独热", "模式", "默认值"}
)
_LEGAL_WORDS: tuple[str, ...] = (
    "仅", "不允许", "禁止", "排他", "独占访问", "并行执行",
)


class CellType(Enum):
    """格子的业务语义（由文本特征推断，loader 自动打标）。
      同一张表里混着三类东西——
        * 约束组合格 『start_id0 先于…仅GLSU/LLSU load store并行允许』
        * 配置枚举格  『13'b0_0000_0000_0001』（C02 的 tile 模式表）
        * 定向用例格  『glsu_cfg_drv_base』（F 类，test_num=1）
      若都用同一个 CoverageCell 处理，validate 的『仅…允许』约束识别会把
      配置枚举行误报成约束缺失，M1 也会把配置值当成待覆盖的时序组合。

    打标后：validate 只审 CONSTRAINT_COMBO；M1 只对 CONSTRAINT_COMBO /
    DIRECTED_CASE 出 bin，CONFIG_ENUM 单独走『配置穷举覆盖』通道。
    """
    CONSTRAINT_COMBO = "constraint_combo"   # 时序/协议组合，含（或不含）约束
    CONFIG_ENUM = "config_enum"            # 配置域枚举值（13'b… / 0x… / 模式名）
    DIRECTED_CASE = "directed_case"        # 已命名的定向用例
    DESCRIPTOR = "descriptor"               # 纯说明性文字，不出点

    # 规则常量放在类上仅为『命名空间归属』；它们是普通元组/集合，
    # 但 Enum 元类会把类作用域里的赋值也登记成成员，所以 classify 里统一走
    # 模块级常量 _CFG_PREFIX / _CFG_WORDS / _LEGAL_WORDS，避免拿到 Enum 成员。
    _CONFIG_PREFIX = _CFG_PREFIX
    _CONFIG_EQ_WORDS = _CFG_WORDS
    _LEGALITY_WORDS = _LEGAL_WORDS

    @classmethod
    def classify(cls, raw_text: str, *, test_name: str | None = None,
                 test_num_kind: "TestNumKind | None" = None) -> "CellType":
        t = (raw_text or "").strip()
        tn = (test_name or "").strip()

        # 1) 空 = 说明性占位（头行分组标题走这里，除非调用方显式覆盖）
        if not t:
            return cls.DESCRIPTOR

        # 2) 形如配置域枚举值：位串 / 十六进制 / cfg_xxx / mx_xxx / bit[…]
        if t.startswith(_CFG_PREFIX) or re.match(r"^\d+'[bBhHdD]", t):
            return cls.CONFIG_ENUM
        if re.match(r"^[0-9A-Fa-f]+h\b", t) or re.match(r"^0[0-7]+b", t):
            return cls.CONFIG_ENUM
        low = t.lower()
        if any(w in low for w in _CFG_WORDS) and re.search(r"\b(bit|13|mode|spad|tile|mx_)", low):
            return cls.CONFIG_ENUM

        # 3) 带约束关键词的组合格
        if any(w in t for w in _LEGAL_WORDS):
            return cls.CONSTRAINT_COMBO

        # 4) 已命名用例（test_name 像 glsu_cfg_drv_base / xxx_para）
        if tn and tn not in ("func_cov监测",) and "_" in tn:
            return cls.DIRECTED_CASE
        if "_" in t and re.search(r"(base|para|drv|inst|mix)", t.lower()):
            return cls.DIRECTED_CASE

        # 5) 显式 test_num：正整数=定向用例；0=覆盖驱动的组合描述
        if test_num_kind is TestNumKind.ZERO:
            return cls.CONSTRAINT_COMBO
        if test_num_kind is TestNumKind.POSITIVE_INT:
            return cls.DIRECTED_CASE

        # 6) 剩余带『先于/后于/同时』等时序词 = 组合格
        if re.search(r"先于|后于|同时|start_|done_|valid|ready|raw|war|waw", t.lower()):
            return cls.CONSTRAINT_COMBO

        return cls.DESCRIPTOR

    def yields_cover_bin(self) -> bool:
        """该类型是否直接贡献一个覆盖 bin。"""
        return self is CellType.CONSTRAINT_COMBO

    def yields_config_cover(self) -> bool:
        """该类型是否贡献『配置域穷举覆盖』（单独计数，不走组合 bin）。"""
        return self is CellType.CONFIG_ENUM

    def yields_directed_case(self) -> bool:
        return self is CellType.DIRECTED_CASE


# ============================================================
#  str Enum：必须与外部字符串（dict 键 / spec 文本 / xlsx 列名）直接比较
# ============================================================
class Component(str, Enum):
    GLSU = "glsu"; LLSU = "llsu"; NIU = "niu"
    VPU = "vpu"; MPU = "mpu"; LMEM = "lmem"

    @classmethod
    def all_values(cls) -> tuple[str, ...]:
        return tuple(m.value for m in cls if m is not cls.__members__.get("LMEM") or True)


class RawColumn(str, Enum):
    """xlsx 列的稳定键。writer / loader 只准通过这里引用，禁止出现字面量列名。"""
    SEQ = "seq"
    FEATURE = "feature"                       # A 列：TP 编号 / 一级分类中文
    SUB_FEATURE = "sub_feature"               # C 列
    SUB_SUB_FEATURE = "sub_sub_feature"       # D 列
    SUB_SUB_SUB_FEATURE = "sub_sub_sub_feature"  # E 列（预留）
    TEST_NAME = "test_name"                   # F 列
    TEST_NUM = "test_num"                     # G 列
    DOC_SECTION = "doc_section"               # I 列
    CHAPTER = "chapter"                       # J 列

    @classmethod
    def xlsx_header_map(cls) -> dict[str, "RawColumn"]:
        """表头 -> 稳定键（loader 用，列改名只改这里）。
        所有 key 已做『全角括号→半角、去空格』归一化，与 _discover_columns
        里对表头做的 normalize 完全一致，避免『（可选）』匹配不上。"""
        raw: list[tuple[str, "RawColumn"]] = [
            # seq
            ("序号", cls.SEQ), ("feature 编号", cls.SEQ), ("feature编号", cls.SEQ),
            # feature（源表 A 列 = TP 编号+一级分类）
            ("feature 提取", cls.FEATURE), ("feature提取", cls.FEATURE),
            ("feature", cls.FEATURE), ("一级分类", cls.FEATURE),
            # sub_feature
            ("sub_feature（可选）", cls.SUB_FEATURE), ("sub_feature", cls.SUB_FEATURE),
            ("二级分类", cls.SUB_FEATURE),
            ("subfeature", cls.SUB_FEATURE),
            # sub_sub_feature：源表双表头写成『sub_sub_feature（可选）』与
            # 『sub_sub_feature（可选）』两行叠在一起，归一化后同为
            # 'sub_sub_feature（可选）'，用 list 保证首匹配稳定，且兜底到『三级分类』。
            ("sub_sub_feature（可选）", cls.SUB_SUB_FEATURE), ("sub_sub_feature", cls.SUB_SUB_FEATURE),
            ("三级分类", cls.SUB_SUB_FEATURE),
            # sub_sub_sub_feature
            ("sub_sub_sub_feature（可选）", cls.SUB_SUB_SUB_FEATURE),
            ("sub_sub_sub_feature", cls.SUB_SUB_SUB_FEATURE), ("四级分类", cls.SUB_SUB_SUB_FEATURE),
            # test_name
            ("testname", cls.TEST_NAME), ("test_name", cls.TEST_NAME),
            ("用例名", cls.TEST_NAME), ("test name", cls.TEST_NAME),
            # test_num
            ("testnum", cls.TEST_NUM), ("test_num", cls.TEST_NUM),
            ("test个数", cls.TEST_NUM), ("test 个数", cls.TEST_NUM),
            # doc_section
            ("doc section", cls.DOC_SECTION), ("doc_section", cls.DOC_SECTION),
            ("相关文档", cls.DOC_SECTION),
            # chapter
            ("章节", cls.CHAPTER), ("chapter", cls.CHAPTER), ("摘取位置", cls.CHAPTER),
        ]
        norm = lambda s: s.strip().lower().replace("（", "(").replace("）", ")").replace(" ", "")
        return {norm(k): v for k, v in raw}


# ============================================================
#  数据模型
# ============================================================
@dataclass
class Provenance:
    doc_section: str = ""
    chapter: str = ""
    xlsx_rows: list[int] = field(default_factory=list)
    spec_ref: str | None = None


@dataclass
class DimensionValue:
    value: str                 # 规范化短码，数据驱动，不做枚举
    raw_text: str              # 源表原文；为空表示该格是推导格，不生成覆盖点
    source_row: int = 0

    def is_material(self) -> bool:
        """有原文 = 源表里真实存在的一格 = 值得生成覆盖点。"""
        return self.raw_text.strip() != ""


@dataclass
class LegalityRule:
    """跨维度约束。M1 只在 '显式 dim 建模' 不够时用；优先用 CoverageCell.legality。"""
    when: dict[str, str]
    constraint: str
    raw_text: str = ""
    source_row: int = 0


@dataclass
class Dimension:
    dim_id: str
    name: str
    dim_type: DimType
    value_domain: list[DimensionValue] = field(default_factory=list)
    semantics: str = ""
    legality: list[LegalityRule] = field(default_factory=list)
    status: Status = Status.CANDIDATE
    related_coverage: list[str] = field(default_factory=list)

    def material_values(self) -> list[DimensionValue]:
        return [dv for dv in self.value_domain if dv.is_material()]


@dataclass
class CoverageCell:
    """源表里的『一个格子』= 一个候选覆盖点。M1 的主循环对象。

    为什么需要它：IF02 源表每个 D 格已经是一个 (start_order, done_order, legality)
    的完整组合，原文即真理。让 M1 对 Dimension 做笛卡尔积再筛，会把 4 点膨胀成 8 点；
    直接拿 CoverageCell 走，就天然是源表格子数，且 legality 跟着格子走，无需约束求解。

    三通道（由 role + cell_type 共同决定）：
      * CONSTRAINT_COMBO + LEAF   -> 覆盖 bin（IF02 那 3~4 个时序组合）
      * CONFIG_ENUM               -> 配置域穷举覆盖（C02 的 13 个 tile 模式，单独计数）
      * DIRECTED_CASE             -> 定向用例（F 类 glsu_cfg_drv_base 之类）
      * DESCRIPTOR / HEADER       -> 不出点，只做可追溯的上下文
    """
    cell_id: str = ""                    # 例如 "NPU_V2-CMDSCHED-IF02#r11"
    raw_text: str = ""
    source_row: int = 0
    role: CellRole = CellRole.LEAF       # 结构角色：头行 or 叶子
    cell_type: CellType = CellType.DESCRIPTOR  # 业务语义，loader 用 CellType.classify 打标
    legality: str = ""                   # 格子自带的『仅…允许』原文，空=无约束
    meta: dict[str, int] = field(default_factory=dict)  # writer 记忆列位，保证 roundtrip 守恒
    dim_bindings: dict[str, str] = field(default_factory=dict)  # dim_id -> value短码（建模后回填）

    def is_material(self) -> bool:
        """有原文才算『源表里真实存在的一格』（头行标题也算 material，只是默认不出 bin）。"""
        return self.raw_text.strip() != ""

    def is_cover_bin(self) -> bool:
        """M1 默认会出的覆盖 bin：组合格 + 叶子角色。"""
        return self.cell_type is CellType.CONSTRAINT_COMBO and self.role is CellRole.LEAF

    def is_config_enum(self) -> bool:
        return self.cell_type is CellType.CONFIG_ENUM and self.is_material()

    def is_directed_case(self) -> bool:
        return self.cell_type is CellType.DIRECTED_CASE and self.is_material()

    def is_header(self) -> bool:
        return self.role is CellRole.HEADER

    def as_cover_label(self) -> str:
        """落到覆盖点的可读标签；配置枚举格用原文（13'b…），组合格用原文摘要。"""
        return self.raw_text.strip()


@dataclass
class TestPointIR:
    tp_id: str = ""                         # 内部唯一 id（同名锚点行追加 #2/#3）
    orig_id: str = ""                        # 源表 A 列原文 id，与 xlsx 逐格对齐
    feature_text: str = ""                  # 一级分类整段原文，不复算、不切词
    feature_path: list[str] = field(default_factory=list)  # 可读分层标签（纯 str）
    category: Category = Category.UNKNOWN   # 权威专题，由 id 解析，不靠文本猜
    dut_components: list[str] = field(default_factory=list)  # Component.value 池
    dimensions: list[Dimension] = field(default_factory=list)
    coverage_cells: list[CoverageCell] = field(default_factory=list)  # 叶子格（M1 主输入）
    test_name: str | None = None
    test_num: str | int | None = None       # 归一化后：str 或 int，None 表示真·空
    expand_count: int | None = None
    directed: bool = True
    coverage_driven: bool = False
    checks: list[str] = field(default_factory=list)
    coverage_points: list[str] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)
    status: Status = Status.CANDIDATE
    raw_rows: list[dict[str, str]] = field(default_factory=list)

    @property
    def test_num_kind(self) -> TestNumKind:
        return TestNumKind.from_value(self.test_num)

    @property
    def execution_mode(self) -> ExecutionMode:
        if self.test_num_kind is TestNumKind.ZERO:
            return ExecutionMode.COVERAGE_DRIVEN
        if self.coverage_driven and not self.directed:
            return ExecutionMode.COVERAGE_DRIVEN
        if self.coverage_driven and self.directed:
            return ExecutionMode.HYBRID
        return ExecutionMode.DIRECTED

    # ---- 供 M1 用的三通道视图（role + cell_type 双重过滤）----
    def material_cells(self) -> list[CoverageCell]:
        """所有有原文的格（含头行标题、配置枚举、说明），用于 roundtrip 守恒校验。"""
        return [c for c in self.coverage_cells if c.is_material()]

    def cover_bin_cells(self) -> list[CoverageCell]:
        """约束组合 + 叶子角色 = M1 默认会出的覆盖 bin。"""
        return [c for c in self.coverage_cells if c.is_cover_bin()]

    def config_enum_cells(self) -> list[CoverageCell]:
        """配置域枚举格（C02 的 tile 模式表），单独走『配置穷举覆盖』通道。"""
        return [c for c in self.coverage_cells if c.is_config_enum()]

    def directed_case_cells(self) -> list[CoverageCell]:
        """已命名定向用例格（F 类 xxx_base / xxx_para）。"""
        return [c for c in self.coverage_cells if c.is_directed_case()]

    def header_cells(self) -> list[CoverageCell]:
        return [c for c in self.coverage_cells if c.is_header()]

    def coverage_point_count(self) -> int:
        """覆盖点数量：组合 bin > 配置枚举 > test_num > 维度乘积下界。
        注意：头行标题（HEADER/DESCRIPTOR）永远不计入。"""
        bins = self.cover_bin_cells()
        if bins:
            return len(bins)
        cfg = self.config_enum_cells()
        if cfg:
            return len(cfg)
        if self.test_num_kind is TestNumKind.POSITIVE_INT:
            return int(self.test_num)  # type: ignore[arg-type]
        if self.dimensions:
            import math
            return math.prod(max(1, len(d.material_values())) for d in self.dimensions)
        return 0

    def cell_type_breakdown(self) -> dict[str, int]:
        from collections import Counter
        return dict(Counter(c.cell_type.value for c in self.coverage_cells))


# ============================================================
#  序列化：纯 Enum 走 .value，str-Enum 因是 str 子类自动落字符串
# ============================================================
def _json_default(o: Any) -> Any:
    if isinstance(o, Enum):
        return o.value
    if hasattr(o, "__dataclass_fields__"):
        return asdict(o)
    return str(o)


@dataclass
class Ontology:
    version: str = "0.0.0"
    spec_rev: str = ""
    xlsx_rev: str = ""
    testpoints: list[TestPointIR] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, default=_json_default)

    def to_dict(self) -> dict:
        return asdict(self, dict_factory=dict)

    def find_tp(self, tp_id: str) -> TestPointIR | None:
        """按 tp_id 取首个命中（兼容单例用法）。不合并口径下同名 id 可多次出现，
        需要全量请改用 find_tps。"""
        hit = self.find_tps(tp_id)
        return hit[0] if hit else None

    def find_tps(self, tp_id: str) -> list[TestPointIR]:
        """返回该 tp_id 的全部 TP。源表 BO02-F02 / R02(RD-RR) 同 id 占多行，
        不合并口径下每一行都是独立 TP，必须返回 list。"""
        return [tp for tp in self.testpoints if tp.tp_id == tp_id or tp.orig_id == tp_id]

    def tp_count(self) -> int:
        """TP 数 = 源表 A 列锚点行数（不去重），与 PM 人工计数对齐。"""
        return len(self.testpoints)

    def category_groups(self) -> dict[Category, list[TestPointIR]]:
        groups: dict[Category, list[TestPointIR]] = {}
        for tp in self.testpoints:
            groups.setdefault(tp.category, []).append(tp)
        return groups

    def total_coverage_points(self, *, material_only: bool = True) -> int:
        """material_only=True：只数『会出覆盖 bin 的组合格』，不含头行/说明/配置枚举。
        material_only=False：组合 bin + 配置枚举 + 定向用例下界（总工作量上界）。"""
        if material_only:
            return sum(len(tp.cover_bin_cells()) for tp in self.testpoints)
        return sum(tp.coverage_point_count() for tp in self.testpoints)

    def total_config_enums(self) -> int:
        return sum(len(tp.config_enum_cells()) for tp in self.testpoints)

    def summary(self) -> dict:
        from collections import Counter
        return {
            "tp_count": len(self.testpoints),
            "by_category": dict(Counter(tp.category.value for tp in self.testpoints)),
            "by_mode": dict(Counter(tp.execution_mode.value for tp in self.testpoints)),
            "cover_bins": sum(len(tp.cover_bin_cells()) for tp in self.testpoints),
            "config_enums": self.total_config_enums(),
            "material_cells": sum(len(tp.material_cells()) for tp in self.testpoints),
            "directed_estimate": sum(
                tp.coverage_point_count() for tp in self.testpoints
                if tp.execution_mode is not ExecutionMode.COVERAGE_DRIVEN),
        }
