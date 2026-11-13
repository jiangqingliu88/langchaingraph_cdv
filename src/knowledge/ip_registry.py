"""
IpRegistry —— IP 库（sqlite）：可复用的 IP 模块注册表。

设计意图：design agent 不再"一次性写死整个 RTL"，而是"先架构拆 IP →
LLM 写手逐个生成 IP 的 RTL → 集成连线成顶层"。IP 库是这一流程的真相源：
每个 IP 的元信息（类别/接口/功能描述/RTL/版本/状态）持久化，跨项目复用。

用法:
    from src.knowledge.ip_registry import IpRegistry
    reg = IpRegistry()
    reg.register_ip("uart_tx", "uart",
                    [{"name":"tx","dir":"output","width":1}],
                    "UART 串行发送：起始位+8数据位+停止位，波特率可配")
    reg.update_rtl("uart_tx", "module uart_tx(...) ...")
    reg.get_ip("uart_tx")
"""
from __future__ import annotations

from .sqlite_utils import connect

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# IP 状态机
STATUS_PLANNED = "planned"        # 已拆解，待生成 RTL
STATUS_GENERATED = "generated"    # RTL 已生成
STATUS_REUSED = "reused"          # 从库复用（非新生成）

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ip_registry (
    ip_name        TEXT PRIMARY KEY,
    category       TEXT NOT NULL DEFAULT '',
    interface      TEXT NOT NULL DEFAULT '[]',
    function_desc  TEXT NOT NULL DEFAULT '',
    tags           TEXT NOT NULL DEFAULT '',
    rtl_code       TEXT NOT NULL DEFAULT '',
    version        INTEGER NOT NULL DEFAULT 1,
    status         TEXT NOT NULL DEFAULT 'planned',
    created_at     TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL DEFAULT ''
);
"""


class IpRegistry:
    """IP 库（同步 sqlite，跨 run 持久）。"""

    def __init__(self, db_path: Optional[str | Path] = None):
        from config.paths import IP_DB

        self.db_path = Path(db_path) if db_path else IP_DB
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = connect(self.db_path)
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    # ═══════════════════════════════════════════════════════════
    # 注册 / 查询 / 更新
    # ═══════════════════════════════════════════════════════════

    def register_ip(self, ip_name: str, category: str,
                    interface: List[Dict] = None,
                    function_desc: str = "", tags: str = "") -> str:
        """注册一个 IP（幂等：已存在则不覆盖 RTL/版本，只更新元信息）。

        tags: 逗号分隔的搜索关键词（中英文），供 search_ip 语义匹配。
        """
        if not ip_name:
            return ""
        if not tags:
            tags = self._auto_tags(ip_name, category, function_desc)
        now = self._now()
        iface_json = json.dumps(interface or [], ensure_ascii=False)
        with self._lock:
            conn = self._connect()
            existing = conn.execute(
                "SELECT 1 FROM ip_registry WHERE ip_name=?", (ip_name,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE ip_registry SET category=?, interface=?, function_desc=?, "
                    "tags=?, updated_at=? WHERE ip_name=?",
                    (category, iface_json, function_desc, tags, now, ip_name))
            else:
                conn.execute(
                    "INSERT INTO ip_registry "
                    "(ip_name, category, interface, function_desc, tags, rtl_code, version, "
                    "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, '', 1, ?, ?, ?)",
                    (ip_name, category, iface_json, function_desc, tags,
                     STATUS_PLANNED, now, now))
            conn.commit()
        return ip_name

    def get_ip(self, ip_name: str) -> Optional[Dict[str, Any]]:
        """查询单个 IP 的完整信息。"""
        with self._lock:
            row = self._connect().execute(
                "SELECT * FROM ip_registry WHERE ip_name=?", (ip_name,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_by_category(self, category: str) -> List[Dict[str, Any]]:
        """按类别列出 IP。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT * FROM ip_registry WHERE category=? ORDER BY ip_name",
                (category,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_all(self) -> List[Dict[str, Any]]:
        """列出所有 IP。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT * FROM ip_registry ORDER BY category, ip_name").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_by_status(self, status: str) -> List[Dict[str, Any]]:
        """按状态列出 IP（planned 待生成 / generated 已生成 / reused 复用）。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT * FROM ip_registry WHERE status=? ORDER BY ip_name",
                (status,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search_ip(self, query: str, category: str = None, limit: int = 5) -> List[Dict[str, Any]]:
        """关键词搜索：query 分词匹配 IP 的 tags/desc/name，返回相似度排序的 IP 列表。

        搜索策略（多层）：
          1. 分词：英文按空格/下划线/位宽后缀分，中文按领域词典匹配
          2. 匹配：每个 IP 的 search_text = name + category + tags + desc
          3. 打分：命中 name 里的关键词 +2 分，命中 tags/desc +1 分
          4. 排序：分数降序，取 top-N
        """
        if not query:
            return []
        tokens = self._tokenize(query)
        if not tokens:
            return []
        scored = []
        for ip in self.list_all():
            if category and ip["category"] != category:
                continue
            search_text = (f"{ip['ip_name']} {ip['category']} "
                           f"{ip.get('tags', '')} {ip['function_desc']}").lower()
            name_lower = ip["ip_name"].lower()
            score = 0
            for t in tokens:
                if t in name_lower:
                    score += 2  # 命中 IP 名，高权重
                elif t in search_text:
                    score += 1  # 命中 tags/desc，中权重
            if score > 0:
                scored.append((score, ip))
        scored.sort(key=lambda x: -x[0])
        return [ip for _, ip in scored[:limit]]

    @staticmethod
    def _auto_tags(ip_name: str, category: str, function_desc: str) -> str:
        """自动生成搜索 tags：IP 名的单词 + 类别 + desc 里的中文领域词。"""
        tags = set()
        # IP 名的单词（下划线拆分）
        for w in ip_name.split("_"):
            if w and len(w) >= 2:
                tags.add(w)
        tags.add(category)
        # desc 里的中文领域词
        cn_keywords = ["发送", "接收", "收发", "中断", "定时器", "计数器", "看门狗",
                       "串行", "异步", "同步", "仲裁", "编码", "解码", "校验", "加密",
                       "时钟", "复位", "跨时钟", "脉冲", "移位", "比较", "乘法", "除法",
                       "读写", "分频", "门控", "流水线", "寄存器"]
        for kw in cn_keywords:
            if kw in function_desc:
                tags.add(kw)
        return ",".join(sorted(tags))

    @staticmethod
    def _tokenize(query: str) -> List[str]:
        """分词：英文按分隔符分，中文按领域词典匹配。"""
        import re
        q = query.lower()
        tokens = set()
        # 英文 token（按空格/下划线/位宽后缀/标点分）
        for t in re.split(r'[\s_/\[\]:,()]+', q):
            t = t.strip()
            if t and len(t) >= 2:
                tokens.add(t)
        # 中文领域词（常见验证/设计术语）
        cn_keywords = ["寄存器", "发送", "接收", "中断", "定时器", "计数器", "看门狗",
                       "串行", "异步", "同步", "仲裁", "编码", "解码", "校验", "加密",
                       "时钟", "复位", "跨时钟", "脉冲", "移位", "比较", "乘法", "除法",
                       "收发", "读写", "分频", "门控"]
        for kw in cn_keywords:
            if kw in query:
                tokens.add(kw)
        return list(tokens)

    def update_rtl(self, ip_name: str, rtl_code: str,
                   status: str = STATUS_GENERATED) -> bool:
        """更新 IP 的 RTL（版本 +1）。"""
        if not ip_name:
            return False
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT version FROM ip_registry WHERE ip_name=?", (ip_name,)).fetchone()
            if not row:
                return False
            conn.execute(
                "UPDATE ip_registry SET rtl_code=?, version=?, status=?, updated_at=? "
                "WHERE ip_name=?",
                (rtl_code, row[0] + 1, status, self._now(), ip_name))
            conn.commit()
        return True

    def mark_reused(self, ip_name: str) -> bool:
        """标记 IP 为复用（从库复用，非新生成）。"""
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT 1 FROM ip_registry WHERE ip_name=?", (ip_name,)).fetchone()
            if not row:
                return False
            conn.execute(
                "UPDATE ip_registry SET status=?, updated_at=? WHERE ip_name=?",
                (STATUS_REUSED, self._now(), ip_name))
            conn.commit()
        return True

    def stats(self) -> Dict[str, Any]:
        """IP 库统计。"""
        with self._lock:
            conn = self._connect()
            total = conn.execute("SELECT COUNT(*) FROM ip_registry").fetchone()[0]
            by_status = {}
            for r in conn.execute(
                    "SELECT status, COUNT(*) FROM ip_registry GROUP BY status").fetchall():
                by_status[r[0]] = r[1]
            by_category = {}
            for r in conn.execute(
                    "SELECT category, COUNT(*) FROM ip_registry GROUP BY category").fetchall():
                by_category[r[0]] = r[1]
        return {"total": total, "by_status": by_status, "by_category": by_category}

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        cols = ["ip_name", "category", "interface", "function_desc", "tags",
                "rtl_code", "version", "status", "created_at", "updated_at"]
        d = dict(zip(cols, row))
        try:
            d["interface"] = json.loads(d.get("interface") or "[]")
        except Exception:
            d["interface"] = []
        return d
