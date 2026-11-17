"""词表与取值归一 —— 归一化的唯一依据。

把「人写的宽松写法」收敛成唯一的机器坐标，都集中在这里：
  · 方法别名（随机 / RANDOM → RND）
  · 检查别名（白盒检查 → CHECK-WBOX）
  · 关系词（联动 / linkage → linkage）
  · 交叉级别（★ / 必需 / required → required）
  · 专题优先级（p0 / 0 / P0 → P0）
  · 交叉矩阵键的分隔符（长度×模式 / 长度*模式）

schema 层因此可以保持严格（只认 5 个方法代号、只认 CHECK-XXX），
下游则不必到处写 fallback。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# ════════════════════════════════════════════════════════════
# L5 方法
# ════════════════════════════════════════════════════════════

METHOD_ORDER: Tuple[str, ...] = ("D", "RND", "G", "RPLY", "SPCL")

METHOD_NAMES: Dict[str, str] = {
    "D": "定向", "RND": "随机", "G": "组合", "RPLY": "重放", "SPCL": "专项",
}

METHOD_ALIASES: Dict[str, str] = {
    "D": "D", "DIRECT": "D", "DIRECTED": "D", "定向": "D",
    "RND": "RND", "RANDOM": "RND", "随机": "RND",
    "G": "G", "COMB": "G", "COMBINATION": "G", "组合": "G", "笛卡尔": "G",
    "RPLY": "RPLY", "REPLAY": "RPLY", "重放": "RPLY",
    "SPCL": "SPCL", "SPECIAL": "SPCL", "专项": "SPCL", "变异": "SPCL",
}

# ════════════════════════════════════════════════════════════
# L6 检查
# ════════════════════════════════════════════════════════════

CHECK_ORDER: Tuple[str, ...] = ("CHECK-FUNC", "CHECK-WBOX", "CHECK-PERF")

CHECK_NAMES: Dict[str, str] = {
    "CHECK-FUNC": "功能检查", "CHECK-WBOX": "白盒检查", "CHECK-PERF": "性能检查",
}

CHECK_ALIASES: Dict[str, str] = {
    "CHECK-FUNC": "CHECK-FUNC", "FUNC": "CHECK-FUNC", "FUNCTIONAL": "CHECK-FUNC",
    "功能": "CHECK-FUNC", "功能检查": "CHECK-FUNC", "功能正确": "CHECK-FUNC",
    "CHECK-WBOX": "CHECK-WBOX", "WBOX": "CHECK-WBOX", "WHITEBOX": "CHECK-WBOX",
    "白盒": "CHECK-WBOX", "白盒检查": "CHECK-WBOX", "白盒状态": "CHECK-WBOX",
    "CHECK-PERF": "CHECK-PERF", "PERF": "CHECK-PERF", "PERFORMANCE": "CHECK-PERF",
    "性能": "CHECK-PERF", "性能检查": "CHECK-PERF", "性能指标": "CHECK-PERF",
}

# ════════════════════════════════════════════════════════════
# L4 字段类型
# ════════════════════════════════════════════════════════════

FIELD_TYPES: Tuple[str, ...] = ("enum", "range", "set", "weighted", "linkage")

FIELD_TYPE_NAMES: Dict[str, str] = {
    "enum": "枚举型", "range": "范围型", "set": "集合型",
    "weighted": "加权型", "linkage": "联动型",
}

# ════════════════════════════════════════════════════════════
# 维度内部字段关系
# ════════════════════════════════════════════════════════════

RELATION_ALIASES: Dict[str, str] = {
    "INDEPENDENT": "independent", "并列": "independent", "独立": "independent",
    "NONE": "independent",
    "LINKAGE": "linkage", "联动": "linkage", "关联": "linkage", "COUPLED": "linkage",
    "EXCLUSIVE": "exclusive", "互斥": "exclusive", "冲突": "exclusive",
    "MUTEX": "exclusive",
}

RELATION_NAMES: Dict[str, str] = {
    "independent": "并列", "linkage": "联动", "exclusive": "互斥",
}

# ════════════════════════════════════════════════════════════
# 维度交叉矩阵
# ════════════════════════════════════════════════════════════

CROSS_LEVEL_ALIASES: Dict[str, str] = {
    "REQUIRED": "required", "★": "required", "STAR": "required",
    "必需": "required", "必须": "required", "必交叉": "required",
    "OPTIONAL": "optional", "✓": "optional", "TICK": "optional",
    "可选": "optional", "可交叉": "optional",
    "FORBIDDEN": "forbidden", "禁止": "forbidden", "✗": "forbidden",
    "禁止交叉": "forbidden", "互斥": "forbidden",
}

CROSS_LEVEL_NAMES: Dict[str, str] = {
    "required": "必需交叉", "optional": "可选交叉", "forbidden": "禁止交叉",
}

CROSS_LEVEL_MARKS: Dict[str, str] = {
    "required": "★", "optional": "✓", "forbidden": "✗",
}

CROSS_KEY_SEPARATORS = "×✕xX*,/+/"

# ════════════════════════════════════════════════════════════
# 专题优先级
# ════════════════════════════════════════════════════════════

PRIORITY_PATTERN = re.compile(r"^P(\d)$")
DEFAULT_PRIORITY = "P0"

PRIORITY_ALIASES: Dict[str, str] = {
    "0": "P0", "P0": "P0",
    "1": "P1", "P1": "P1",
    "2": "P2", "P2": "P2",
    "3": "P3", "P3": "P3",
    "4": "P4", "P4": "P4",
    "5": "P5", "P5": "P5",
}

# 专题的两类：是否作用于功能组织树（由 applies_to 是否为空决定）
THEME_KINDS: Dict[str, str] = {
    "structural": "作用于功能组织树",
    "orthogonal": "不作用功能组织树",
}

# 专题的维度范围（由 dimensions 是否为空 / 通配决定）
THEME_DIM_SCOPES: Dict[str, str] = {
    "all": "各维度随机组合",
    "restricted": "指定维度",
}

WILDCARD = "*"

# ════════════════════════════════════════════════════════════
# 环境指纹
# ════════════════════════════════════════════════════════════

ENV_KEYS: Tuple[str, ...] = (
    "tool_version", "rtl_version", "constraint_version", "interface_version",
    "config_profile", "seed", "compile_options",
)

ENV_KEY_NAMES: Dict[str, str] = {
    "tool_version": "工具版本", "rtl_version": "RTL 版本",
    "constraint_version": "约束版本", "interface_version": "接口版本",
    "config_profile": "配置档位", "seed": "随机种子",
    "compile_options": "编译选项",
}

# ════════════════════════════════════════════════════════════
# 缺省值
# ════════════════════════════════════════════════════════════

DEFAULT_ID_PREFIX = "TC"
DEFAULT_REPEAT = 8
DEFAULT_SEED = 0


# ════════════════════════════════════════════════════════════
# 归一化辅助
# ════════════════════════════════════════════════════════════

def value_of(raw: Any) -> Any:
    """字段取值归一：加权型写成 {value, weight}，其余是裸标量。"""
    if isinstance(raw, dict):
        return raw.get("value")
    return raw


def weight_of(raw: Any) -> Optional[float]:
    if isinstance(raw, dict):
        w = raw.get("weight")
        if isinstance(w, (int, float)) and not isinstance(w, bool):
            return float(w)
    return None


def token_of(raw: Any) -> str:
    """取值的字符串坐标 —— 覆盖率的比较基准。"""
    val = value_of(raw)
    if val is None:
        return "<null>"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)


def as_list(raw: Any) -> List[Any]:
    """YAML 里单值/列表都接受，统一成列表。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    return [raw]


