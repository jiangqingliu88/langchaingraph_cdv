"""签核状态的**唯一词表与展示映射**。

## 为什么单独一个文件

状态本身只由 `verification_os.derive()` 产出（契约 → 义务 → 事实 → 推导）。
但"状态怎么显示"散落在 `case_view` / `cell_matrix` / GUI 里各写一份：

    PROVEN → green / MISSING → red / PARTIAL → yellow …

各写一份的直接后果是：改了一处映射，另一份报表还是旧颜色。所以这里只放
**映射**（不做判定），所有视图都调这一份：

    display_color(status)      单值状态 → green/yellow/red/na
    worst(statuses)            多值 → 最差
    cell_color(statuses)       TP 契约状态（VERIFIED/PARTIAL/…）→ CELL 颜色
    evidence_color(statuses)   case 证据状态（PROVEN/MISSING/…）→ 颜色
    conclusion_for(layers)     四层展示色 → 人读结论

判定实现在 `verification_os/derive.py` 与 `tp_shadow.status_for_hits`；
**这里不 import 它们、不改它们**，只做词表。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

GREEN = "green"
YELLOW = "yellow"
RED = "red"
NA = "na"

COLORS = (GREEN, YELLOW, RED, NA)
COLOR_ORDER = {NA: 0, GREEN: 1, YELLOW: 2, RED: 3}

#: 证据/契约状态 → 展示色。
_STATUS_COLOR = {
    "PROVEN": GREEN,
    "VERIFIED": GREEN,
    "PARTIAL": YELLOW,
    "PENDING_BACKEND": YELLOW,
    "OBSERVED": YELLOW,
    "SIGNED_OFF": GREEN,
    "MISSING": RED,
    "NOT_EXECUTED": RED,
    "NOT_VERIFIED": RED,
    "UNMAPPED": RED,
    "UNOBSERVED": RED,
    "NOT_APPLICABLE": NA,
    "": NA,
}

#: 展示色 → 人读文字。
COLOR_TEXT = {GREEN: "通过", YELLOW: "部分", RED: "缺失", NA: "不适用"}

#: 层名（与 `_LAYER_KEYS` 同序，视图与结论共用）。
LAYER_LABELS = (("coverage", "功能覆盖"), ("sva", "SVA"),
                ("scoreboard", "Scoreboard"), ("path", "PATH"))


def display_color(status: Any) -> str:
    """单个状态 → 展示色。未知状态按 `na`（不冒充绿）。"""
    text = str(status or "")
    return _STATUS_COLOR.get(text, NA)


def worst(statuses: Iterable[Any]) -> str:
    """多值 → 最差的展示色（红 > 黄 > 绿 > na；空 = na）。"""
    colors = [display_color(s) for s in statuses if s]
    if not colors:
        return NA
    return max(colors, key=lambda c: COLOR_ORDER.get(c, 0))


def cell_color(statuses: Iterable[Any]) -> str:
    """TP 契约状态集合 → CELL 颜色（与 `cell_matrix` 原口径一致）。"""
    values = [str(s) for s in statuses if s]
    if not values:
        return NA
    if any(v in ("NOT_VERIFIED", "UNMAPPED", "MISSING") for v in values):
        return RED
    if all(v == "VERIFIED" for v in values):
        return GREEN
    if all(v == "PENDING_BACKEND" for v in values):
        return NA
    return YELLOW


def evidence_color(statuses: Iterable[Any]) -> str:
    """case 证据状态集合 → 颜色（与 `cell_matrix._evidence_status` 原口径一致）。"""
    values = [str(s) for s in statuses if s]
    if not values:
        return NA
    if any(v in ("MISSING", "UNMAPPED", "NOT_EXECUTED") for v in values):
        return RED
    if all(v in ("PROVEN", "NOT_APPLICABLE") for v in values):
        return GREEN
    if all(v == "PENDING_BACKEND" for v in values):
        return NA
    return YELLOW


def conclusion_for(layers: Dict[str, str]) -> str:
    """四层展示色 → 人读结论（与 case_view 原口径一致）。"""
    if all(v == GREEN for v in layers.values()):
        return "已验证"
    reds = [_label(k) for k, v in layers.items() if v == RED]
    yellows = [_label(k) for k, v in layers.items() if v == YELLOW]
    if reds:
        return "证据链不完整（" + "、".join(reds) + "）"
    if yellows:
        return "待补（" + "、".join(yellows) + "）"
    return "不适用"


def _label(key: str) -> str:
    for k, label in LAYER_LABELS:
        if k == key:
            return label
    return key


def detail_of(statuses: List[Any], labels: Dict[str, str] = None) -> str:
    """给视图用的简短要点：`PROVEN×3 / PARTIAL×1`。"""
    counts: Dict[str, int] = {}
    for status in statuses:
        text = str(status or "")
        if text:
            counts[text] = counts.get(text, 0) + 1
    labels = labels or {}
    return "、".join(f"{labels.get(k, k)}×{v}" for k, v in sorted(counts.items()))


__all__ = [
    "COLORS", "COLOR_ORDER", "COLOR_TEXT", "GREEN", "LAYER_LABELS", "NA", "RED",
    "YELLOW", "cell_color", "conclusion_for", "detail_of", "display_color",
    "evidence_color", "worst",
]
