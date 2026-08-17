"""
共享的输出目录命名规则 —— 所有模块统一导入此处。

格式: {prefix}_{user}_{YYYYMMDD_HHMMSS}，如 output_jiang_20260809_183000。
支持幂等调用：若路径已含时间戳后缀，直接返回，不再追加。
"""
from __future__ import annotations

import getpass
import re
from datetime import datetime

# 匹配已含时间戳的路径：..._用户名_YYYYMMDD_HHMMSS
_TIMESTAMPED = re.compile(r"_[a-z]+\d*_\d{8}_\d{6}$")


def make_output_root(base: str | None = None) -> str:
    """生成带用户名和时间戳的输出目录名（幂等）。

    多次调用同一 base 不会层层叠加后缀。已含时间戳的路径直接返回。

    Args:
        base: 目录前缀。None → "output"；已含时间戳 → 直接返回。

    Returns:
        输出目录路径，格式 {prefix}_{user}_{YYYYMMDD_HHMMSS}。
    """
    prefix = base if base else "output"
    # 幂等：若已含 _user_YYYYMMDD_HHMMSS 后缀，直接返回
    if _TIMESTAMPED.search(prefix):
        return prefix
    user = getpass.getuser()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{user}_{ts}"
