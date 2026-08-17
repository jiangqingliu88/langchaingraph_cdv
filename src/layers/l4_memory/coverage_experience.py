"""
Coverage 归因校准 —— 把"gap 归因 → 决策动作 → Δ覆盖率"的反馈沉淀成可检索的记忆。

与 ExperienceStore.gap_solution 的分工:
  - gap_solution（experience_store.py）: gap reason → 该做什么动作（静态映射）
  - 本模块: 动作是否真的涨了覆盖率（反馈校准），产出 reason 准确率 / 动作成效 / 黑名单

三个成长能力:
  1. 记忆: 每轮记录 (action_type, gap_reasons, prev/new coverage, delta)
  2. 经验: 聚合 reason 归因准确率 + 动作成效（改善率 / 平均 Δ 覆盖率）
  3. 能力: unreachable 归因多次 refactor 仍不涨 → 进黑名单，下次不再重复报告

持久化到 .signoffai/coverage_experience.db（全局跨 run，对齐 debug_experience.py）。

用法:
    from src.layers.l4_memory.coverage_experience import get_coverage_experience_store
    store = get_coverage_experience_store()
    store.record_round(round_num, action_type, reason, gap_reasons, prev, new, unreachable_dims)
    acc = store.reason_accuracy()           # {"constraint": {"trials":..,"confidence":..}}
    eff = store.action_effectiveness()      # {"RELAX_CONSTRAINT": {"improve_rate":..,"avg_delta":..}}
    bl = store.get_blacklist()              # 已多次 refactor 仍不涨的维度
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# unreachable 归因连续 refactor 失败 N 次才进黑名单
BLACKLIST_MAX_STRIKES = 3

_DEFAULT_DB = Path(".signoffai") / "coverage_experience.db"

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
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.executescript(_SCHEMA)
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
                     new_coverage: float, unreachable_dims: List[str] = None) -> None:
        """记录一轮决策动作的覆盖率反馈。

        若 REFACTOR_RTL 未改善覆盖率，则对 unreachable 归因的维度记一次 strike；
        若改善了，则清零对应 strike（说明该维度其实是可修的死代码）。
        """
        delta = round(float(new_coverage) - float(prev_coverage), 3)
        improved = 1 if delta > 0 else 0
        now = self._now()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO coverage_rounds "
                "(round_num, action_type, reason, gap_reasons, prev_coverage, "
                "new_coverage, delta, improved, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (round_num, action_type, reason,
                 json.dumps(gap_reasons or [], ensure_ascii=False),
                 float(prev_coverage), float(new_coverage), delta, improved, now),
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

    def action_effectiveness(self) -> Dict[str, Dict[str, Any]]:
        """聚合各决策动作的改善率与平均 Δ 覆盖率。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT action_type, improved, delta FROM coverage_rounds"
            ).fetchall()
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
                "new_coverage, delta, improved, created_at "
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
         new_coverage, delta, improved, created_at) = row
        try:
            gap_reasons = json.loads(gap_reasons or "[]")
        except Exception:
            gap_reasons = []
        return {
            "round_num": round_num, "action_type": action_type, "reason": reason,
            "gap_reasons": gap_reasons, "prev_coverage": prev_coverage,
            "new_coverage": new_coverage, "delta": delta,
            "improved": bool(improved), "created_at": created_at,
        }


# 全局单例（默认路径 .signoffai/coverage_experience.db）
_global_store: Optional[CoverageExperienceStore] = None


def get_coverage_experience_store(db_path: Optional[str | Path] = None) -> CoverageExperienceStore:
    global _global_store
    if _global_store is None:
        _global_store = CoverageExperienceStore(db_path)
    return _global_store
