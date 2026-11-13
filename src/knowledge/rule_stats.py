"""校验规则的**命中统计** —— 把规则库从"只增不减的清单"变成能淘汰的资产。

## 为什么要有这个

规则（`semantic_check` 的 `@rule`、`quality_guard` 的 validator）现在**带 id 但
只打印**：每次运行写了 `validation_report.txt` 就完了，没有任何地方累计"哪条规则
真在拦东西、哪条从来没命中过"。

后果很具体：规则库**只会越加越多**。而"从来没命中的规则"和"真在干活的规则"在
代码里长得一模一样 —— 于是没人敢删任何一条，也没人知道哪条的阈值该调。这就是
所有规则库腐烂的共同路径：**不能淘汰的库不是资产，是负债。**

## 记什么、怎么用

每次校验把命中的 (rule, severity) 累加一次，带上 run_id 与最近一次命中的目标。
于是能回答三个问题：

  · 哪条规则命中最多（它在护着什么）
  · 哪条规则**从注册起一次都没命中**（`never_hit`）—— 该删、该调阈值、或该补一个它本该拦的用例
  · 某条规则是从哪次运行开始出现的（`first_run`）

`never_hit` 要拿"注册过的规则全集"作差 —— 所以这里会去问各注册表要规则清单
（`semantic_check._RULES`），**不另抄一份规则名单**。

## 放哪

`database/rule_stats.db` —— 与其它 L4 记忆库同目录、同口径（相对工作目录，
所以**项目隔离是现成的**：换个目录跑，统计就换一份）。
"""
from __future__ import annotations

from .sqlite_utils import connect

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from config.paths import RULE_STATS_DB

_DEFAULT_DB = RULE_STATS_DB


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def registered_rules() -> List[Dict[str, str]]:
    """**注册过的规则全集**（供 `never_hit` 作差）。

    从各注册表现取，不另抄名单 —— 抄一份就是第二份真相，迟早和代码里的规则对不上。
    认不出的注册表就跳过（少几条 never_hit 好过报一个假名单）。
    """
    out: List[Dict[str, str]] = []
    try:
        from src.generation.uvm_tools.tool_uvm.semantic_check import _RULES

        for (kind, rule_id), (severity, _fn) in (_RULES or {}).items():
            out.append({"rule": rule_id, "kind": kind, "severity": severity})
    except Exception:                                  # noqa: BLE001
        pass
    return out


class RuleStats:
    """规则命中计数（SQLite）。"""

    def __init__(self, db_path: str = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB

    # ── 连接 ──
    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rule_hits (
                rule TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT '',
                hits INTEGER NOT NULL DEFAULT 0,
                first_run TEXT NOT NULL DEFAULT '',
                last_run TEXT NOT NULL DEFAULT '',
                last_target TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (rule, severity)
            )
        """)
        return conn

    # ── 写 ──
    def record(self, issues: Iterable[Any], run_id: str = "") -> int:
        """把一次校验里命中的规则累加一次，返回命中的**条目数**。

        `issues` 是 `semantic_check` 的 SemanticIssue（有 `.rule` / `.severity` /
        `.target`），也接受同形状的 dict —— 别的校验器（quality_guard）照样能用。
        """
        rows = []
        for issue in issues or []:
            rule_id = str(getattr(issue, "rule", "") or
                          (issue.get("rule", "") if isinstance(issue, dict) else ""))
            if not rule_id:
                continue                                  # 没 id 的不记 —— 记了也没法淘汰
            rows.append({
                "rule": rule_id,
                "severity": str(getattr(issue, "severity", "") or
                                (issue.get("severity", "") if isinstance(issue, dict) else "")),
                "kind": str(getattr(issue, "kind", "") or
                            (issue.get("kind", "") if isinstance(issue, dict) else "")),
                "target": str(getattr(issue, "target", "") or
                              (issue.get("target", "") if isinstance(issue, dict) else "")),
            })
        if not rows:
            return 0
        now = _now()
        with self._connect() as conn:
            for row in rows:
                conn.execute("""
                    INSERT INTO rule_hits
                        (rule, severity, kind, hits, first_run, last_run, last_target, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(rule, severity) DO UPDATE SET
                        hits = hits + 1,
                        kind = CASE WHEN excluded.kind != '' THEN excluded.kind ELSE kind END,
                        last_run = excluded.last_run,
                        last_target = excluded.last_target,
                        updated_at = excluded.updated_at
                """, (row["rule"], row["severity"], row["kind"], run_id, run_id,
                      row["target"][:120], now))
        return len(rows)

    # ── 读 ──
    def stats(self) -> Dict[str, Any]:
        """命中排行 + **从没命中过的规则**。"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(
                "SELECT rule, severity, kind, hits, first_run, last_run, last_target "
                "FROM rule_hits ORDER BY hits DESC, rule")]
        known = {(r["rule"], r["severity"]) for r in rows}
        never = [r for r in registered_rules()
                 if (r["rule"], r["severity"]) not in known
                 and (r["rule"], "") not in known]
        return {
            "rules": rows,
            "never_hit": sorted(never, key=lambda r: r["rule"]),
            "total_hits": sum(r["hits"] for r in rows),
            "rules_seen": len(rows),
            "db": str(self.db_path),
        }


def record_rule_hits(issues: Iterable[Any], run_id: str = "",
                     db_path: str = None) -> int:
    """便捷入口。**失败不抛** —— 统计是旁路，不该拖垮生成流程。"""
    try:
        return RuleStats(db_path).record(issues, run_id=run_id)
    except Exception:                                  # noqa: BLE001
        return 0
