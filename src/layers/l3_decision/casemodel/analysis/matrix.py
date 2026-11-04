"""维度交叉矩阵 —— 文档十四节。

矩阵是「维度的约束组合」的载体：专题先选定范围（打哪些节点、用哪些维度），
矩阵再来约束这些维度彼此怎么配。所以它的输入是脚本，输出是**约束**，
不是 case 本身。

显式声明优先：矩阵里写的级别不会被交叉组静默覆盖。两者打架时保留声明、
把冲突记进 conflicts，由 rules/cross.py 报出来 —— 静默取一个会让模型
「看起来生效实则失效」。
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Dict, List, Optional, Tuple

from ..domain import CaseModel, Dimension


@dataclass
class MatrixCell:
    """交叉矩阵的一个格子。"""
    row: int
    col: int
    level: str = "none"          # required | optional | forbidden | none
    source: str = "undeclared"   # declared | group | undeclared
    reason: str = ""

    @property
    def mark(self) -> str:
        return {"required": "★", "optional": "✓", "forbidden": "✗"}.get(self.level, "")

    @property
    def level_name(self) -> str:
        return {"required": "必需交叉", "optional": "可选交叉",
                "forbidden": "禁止交叉"}.get(self.level, "未声明")

    @property
    def crosses(self) -> bool:
        """是否表示「这两个维度要一起变」。"""
        return self.level in ("required", "optional")


@dataclass
class CrossMatrix:
    """维度交叉矩阵。"""
    dimensions: List[Dimension] = _field(default_factory=list)
    cells: Dict[Tuple[int, int], MatrixCell] = _field(default_factory=dict)
    #: (a_key, b_key, 声明级别, 交叉组级别, 交叉组key) —— 显式声明与交叉组不一致
    conflicts: List[Tuple[str, str, str, str, str]] = _field(default_factory=list)

    @property
    def labels(self) -> List[str]:
        return [d.label for d in self.dimensions]

    @property
    def keys(self) -> List[str]:
        return [d.key for d in self.dimensions]

    def index_of(self, key: str) -> int:
        for i, d in enumerate(self.dimensions):
            if d.key == key:
                return i
        return -1

    def get(self, a: str, b: str) -> Optional[MatrixCell]:
        i, j = self.index_of(a), self.index_of(b)
        if i < 0 or j < 0 or i == j:
            return None
        return self.cells.get((min(i, j), max(i, j)))

    def mark_grid(self) -> List[List[str]]:
        """GUI 用的符号网格：对角线 '—'，未声明留空。"""
        n = len(self.dimensions)
        grid = [["" for _ in range(n)] for _ in range(n)]
        for i in range(n):
            grid[i][i] = "—"
        for (i, j), cell in self.cells.items():
            grid[i][j] = cell.mark
            grid[j][i] = cell.mark
        return grid

    def rows(self) -> List[Dict[str, object]]:
        """逐对展开（报告/表格用）。"""
        out: List[Dict[str, object]] = []
        n = len(self.dimensions)
        for i in range(n):
            for j in range(i + 1, n):
                cell = self.cells.get((i, j))
                if cell is None:
                    continue
                out.append({
                    "a": self.dimensions[i].label,
                    "b": self.dimensions[j].label,
                    "a_key": self.dimensions[i].key,
                    "b_key": self.dimensions[j].key,
                    "level": cell.level,
                    "level_name": cell.level_name,
                    "mark": cell.mark,
                    "source": cell.source,
                    "reason": cell.reason,
                })
        return out

    def declared_count(self) -> int:
        return sum(1 for c in self.cells.values() if c.source != "undeclared")

    def total_pairs(self) -> int:
        n = len(self.dimensions)
        return n * (n - 1) // 2

    def undeclared_count(self) -> int:
        return self.total_pairs() - self.declared_count()

    def participation(self) -> Dict[str, int]:
        """每个维度参与了几对交叉（★ + ✓，不含禁止）。"""
        counts = {d.key: 0 for d in self.dimensions}
        for (i, j), cell in self.cells.items():
            if cell.crosses:
                counts[self.dimensions[i].key] += 1
                counts[self.dimensions[j].key] += 1
        return counts

    def forbidden_pairs(self) -> List[Tuple[str, str]]:
        """(a_key, b_key) 清单 —— 生成侧拿它做互斥剔除。"""
        return [(self.dimensions[i].key, self.dimensions[j].key)
                for (i, j), c in self.cells.items() if c.level == "forbidden"]


def build_matrix(model: CaseModel) -> CrossMatrix:
    """模型 → 交叉矩阵。声明优先，交叉组补隐含格子，其余标未声明。"""
    matrix = CrossMatrix(dimensions=list(model.dimensions))
    index = {d.key: i for i, d in enumerate(model.dimensions)}
    n = len(model.dimensions)

    def put(i: int, j: int, level: str, source: str, reason: str = "",
            keep_declared: bool = True) -> None:
        key = (min(i, j), max(i, j))
        existing = matrix.cells.get(key)
        if existing and existing.source == "declared" and keep_declared:
            return
        matrix.cells[key] = MatrixCell(row=key[0], col=key[1],
                                       level=level, source=source, reason=reason)

    for pair in model.cross_pairs:
        if not pair.resolved:
            continue
        i, j = index.get(pair.dim_a.key), index.get(pair.dim_b.key)
        if i is None or j is None or i == j:
            continue
        put(i, j, pair.level, "declared", pair.reason)

    # 交叉组隐含的格子（组内两两）。组内维度必然一起组合，禁止逻辑在组内不适用。
    for grp in model.cross_groups:
        keys = [d.key for d in grp.dims]
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                i, j = index.get(keys[a]), index.get(keys[b])
                if i is None or j is None or i == j:
                    continue
                level = "required" if grp.level == "forbidden" else grp.level
                existing = matrix.cells.get((min(i, j), max(i, j)))
                if existing and existing.source == "declared":
                    if existing.level != level and existing.level != "forbidden":
                        matrix.conflicts.append(
                            (keys[a], keys[b], existing.level, level, grp.key))
                    continue
                put(i, j, level, "group", f"由交叉组 {grp.key} 隐含",
                    keep_declared=False)

    for i in range(n):
        for j in range(i + 1, n):
            matrix.cells.setdefault((i, j), MatrixCell(row=i, col=j,
                                                       level="none",
                                                       source="undeclared"))
    return matrix
