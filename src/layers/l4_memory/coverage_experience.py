"""
Coverage 归因校准 —— 把"gap 归因 → 决策动作 → Δ覆盖率"的反馈沉淀成可检索的记忆。

与 ExperienceStore.gap_solution 的分工:
  - gap_solution（experience_store.py）: gap reason → 该做什么动作（静态映射）
  - 本模块: 动作是否真的涨了覆盖率（反馈校准），产出 reason 准确率 / 动作成效 / 黑名单

三个成长能力:
  1. 记忆: 每轮记录 (action_type, gap_reasons, prev/new coverage, delta)
  2. 经验: 聚合 reason 归因准确率 + 动作成效（改善率 / 平均 Δ 覆盖率）
  3. 能力: unreachable 归因多次 refactor 仍不涨 → 进黑名单，下次不再重复报告

持久化到 database/coverage_experience.db（全局跨 run，对齐 debug_experience.py）。

用法:
    from src.layers.l4_memory.coverage_experience import get_coverage_experience_store
    store = get_coverage_experience_store()
    store.record_round(round_num, action_type, reason, gap_reasons, prev, new, unreachable_dims)
    acc = store.reason_accuracy()           # {"constraint": {"trials":..,"confidence":..}}
    eff = store.action_effectiveness()      # {"RELAX_CONSTRAINT": {"improve_rate":..,"avg_delta":..}}
    bl = store.get_blacklist()              # 已多次 refactor 仍不涨的维度
"""
from __future__ import annotations

from .sqlite_utils import connect

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.paths import COVERAGE_EXPERIENCE_DB

# unreachable 归因连续 refactor 失败 N 次才进黑名单
BLACKLIST_MAX_STRIKES = 3

_DEFAULT_DB = COVERAGE_EXPERIENCE_DB

_SCHEMA = """
CREATE TABLE IF NOT EXISTS coverage_rounds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    round_num     INTEGER NOT NULL,
    action_type   TEXT NOT NULL DEFAULT '',
    reason        TEXT NOT NULL DEFAULT '',
    gap_reasons   TEXT NOT NULL DEFAULT '[]',   -- JSON array，驱动该动作的 gap reason 列表
    prev_coverage REAL NOT NULL DEFAULT 0,
    new_coverage  REAL NOT NULL DEFAULT 0,
    delta         REAL NOT NULL DEFAULT 0,
    improved      INTEGER NOT NULL DEFAULT 0,   -- 0/1: delta > 0
    -- **这个动作是谁定的**（`Action.source`）：rule_hard / rule /
    -- rl_suggested / rl_overridden / terminal。
    --
    -- 为什么要分桶：`action_effectiveness()` 原来按 `action_type` **无差别**聚合
    -- —— 于是"RL 建议过、但被规则退掉、从来没真执行"的那些也算进了"这个动作的
    -- 历史效果"。蒸馏出来的权重因此偏向**被采纳的**那批（幸存者偏差），而真正
    -- 没生效过的从未被证伪。L5 现在只拿 `rl_suggested` 的样本学"选哪个动作"。
    --
    -- 老库补列：`_connect()` 里 ALTER TABLE（SQLite 没有 `ADD COLUMN IF NOT
    -- EXISTS`），补出来的老行是 `''` = **来源未知**，与"规则"区分得开。
    source        TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS unreachable_strikes (
    dimension    TEXT PRIMARY KEY,
    strikes      INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT ''
);
"""


