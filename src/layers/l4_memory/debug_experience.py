"""
Debug 经验库 —— 错误指纹 → 已验证修复 的持久化记忆（debug 智能体的成长层）

三件事:
  1. 记忆: 新错误先按 fingerprint 查库，命中且高置信 → 复用历史修复（跳过 LLM/重复分析）
  2. 经验: rerun 的 PASS/FAIL 写回 success_count/fail_count → confidence 校准（教训机制）
  3. 能力: 稳定通过 N 次的经验可被蒸馏成规则/模板（供 Distiller 读取，见 distill_candidates）

设计约束:
  - Agent 保持无状态（agent_contract 不变），这里是"外部记忆"，只读只写不侵入 execute_task 契约
  - 同步 stdlib sqlite3（debug 工具链本就是同步 subprocess/文件 IO），不引入 async 耦合
  - 持久化到 .signoffai/debug_experience.db（对齐 InfrastructureManager 的持久归档区，跨 run 存活）

用法:
    from src.layers.l4_memory.debug_experience import get_debug_experience_store
    store = get_debug_experience_store()
    exp = store.lookup(fp)                # 命中且 confidence>=0.8 才返回
    store.record(fp, category=..., fix_name=...)   # 记录新经验（0/0，未验证）
    store.record_result(fp, passed=True)  # rerun 结果写回，校准 confidence
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 复用门槛：confidence >= 此值才认为"已验证可靠"，直接复用
REUSE_MIN_CONFIDENCE = 0.8
# 蒸馏门槛：稳定通过此次数，才认为可沉淀成规则
DISTILL_MIN_SUCCESS = 3

_DEFAULT_DB = Path(".signoffai") / "debug_experience.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS debug_experience (
    fingerprint    TEXT PRIMARY KEY,
    category       TEXT NOT NULL DEFAULT 'unknown',
    root_cause     TEXT NOT NULL DEFAULT '',
    fix_name       TEXT NOT NULL DEFAULT '',
    fix_patch      TEXT NOT NULL DEFAULT '',
    success_count  INTEGER NOT NULL DEFAULT 0,
    fail_count     INTEGER NOT NULL DEFAULT 0,
    last_seen_at   TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT ''
);
"""


class DebugExperienceStore:
    """错误指纹经验库（同步 sqlite3，跨 run 持久）。"""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute(_SCHEMA)
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

    # ── 记忆: 命中复用 ──

    def lookup(self, fingerprint: str,
               min_confidence: float = REUSE_MIN_CONFIDENCE) -> Optional[Dict[str, Any]]:
        """按指纹查经验。命中且 confidence >= 阈值才返回，否则 None。

        0/0 的未验证经验 confidence=0，默认不返回（不盲目复用）。
        """
        if not fingerprint:
            return None
        with self._lock:
            row = self._connect().execute(
                "SELECT fingerprint, category, root_cause, fix_name, fix_patch, "
                "success_count, fail_count, last_seen_at, created_at "
                "FROM debug_experience WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        if not row:
            return None
        exp = self._row_to_dict(row)
        if exp["confidence"] < min_confidence:
            return None
        return exp

    # ── 记忆: 记录新经验 ──

    def record(self, fingerprint: str, category: str = "unknown",
               root_cause: str = "", fix_name: str = "",
               fix_patch: str = "") -> Optional[Dict[str, Any]]:
        """插入或更新一条经验（保留已有成功/失败计数，不覆盖验证历史）。"""
        if not fingerprint:
            return None
        now = self._now()
        with self._lock:
            conn = self._connect()
            existing = conn.execute(
                "SELECT 1 FROM debug_experience WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE debug_experience SET category=?, root_cause=?, fix_name=?, "
                    "fix_patch=?, last_seen_at=? WHERE fingerprint=?",
                    (category, root_cause, fix_name, fix_patch, now, fingerprint),
                )
            else:
                conn.execute(
                    "INSERT INTO debug_experience "
                    "(fingerprint, category, root_cause, fix_name, fix_patch, "
                    "success_count, fail_count, last_seen_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)",
                    (fingerprint, category, root_cause, fix_name, fix_patch, now, now),
                )
            conn.commit()
        return self.lookup(fingerprint, min_confidence=0.0)

    # ── 经验: 反馈校准 ──

    def record_result(self, fingerprint: str, passed: bool) -> Optional[Dict[str, Any]]:
        """把 rerun 的 PASS/FAIL 写回，更新 success/fail 计数与 confidence。

        失败会拉低 confidence，低于复用门槛后下次不再自动应用（教训机制）。
        """
        if not fingerprint:
            return None
        now = self._now()
        # col 由布尔值决定，非用户输入，f-string 安全
        col = "success_count" if passed else "fail_count"
        sql = (
            "INSERT INTO debug_experience "
            "(fingerprint, category, root_cause, fix_name, fix_patch, "
            "success_count, fail_count, last_seen_at, created_at) "
            "VALUES (?, 'unknown', '', '', '', 0, 0, ?, ?) "
            f"ON CONFLICT(fingerprint) DO UPDATE SET "
            f"{col} = {col} + 1, last_seen_at = excluded.last_seen_at"
        )
        with self._lock:
            conn = self._connect()
            conn.execute(sql, (fingerprint, now, now))
            conn.commit()
        return self.lookup(fingerprint, min_confidence=0.0)

    # ── 能力: 蒸馏候选 ──

    def distill_candidates(self, min_success: int = DISTILL_MIN_SUCCESS,
                           min_confidence: float = REUSE_MIN_CONFIDENCE) -> List[Dict[str, Any]]:
        """返回稳定通过 N 次、可蒸馏成规则/模板的成熟经验。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT fingerprint, category, root_cause, fix_name, fix_patch, "
                "success_count, fail_count, last_seen_at, created_at "
                "FROM debug_experience WHERE success_count >= ?",
                (min_success,),
            ).fetchall()
        out = [self._row_to_dict(r) for r in rows]
        return [e for e in out if e["confidence"] >= min_confidence]

    # ── 查询 ──

    def list_all(self) -> List[Dict[str, Any]]:
        """列出全部经验（供 CLI 审计查看）。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT fingerprint, category, root_cause, fix_name, fix_patch, "
                "success_count, fail_count, last_seen_at, created_at "
                "FROM debug_experience ORDER BY last_seen_at DESC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def stats(self) -> Dict[str, int]:
        """统计: 总条数 / 可复用条数（已验证成功过的）。"""
        with self._lock:
            conn = self._connect()
            total = conn.execute("SELECT COUNT(*) FROM debug_experience").fetchone()[0]
            reusable = conn.execute(
                "SELECT COUNT(*) FROM debug_experience WHERE success_count > 0"
            ).fetchone()[0]
        return {"total": total, "reusable": reusable}

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        (fingerprint, category, root_cause, fix_name, fix_patch,
         success_count, fail_count, last_seen_at, created_at) = row
        total = success_count + fail_count
        confidence = round(success_count / total, 3) if total else 0.0
        return {
            "fingerprint": fingerprint,
            "category": category,
            "root_cause": root_cause,
            "fix_name": fix_name,
            "fix_patch": fix_patch,
            "success_count": success_count,
            "fail_count": fail_count,
            "confidence": confidence,
            "last_seen_at": last_seen_at,
            "created_at": created_at,
        }


# 全局单例（默认路径 .signoffai/debug_experience.db）
_global_store: Optional[DebugExperienceStore] = None


def get_debug_experience_store(db_path: Optional[str | Path] = None) -> DebugExperienceStore:
    global _global_store
    if _global_store is None:
        _global_store = DebugExperienceStore(db_path)
    return _global_store
