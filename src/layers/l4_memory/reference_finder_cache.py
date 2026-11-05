"""Reference Finder 结论缓存 —— 「这个版本跑过没有」的持久化记忆。

为什么需要它

    每个版本 = 一次完整编译 + 仿真（Questa 编一次几十秒到几分钟）。迭代排查时
    同样的区间会被反复查，而二分每轮都要重跑端点。缓存把「跑过的版本」记下来，
    重复查询直接命中，省掉的是**分钟级**的 EDA 时间，不是毫秒级的函数调用。

缓存键为什么带 env_digest

    结论不只取决于代码，还取决于**跑它的环境**。同一个提交在换过 EDA 版本 /
    UVM 版本之后重新判定，结论可能不同 —— 所以环境摘要必须进键。
    否则缓存会用一个旧环境下的结论回答新环境的问题，而且看起来毫无破绽。

设计约束（与 debug_experience 保持一致）

  - 同步 stdlib sqlite3，不引入 async 耦合
  - 持久化到 `.signoffai/`，跨 run 存活
  - 只读只写，不侵入 ReferenceFinder 的契约
"""
from __future__ import annotations

from .sqlite_utils import connect

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from config.paths import REFERENCE_FINDER_CACHE_DB

_DEFAULT_DB = REFERENCE_FINDER_CACHE_DB

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rev_verdict (
    repo          TEXT NOT NULL,
    rev           TEXT NOT NULL,
    test_pattern  TEXT NOT NULL,
    env_digest    TEXT NOT NULL,
    verdict       TEXT NOT NULL,
    detail        TEXT NOT NULL DEFAULT '',
    passed        INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    unknown       INTEGER NOT NULL DEFAULT 0,
    run_root      TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (repo, rev, test_pattern, env_digest)
);
CREATE INDEX IF NOT EXISTS idx_rev_verdict_rev ON rev_verdict(repo, rev);
"""


class ReferenceFinderCache:
    def __init__(self, db_path: str | Path = None):
        # 相对路径按 .signoffai/ 解析（与其它 L4 库一致，跨 run 存活）
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── 读 ──
    def get(self, repo: str, rev: str, test_pattern: str,
            env_digest: str) -> Optional[Dict[str, Any]]:
        """命中返回该版本的结论 dict，未命中返回 None。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM rev_verdict WHERE repo=? AND rev=? "
                "AND test_pattern=? AND env_digest=?",
                (str(repo), rev, test_pattern, env_digest)).fetchone()
        return dict(row) if row else None

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT verdict, COUNT(*) c FROM rev_verdict GROUP BY verdict").fetchall()
        return {r["verdict"]: r["c"] for r in rows}

    # ── 写 ──
    def put(self, repo: str, rev: str, test_pattern: str, env_digest: str,
            verdict: str, detail: str = "", passed: int = 0, failed: int = 0,
            unknown: int = 0, run_root: str = "") -> None:
        """记一条结论。

        **inconclusive 也记** —— 它是「这次没测出来」这一事实本身，
        下次查询可以据此决定是否值得重试，而不是误当成从没跑过。
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO rev_verdict "
                "(repo, rev, test_pattern, env_digest, verdict, detail, "
                " passed, failed, unknown, run_root, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (str(repo), rev, test_pattern, env_digest, verdict, detail,
                 passed, failed, unknown, str(run_root),
                 datetime.now().isoformat(timespec="seconds")))
            self._conn.commit()

    def clear(self, repo: str = None) -> int:
        """清缓存。给了 repo 就只清它，返回删除行数。"""
        with self._lock:
            cur = (self._conn.execute("DELETE FROM rev_verdict WHERE repo=?", (str(repo),))
                   if repo else self._conn.execute("DELETE FROM rev_verdict"))
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_store: Optional[ReferenceFinderCache] = None
_store_lock = threading.Lock()


def get_reference_finder_cache(db_path: str | Path = None) -> ReferenceFinderCache:
    """进程级单例。"""
    global _store
    with _store_lock:
        if _store is None:
            _store = ReferenceFinderCache(db_path)
        return _store
