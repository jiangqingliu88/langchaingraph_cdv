"""作者身份解析 —— 审计链里"谁改的/谁批的"的唯一实现。"""
from __future__ import annotations

import getpass


def resolve_author(explicit: str = "") -> str:
    """这次编辑算谁的。

    优先级：调用方给的 > `PLATFORM_USER_NAME`（配置里可写，像 git 的 user.name）
    > 系统登录名 > `unknown`。

    为什么要一个**可配置**的名字而不是直接用登录名：这个名字会被写进审计链，
    是"谁批准的、谁改的"的答案。跟着"当前登录的是谁"漂移的话，换台机器、换个
    账号，同一个人就变成了两个作者，链上就对不上了。
    """
    explicit = (explicit or "").strip()
    if explicit:
        return explicit
    try:
        from config.settings import Settings
        configured = (Settings.get_instance().platform.user_name or "").strip()
        if configured:
            return configured
    except Exception:                              # noqa: BLE001 配置不可用不挡审计
        pass
    try:
        return getpass.getuser() or "unknown"
    except Exception:                              # noqa: BLE001
        return "unknown"


__all__ = ["resolve_author"]
