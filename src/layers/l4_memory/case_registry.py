"""跨 run 的 **CASE 注册表** —— 同一逻辑用例在哪些 run 出现过。

## 为什么需要

`case_view` 已经回答了"这一轮每条 CASE 有什么证据"，但跨 run 的问题还没有
实体可查：

    · 这个 CASE 第一次出现在哪一轮？最后一轮？
    · 它一共跑出过多少条执行实例（EVD）？
    · 某轮报表对不上时，另外几轮的同一 CASE 是什么样子？

以前只能靠 SHA256 反查或翻目录名。身份脊梁（CASE → TST → EVD → CELL）落地
之后，`case_id` 本身就是稳定的 join 键 —— 这里只补一张跨 run 的索引表：

    case_registry(module, case_id, first_seen_run, last_seen_run, evd_count, updated_at)

## 边界

- **只是元数据**：写失败/表不存在都不该拦证据流水线（调用方包 try/except）。
- 批次级 test（没有 CASE）不进表 —— 它们没有稳定的逻辑身份，硬编一个就是造身份。
- 与 `lineage.db` 分工相同：这里是可重建的索引，不是事实账本。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .sqlite_utils import connect

SCHEMA = "case_registry_v1"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS case_registry (
    module         TEXT NOT NULL DEFAULT '',
    case_id        TEXT NOT NULL,
    first_seen_run TEXT NOT NULL DEFAULT '',
    last_seen_run  TEXT NOT NULL DEFAULT '',
    evd_count      INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (module, case_id)
);
"""


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _default_db() -> Path:
    from config.paths import MAIN_DB
    return Path(MAIN_DB)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    conn.execute(_SCHEMA_SQL)
    return conn


def case_counts(run_dir: str | Path) -> Dict[str, int]:
    """本 run 的 `{case_id: EVD 条数}`（只收有 CASE 身份的执行实例）。"""
    root = Path(run_dir)
    view = _read_json(root / "coverage" / "case_view.json")
    counts: Dict[str, int] = {}
    for run in view.get("case_runs") or []:
        if not isinstance(run, dict):
            continue
        case_id = str(run.get("case_id") or "")
        if case_id:
            counts[case_id] = counts.get(case_id, 0) + 1
    # 没有 case_runs 时退回 cases（去重后的逻辑用例，EVD 计 0）
    for case in view.get("cases") or []:
        if isinstance(case, dict) and case.get("case_id"):
            counts.setdefault(str(case["case_id"]), 0)
    return counts


def record_case_view(run_dir: str | Path,
                     db_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """把本 run 的 CASE 身份并进跨 run 注册表（幂等 upsert）。"""
    root = Path(run_dir)
    counts = case_counts(root)
    if not counts:
        return {"schema": SCHEMA, "run": root.name, "cases": 0}
    case_ir = _read_json(root / "coverage" / "case_ir.json")
    module = str(case_ir.get("module") or root.name)
    now = datetime.now().isoformat(timespec="seconds")
    conn = _connect(db_path or _default_db())
    try:
        with conn:
            for case_id, evd in sorted(counts.items()):
                conn.execute(
                    """
                    INSERT INTO case_registry
                        (module, case_id, first_seen_run, last_seen_run,
                         evd_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(module, case_id) DO UPDATE SET
                        last_seen_run = excluded.last_seen_run,
                        evd_count     = excluded.evd_count,
                        updated_at    = excluded.updated_at
                    """,
                    (module, case_id, root.name, root.name, int(evd), now))
    finally:
        conn.close()
    return {"schema": SCHEMA, "run": root.name, "module": module,
            "cases": len(counts), "evd": sum(counts.values())}


def list_cases(module: str = "",
               db_path: Optional[str | Path] = None) -> List[Dict[str, Any]]:
    """按模块（可空 = 全部）读注册表，最近的 run 在前。"""
    conn = _connect(db_path or _default_db())
    try:
        if module:
            rows = conn.execute(
                "SELECT module, case_id, first_seen_run, last_seen_run, "
                "evd_count, updated_at FROM case_registry WHERE module = ? "
                "ORDER BY updated_at DESC", (module,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT module, case_id, first_seen_run, last_seen_run, "
                "evd_count, updated_at FROM case_registry "
                "ORDER BY updated_at DESC").fetchall()
    finally:
        conn.close()
    return [{"module": r[0], "case_id": r[1], "first_seen_run": r[2],
             "last_seen_run": r[3], "evd_count": r[4], "updated_at": r[5]}
            for r in rows]


__all__ = ["SCHEMA", "case_counts", "list_cases", "record_case_view"]
