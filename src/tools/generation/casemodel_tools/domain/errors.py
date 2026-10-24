"""领域异常。

单独成模块，是为了让「模型构建失败」这个信号不依赖任何具体层：
repository 抛出它，analysis 与 view 捕获它，domain 内部不该捕获。
"""
from __future__ import annotations


class CaseModelError(ValueError):
    """模型无法构建 —— 结构性错误。

    典型场景：YAML 顶层不是 mapping、缺 object/dimensions、object 不是字符串。
    与「schema 违规」的区别：schema 违规是逐条可枚举的 Issue（不抛异常），
    这里是「连模型对象都建不出来」，只能中断。
    """


class CaseListError(ValueError):
    """外部真实 case 列表无法解析。"""
