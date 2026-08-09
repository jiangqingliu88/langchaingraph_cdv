"""
共享的输出目录命名规则 —— 所有模块统一导入此处。

格式: output_{username}_{YYYYMMDD_HHMMSS}，如 output_jiang_20260809_183000。
可通过 base 参数覆盖（用户显式指定 --output 时）。
"""

from __future__ import annotations

import getpass
from datetime import datetime


def make_output_root(base: str | None = None) -> str:
    """生成带用户名和时间戳的输出目录名。

    Args:
        base: 用户显式指定的目录。为 None 或空字符串时自动生成。

    Returns:
        输出目录路径字符串。
    """
    if base:
        return base
    user = getpass.getuser()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"output_{user}_{ts}"
