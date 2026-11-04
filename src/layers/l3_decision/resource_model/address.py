"""地址区间：规范化、溢出与重叠判定（左闭右开）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AddressRange:
    address: int
    length: int
    space: str = ""

    @property
    def start(self) -> int:
        return int(self.address)

    @property
    def end(self) -> int:
        return int(self.address) + int(self.length)

    @property
    def valid(self) -> bool:
        return self.length > 0 and self.address >= 0

    def normalized(self, address_width: int = 64) -> "AddressRange":
        """按地址宽度截断；溢出在 `overflowed` 里单独报。"""
        mask = (1 << address_width) - 1
        return AddressRange(self.address & mask, self.length, self.space)

    def overflowed(self, address_width: int = 64) -> bool:
        return self.end > (1 << address_width)


def overlap(a: AddressRange, b: AddressRange) -> str:
    """返回 NONE / ADJACENT / PARTIAL / FULL / CONTAINED。"""
    if not a.valid or not b.valid or a.space != b.space:
        return "NONE"
    if a.start == b.start and a.end == b.end:
        return "FULL"
    if a.end == b.start or b.end == a.start:
        return "ADJACENT"
    if a.end <= b.start or b.end <= a.start:
        return "NONE"
    if (a.start <= b.start and b.end <= a.end) or \
            (b.start <= a.start and a.end <= b.end):
        return "CONTAINED"
    return "PARTIAL"


def overlaps(a: AddressRange, b: AddressRange) -> bool:
    return overlap(a, b) not in ("NONE", "ADJACENT")


__all__ = ["AddressRange", "overlap", "overlaps"]
