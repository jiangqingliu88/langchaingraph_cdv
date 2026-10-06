"""**策略提示（hint）的结局统计** —— prompt 库能不能淘汰，全看这张表。

## 为什么非有不可

prompt 库腐烂的路径和规则库一样，但更隐蔽：hint 是**文本**，加一条没人看得出来，
于是越加越长，最后把 prompt 撑满、还说不清哪句有用。要能淘汰，就必须回答
**"有它比没它好多少"** —— 那只统计"用了哪些 id"是不够的（上一轮做的 ③ 只到这一步），
得有**结局**。

## 记什么

一次定向激励生成结束，把这次注入的 hint id 与**当时可判定的结局**写一条：

    hint_id, run_id, compiled(生成的序列过没过 EDN 编译门禁), note

`compiled` 是这一刻唯一**确定**的结局（"这段提示有没有让模型写出能编译的东西"）。
覆盖率增量要等这一轮跑完才知道，且它是**多因素**的（激励、种子、约束都在动）——
把它算到单条 hint 头上是过度归因，所以这里**不记**，留给后续做对照实验。

## 于是它能回答

  · 每条 hint 试过几次、其中几次编译通过（`rate`）
  · 哪条 hint **从注入起一次都没让人写出能编译的代码**（`ineffective`）—— 该改写或删掉

与 `rule_stats` 同一个口径（`.signoffai/` 下、相对工作目录、**项目隔离现成**），
同样是**旁路**：记不上不影响生成。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

_DEFAULT_DB = Path(".signoffai") / "hint_stats.db"

#: 试过这么多次仍一次都没编译通过，才算"该淘汰的" —— 一次失败可能是运气
MIN_TRIALS_TO_JUDGE = 2


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class HintStats:
    """策略提示的尝试/成功计数（SQLite）。"""

    def __init__(self, db_path: str = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hint_outcomes (
                hint_id TEXT NOT NULL PRIMARY KEY,
                trials INTEGER NOT NULL DEFAULT 0,
                compiled_ok INTEGER NOT NULL DEFAULT 0,
                first_run TEXT NOT NULL DEFAULT '',
                last_run TEXT NOT NULL DEFAULT '',
                last_note TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
        """)
        return conn

    def record(self, hint_ids: Iterable[str], compiled: bool,
               run_id: str = "", note: str = "") -> int:
        """记一次结局：这次注入的每条 hint 都算"试过一次"。

        **一次生成里注入了几条就记几条** —— 现在是一次全注入，所以效果无法
        拆到单条头上；这如实反映了当前的能力边界（要做单条对照得改成
        "分组注入 + 对照"，那是下一步的设计，不是这里的笔误）。
        """
        ids = [str(h) for h in (hint_ids or []) if str(h).strip()]
        if not ids:
            return 0
        now = _now()
        with self._connect() as conn:
            for hint_id in ids:
                conn.execute("""
                    INSERT INTO hint_outcomes
                        (hint_id, trials, compiled_ok, first_run, last_run, last_note, updated_at)
                    VALUES (?, 1, ?, ?, ?, ?, ?)
                    ON CONFLICT(hint_id) DO UPDATE SET
                        trials = trials + 1,
                        compiled_ok = compiled_ok + excluded.compiled_ok,
                        last_run = excluded.last_run,
                        last_note = excluded.last_note,
                        updated_at = excluded.updated_at
                """, (hint_id, 1 if compiled else 0, run_id, run_id, note[:200], now))
        return len(ids)

    def stats(self) -> Dict[str, Any]:
        """每条 hint 的尝试与通过次数 + **该淘汰的**。"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = []
            for r in conn.execute("SELECT * FROM hint_outcomes ORDER BY hint_id"):
                item = dict(r)
                item["rate"] = round(item["compiled_ok"] / item["trials"], 3) if item["trials"] else 0.0
                rows.append(item)
        ineffective = [r for r in rows
                       if r["trials"] >= MIN_TRIALS_TO_JUDGE and r["compiled_ok"] == 0]
        return {
            "hints": rows,
            "ineffective": ineffective,
            "total_trials": sum(r["trials"] for r in rows),
            "db": str(self.db_path),
        }


def record_hint_outcome(hint_ids: Iterable[str], compiled: bool, run_id: str = "",
                        note: str = "", db_path: str = None) -> int:
    """便捷入口。**失败不抛** —— 统计是旁路。"""
    try:
        return HintStats(db_path).record(hint_ids, compiled, run_id=run_id, note=note)
    except Exception:                                  # noqa: BLE001
        return 0
