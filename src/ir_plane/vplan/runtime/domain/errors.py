"""领域异常。

单独成模块，是为了让「模型构建失败」这个信号不依赖任何具体层：
repository 抛出它，analysis 与 view 捕获它，domain 内部不该捕获。
"""
from __future__ import annotations


from src.runtime_plane.core.runtime.errors import CaseListError, CaseModelError  # noqa: F401


__all__ = ["CaseListError", "CaseModelError"]
