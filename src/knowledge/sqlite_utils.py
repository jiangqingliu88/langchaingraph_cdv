"""SQLite 连接统一配置 —— WAL + busy_timeout + 单写者友好。

项目里有 **SQLAlchemy（异步）** 和 **裸 sqlite3（同步注册表）** 两条连接路径。
两条都要有同样的 pragma；否则桌面工作台与 CLI 并发时会一边 WAL、一边回滚日志，
`database is locked` 的概率反而更高。

用法：

    from .sqlite_utils import connect, configure
    conn = connect(MAIN_DB)
    # 或对已存在的连接：
    configure(conn)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def configure(conn: sqlite3.Connection, *, busy_timeout_ms: int = 5000) -> None:
    """设置并发相关 pragma（幂等，开销很小）。"""
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error:
        # 老库/只读库上个别 pragma 可能失败；不阻断主流程
        pass


def connect(path: str | Path, **kwargs) -> sqlite3.Connection:
    """打开连接并立即配置 pragma。"""
    conn = sqlite3.connect(str(path), **kwargs)
    configure(conn)
    return conn