class CoverageExperienceStore:
    """覆盖率归因校准库（同步 sqlite3，全局跨 run 持久）。"""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self._lock = threading.RLock()   # RLock: 允许 stats() 内联复用黑名单查询，避免重入死锁
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = connect(self.db_path)
            self._conn.executescript(_SCHEMA)
            # **老库补 `source` 列**：`CREATE TABLE IF NOT EXISTS` 对已存在的表
            # 什么都不做，所以后加的列必须在建表语句之外补一次。SQLite 没有
            # `ADD COLUMN IF NOT EXISTS`，靠"先查 pragma 再 ALTER"。
            # 补出来的老行是 `''`（来源未知）—— 与"规则决定"**分得开**，
            # 不会被误当成有来源的样本喂给蒸馏。
            try:
                cols = {r[1] for r in self._conn.execute(
                    "PRAGMA table_info(coverage_rounds)").fetchall()}
                if "source" not in cols:
                    self._conn.execute(
                        "ALTER TABLE coverage_rounds ADD COLUMN source TEXT NOT NULL DEFAULT ''")
            except sqlite3.Error:
                pass
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    # ── 记忆: 记录每轮动作成效 ──

    def record_round(self, round_num: int, action_type: str, reason: str,
                     gap_reasons: List[str], prev_coverage: float,
                     new_coverage: float, unreachable_dims: List[str] = None,
                     source: str = "") -> None:
        """记录一轮决策动作的覆盖率反馈。

        若 REFACTOR_RTL 未改善覆盖率，则对 unreachable 归因的维度记一次 strike；
        若改善了，则清零对应 strike（说明该维度其实是可修的死代码）。

        `source` 是**这个动作是谁定的**（`Action.source`）—— 见表定义里那段注释：
        不分来源地聚合会让蒸馏出幸存者偏差。缺省 `''` = 来源未知（老调用方 /
        老数据），**与"规则决定"分得开**。
        """
        delta = round(float(new_coverage) - float(prev_coverage), 3)
        improved = 1 if delta > 0 else 0
        now = self._now()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO coverage_rounds "
                "(round_num, action_type, reason, gap_reasons, prev_coverage, "
                "new_coverage, delta, improved, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (round_num, action_type, reason,
                 json.dumps(gap_reasons or [], ensure_ascii=False),
                 float(prev_coverage), float(new_coverage), delta, improved,
                 str(source or ""), now),
            )
            # unreachable 归因的反馈
            if action_type == "REFACTOR_RTL" and unreachable_dims:
                for dim in unreachable_dims:
                    if not dim:
                        continue
                    if improved:
                        conn.execute(
                            "INSERT INTO unreachable_strikes (dimension, strikes, last_seen_at, created_at) "
                            "VALUES (?, 0, ?, ?) "
                            "ON CONFLICT(dimension) DO UPDATE SET strikes = 0, last_seen_at = excluded.last_seen_at",
                            (dim, now, now),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO unreachable_strikes (dimension, strikes, last_seen_at, created_at) "
                            "VALUES (?, 1, ?, ?) "
                            "ON CONFLICT(dimension) DO UPDATE SET "
                            "strikes = strikes + 1, last_seen_at = excluded.last_seen_at",
                            (dim, now, now),
                        )
            conn.commit()

    # ── 经验: 归因准确率 + 动作成效 ──

    def reason_accuracy(self) -> Dict[str, Dict[str, Any]]:
        """聚合各 gap reason 的改善率与置信度。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT gap_reasons, improved FROM coverage_rounds"
            ).fetchall()
        agg: Dict[str, Dict[str, Any]] = {}
        for gap_reasons_json, improved in rows:
            try:
                reasons = json.loads(gap_reasons_json or "[]")
            except Exception:
                reasons = []
            for r in reasons:
                if not r:
                    continue
                a = agg.setdefault(r, {"trials": 0, "improved": 0})
                a["trials"] += 1
                a["improved"] += improved
        out = {}
        for r, a in agg.items():
            out[r] = {
                "trials": a["trials"],
                "improved": a["improved"],
                "confidence": round(a["improved"] / a["trials"], 3) if a["trials"] else 0.0,
            }
        return out

    def action_effectiveness(self, source: Optional[str] = None
                             ) -> Dict[str, Dict[str, Any]]:
        """聚合各决策动作的改善率与平均 Δ 覆盖率。

        `source` 给了就**只统计那个来源**（`rl_suggested` / `rule` / …）。
        L5 蒸馏走 `source="rl_suggested"` —— 它要回答的是"**RL 选的动作**里
        哪些真的有用"，而不是"凡是叫这个名字的动作"。

        不分来源的后果很具体（这就是加这个参数的原因）：RL 建议了 A、被规则
        退成 B，那一轮照样以 B 的名字记一条 —— 于是 A 的历史"效果"里混进了
        一堆**它根本没被采用**的轮次。蒸馏据此算出的权重是幸存者偏差。
        """
        sql = "SELECT action_type, improved, delta FROM coverage_rounds"
        params: tuple = ()
        if source is not None:
            sql += " WHERE source = ?"
            params = (str(source),)
        with self._lock:
            rows = self._connect().execute(sql, params).fetchall()
        agg: Dict[str, Dict[str, Any]] = {}
        for action_type, improved, delta in rows:
            if not action_type:
                continue
            a = agg.setdefault(action_type, {"trials": 0, "improved": 0, "delta_sum": 0.0})
            a["trials"] += 1
            a["improved"] += improved
            a["delta_sum"] += delta
        out = {}
        for act, a in agg.items():
            out[act] = {
                "trials": a["trials"],
                "improved": a["improved"],
                "improve_rate": round(a["improved"] / a["trials"], 3) if a["trials"] else 0.0,
                "avg_delta": round(a["delta_sum"] / a["trials"], 3) if a["trials"] else 0.0,
            }
        return out

    # ── 能力: unreachable 黑名单 ──

    def is_unreachable_blacklisted(self, dimension: str,
                                   max_strikes: int = BLACKLIST_MAX_STRIKES) -> bool:
        if not dimension:
            return False
        with self._lock:
            row = self._connect().execute(
                "SELECT strikes FROM unreachable_strikes WHERE dimension = ?",
                (dimension,),
            ).fetchone()
        return bool(row) and row[0] >= max_strikes

    def get_blacklist(self, max_strikes: int = BLACKLIST_MAX_STRIKES) -> List[str]:
        with self._lock:
            rows = self._connect().execute(
                "SELECT dimension, strikes FROM unreachable_strikes"
            ).fetchall()
        return [d for d, s in rows if s >= max_strikes]

    # ── 查询 ──

    def list_rounds(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._connect().execute(
                "SELECT round_num, action_type, reason, gap_reasons, prev_coverage, "
                "new_coverage, delta, improved, source, created_at "
                "FROM coverage_rounds ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._round_to_dict(r) for r in rows]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            conn = self._connect()
            rounds = conn.execute("SELECT COUNT(*) FROM coverage_rounds").fetchone()[0]
            blacklisted = conn.execute(
                f"SELECT COUNT(*) FROM unreachable_strikes WHERE strikes >= {BLACKLIST_MAX_STRIKES}"
            ).fetchone()[0]
        return {"rounds": rounds, "blacklisted": blacklisted}

    @staticmethod
    def _round_to_dict(row) -> Dict[str, Any]:
        (round_num, action_type, reason, gap_reasons, prev_coverage,
         new_coverage, delta, improved, source, created_at) = row
        try:
            gap_reasons = json.loads(gap_reasons or "[]")
        except Exception:
            gap_reasons = []
        return {
            "round_num": round_num, "action_type": action_type, "reason": reason,
            "gap_reasons": gap_reasons, "prev_coverage": prev_coverage,
            "new_coverage": new_coverage, "delta": delta,
            "improved": bool(improved),
            # `''` = 来源未知（老数据）—— 与 "rule" 分得开
            "source": source or "",
            "created_at": created_at,
        }


# 全局单例（默认路径 database/coverage_experience.db）
_global_store: Optional[CoverageExperienceStore] = None


def get_coverage_experience_store(db_path: Optional[str | Path] = None) -> CoverageExperienceStore:
    global _global_store
    if _global_store is None:
        _global_store = CoverageExperienceStore(db_path)
    return _global_store
