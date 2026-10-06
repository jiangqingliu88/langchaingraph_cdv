# src/regression_framework/reporters/trend_db.py
"""
趋势数据库 - 将每次回归的结果存入 SQLite，支持历史趋势分析。

表结构:
  runs: 每次回归的摘要 (timestamp, total, pass, fail, unknown, pass_rate)
  task_details: 每个任务的详细信息 (task_name, status, sim_time, wave_path, work_dir, fingerprint)
"""
import os
import sqlite3
from datetime import datetime
from typing import List

from ..core.logging_config import get_logger

logger = get_logger(__name__)


class TrendDatabase:
    """SQLite 趋势数据库管理器"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(os.getcwd(), "regression_trend.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total INTEGER DEFAULT 0,
                pass INTEGER DEFAULT 0,
                fail INTEGER DEFAULT 0,
                unknown INTEGER DEFAULT 0,
                pass_rate REAL DEFAULT 0.0,
                total_time TEXT,
                root_dir TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS task_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                task_name TEXT NOT NULL,
                status TEXT DEFAULT 'unknown',
                sim_time REAL DEFAULT 0.0,
                wave_path TEXT,
                work_dir TEXT,
                fingerprint TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(id)
            )''')
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to initialize trend DB: {e}")

    def save(self, tasks: List, root_dir: str = ""):
        """
        保存本次回归结果到数据库。

        Args:
            tasks: Task 对象列表
            root_dir: 本次回归的根目录
        """
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # 统计
            stats = {'pass': 0, 'fail': 0, 'unknown': 0}
            for task in tasks:
                stats[task.status] += 1
            total = len(tasks)
            pass_rate = (stats['pass'] / total * 100) if total > 0 else 0.0

            # 计算总耗时
            total_time = "N/A"
            if tasks:
                max_elapsed = max((getattr(t, 'elapsed', 0) or 0) for t in tasks)
                if max_elapsed > 0:
                    hours, rem = divmod(max_elapsed, 3600)
                    minutes, seconds = divmod(rem, 60)
                    total_time = f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"

            # 插入 runs 表
            c.execute('''INSERT INTO runs (timestamp, total, pass, fail, unknown, pass_rate, total_time, root_dir)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                      (datetime.now().isoformat(), total, stats['pass'], stats['fail'],
                       stats['unknown'], pass_rate, total_time, root_dir))
            run_id = c.lastrowid

            # 插入 task_details 表
            for task in tasks:
                c.execute('''INSERT INTO task_details
                             (run_id, task_name, status, sim_time, wave_path, work_dir, fingerprint)
                             VALUES (?, ?, ?, ?, ?, ?, ?)''',
                          (run_id, task.name, task.status,
                           getattr(task, 'sim_time', 0.0) or 0.0,
                           getattr(task, 'wave_path', None),
                           task.work_dir,
                           getattr(task, 'fingerprint', 'unknown')))

            conn.commit()
            conn.close()
            logger.info(f"Trend data saved to {self.db_path} (run_id={run_id})")
        except Exception as e:
            logger.warning(f"Failed to save trend data: {e}")

    def query_history(self, limit: int = 10):
        """查询最近 N 次回归的历史记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''SELECT id, timestamp, total, pass, fail, unknown, pass_rate, total_time
                         FROM runs ORDER BY id DESC LIMIT ?''', (limit,))
            rows = c.fetchall()
            conn.close()
            return [
                {
                    "id": r[0], "timestamp": r[1], "total": r[2],
                    "pass": r[3], "fail": r[4], "unknown": r[5],
                    "pass_rate": r[6], "total_time": r[7]
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"Failed to query history: {e}")
            return []

    def query_task_history(self, task_name: str, limit: int = 10):
        """查询特定任务的历史记录"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''SELECT r.timestamp, td.status, td.sim_time, td.work_dir
                         FROM task_details td
                         JOIN runs r ON td.run_id = r.id
                         WHERE td.task_name = ?
                         ORDER BY r.id DESC LIMIT ?''', (task_name, limit))
            rows = c.fetchall()
            conn.close()
            return [
                {"timestamp": r[0], "status": r[1], "sim_time": r[2], "work_dir": r[3]}
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"Failed to query task history: {e}")
            return []