def num(raw: Any) -> Optional[float]:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def canon(raw: Any, table: Dict[str, str],
          default: Optional[str] = None) -> Optional[str]:
    """别名表查表：先精确，再大写。"""
    if not isinstance(raw, str):
        return default
    key = raw.strip()
    if key in table:
        return table[key]
    if key.upper() in table:
        return table[key.upper()]
    return default


def normalize_priority(raw: Any, default: str = DEFAULT_PRIORITY) -> str:
    """专题优先级归一：0 / p0 / P0 → P0。认不出来就给默认值。"""
    if isinstance(raw, int) and not isinstance(raw, bool):
        raw = f"P{raw}"
    if isinstance(raw, str):
        hit = canon(raw, PRIORITY_ALIASES)
        if hit:
            return hit
        m = PRIORITY_PATTERN.match(raw.strip().upper())
        if m:
            return f"P{m.group(1)}"
    return default


def priority_rank(priority: str) -> int:
    """排序用：P0 < P1 < P2。认不出来的排到最后。"""
    m = PRIORITY_PATTERN.match(priority or "")
    return int(m.group(1)) if m else 99


def priority_label(priority: str) -> str:
    rank = priority_rank(priority)
    return f"{priority}（第 {rank + 1} 轮）" if rank < 90 else str(priority)


def _ascii_words(text: str) -> List[str]:
    return [w for w in re.split(r"[^A-Za-z0-9]+", text or "") if w]


def derive_code(text: str, width: int = 4) -> str:
    """从名字推导 case_id 用的 ASCII 代号。

    FlowControl → FC（驼峰取首字母）
    Address     → ADDR（单词取前 width 位）
    接收侧流控   → ''（无 ASCII 可用，交给调用方兜底）
    """
    words = _ascii_words(text)
    if not words:
        return ""
    if len(words) >= 2:
        return "".join(w[0] for w in words).upper()[:8]
    parts = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+", words[0])
    if len(parts) > 1:
        return "".join(p[0] for p in parts).upper()[:8]
    return words[0][:width].upper()


def split_cross_key(key: str) -> Optional[Tuple[str, str]]:
    """拆「指令长度×反压模式」这类矩阵键；分隔符见 CROSS_KEY_SEPARATORS。"""
    for sep in CROSS_KEY_SEPARATORS:
        if sep in key:
            left, _, right = key.partition(sep)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right
    return None


def is_wildcard(ref: Any) -> bool:
    return isinstance(ref, str) and ref.strip() == WILDCARD
