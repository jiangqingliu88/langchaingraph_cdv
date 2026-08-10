"""
多 Agent 共享上下文 —— 三层分离 + 字段级 consumes + 数据溯源

  三层:
    config  — 只读运行配置 (working_dir, workflow)
    state   — 执行状态 (phases, scores, timestamps)
    data    — ContextStore: 数据通道，支持字段级读写，自动溯源，消费后清理
"""

from __future__ import annotations

import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# ═══════════════════════════════════════════════════════════════
# ContextEntry — 带溯源的数据包装
# ═══════════════════════════════════════════════════════════════

@dataclass
class ContextEntry:
    """数据通道中的单个条目，带溯源信息"""
    value: Any
    source: str           # agent role name
    timestamp: float = field(default_factory=time.time)
    version: int = 1


# ═══════════════════════════════════════════════════════════════
# ConsumesTopology — 数据消费拓扑
# ═══════════════════════════════════════════════════════════════

# 每个 ctx key 被哪些 agent 消费（用于自动清理）
_CONSUMES_TOPOLOGY: Dict[str, List[str]] = {
    "spec":        ["design_architect", "model_agent", "write_rtl", "verification_architect"],
    "design_arch": ["model_agent", "write_rtl"],
    "model":       [],
    "rtl":         ["verification_architect", "test_engineer"],
    "env":         ["test_engineer", "regression_manager"],
    "tests":       ["regression_manager"],
    "regression":  ["coverage_manager", "debug_engineer"],
    "coverage":    ["quality_assurance"],
    "debug":       [],
}


# ═══════════════════════════════════════════════════════════════
# ContextStore — 数据通道专用管理
# ═══════════════════════════════════════════════════════════════

class ContextStore:
    """Agent 间数据通道，支持字段级读写、溯源标记、自动清理。

    用法:
      store = ContextStore()
      store.put("spec", {"features": [...], "test_points": [...]},
                source="spec_planner")
      # 下游只取需要的字段
      features = store.get("spec", fields=["features"])
      # 消费完成后自动清理
      store.prune(["design_architect", "model_agent"])
    """

    def __init__(self):
        self._data: Dict[str, ContextEntry] = {}

    # ── 写入 ──

    def put(self, key: str, value: Any, source: str = "") -> None:
        """写入数据。如果 key 已存在，追加 version。"""
        old = self._data.get(key)
        new_version = (old.version + 1) if old else 1
        self._data[key] = ContextEntry(
            value=deepcopy(value) if isinstance(value, (dict, list)) else value,
            source=source,
            timestamp=time.time(),
            version=new_version,
        )

    def update(self, key: str, partial: dict, source: str = "") -> None:
        """合并更新已有条目（浅合并）。"""
        old = self._data.get(key)
        if old and isinstance(old.value, dict):
            merged = {**old.value, **partial}
            self.put(key, merged, source=source)
        else:
            self.put(key, partial, source=source)

    # ── 读取 ──

    def fetch(self, key: str, fields: List[str] = None) -> Optional[Any]:
        """读取数据。fields=None 返回全部；指定字段列表只返回子集。"""
        entry = self._data.get(key)
        if entry is None:
            return None
        value = entry.value
        if fields is None:
            return value
        if not isinstance(value, dict):
            return value
        return {f: value[f] for f in fields if f in value}

    def get_entry(self, key: str) -> Optional[ContextEntry]:
        """读取完整条目（含溯源信息）。"""
        return self._data.get(key)

    def has(self, key: str) -> bool:
        return key in self._data

    def keys(self) -> Set[str]:
        return set(self._data.keys())

    # ── 生命周期 ──

    def prune(self, completed_agent_roles: List[str]) -> List[str]:
        """清理所有消费者都已完成的 key。返回被清理的 key 列表。"""
        removed = []
        for key, consumers in _CONSUMES_TOPOLOGY.items():
            if key not in self._data:
                continue
            if not consumers:
                continue
            if all(c in completed_agent_roles for c in consumers):
                del self._data[key]
                removed.append(key)
        return removed

    def snapshot(self) -> dict:
        """返回当前所有数据的纯值副本（不含溯源）。"""
        return {k: e.value for k, e in self._data.items()}

    # ── Dict-compatible API (for backward compat) ──

    def __getitem__(self, key: str) -> Any:
        entry = self._data.get(key)
        if entry is None:
            raise KeyError(key)
        return entry.value

    def __setitem__(self, key: str, value: Any) -> None:
        self.put(key, value, source="direct")

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str, default: Any = None) -> Any:
        """dict-compatible get: returns value or default."""
        entry = self._data.get(key)
        return entry.value if entry else default

    # ═══════════════════════════════════════════════════════
    # 持久化 — SQLite 版本链 + 断点续跑
    # ═══════════════════════════════════════════════════════

    _DB_SCHEMA = """
    CREATE TABLE IF NOT EXISTS commits (
        version     INTEGER NOT NULL,
        step_name   TEXT    NOT NULL DEFAULT '',
        timestamp   REAL   NOT NULL,
        parent_version INTEGER,
        key         TEXT   NOT NULL,
        value_json  TEXT   NOT NULL,
        source      TEXT   NOT NULL DEFAULT '',
        PRIMARY KEY (version, key)
    );
    CREATE INDEX IF NOT EXISTS idx_commits_version ON commits(version);
    """

    def enable_persistence(self, db_path: str) -> None:
        """启用 SQLite 持久化。每次 put() 后自动 commit。"""
        import sqlite3, os
        os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.executescript(self._DB_SCHEMA)
        self._db.commit()
        self._db_path = db_path
        self._auto_save = True

    def save(self, step_name: str = "") -> int:
        """将当前状态保存为新的 version。返回 version 号。"""
        if not hasattr(self, '_db'):
            return -1
        # 计算新版本号
        cur = self._db.execute("SELECT COALESCE(MAX(version),0)+1 FROM commits")
        new_version = cur.fetchone()[0]
        parent = new_version - 1 if new_version > 1 else None
        ts = time.time()
        # 写入所有当前 key
        for key, entry in self._data.items():
            value_json = json.dumps(entry.value, ensure_ascii=False, default=str)
            self._db.execute(
                "INSERT INTO commits(version,step_name,timestamp,parent_version,key,value_json,source) "
                "VALUES(?,?,?,?,?,?,?)",
                (new_version, step_name, ts, parent, key, value_json,
                 entry.source))
        self._db.commit()
        return new_version

    def load(self, version: int = -1) -> int:
        """从数据库恢复到指定版本 (-1 = 最新)。返回加载的版本号。"""
        if not hasattr(self, '_db'):
            return -1
        if version < 0:
            cur = self._db.execute("SELECT MAX(version) FROM commits")
            row = cur.fetchone()
            version = row[0] if row and row[0] else 0
        if version == 0:
            return 0
        # 清空内存
        self._data.clear()
        # 加载指定版本
        for row in self._db.execute(
            "SELECT key, value_json, source, timestamp FROM commits WHERE version=?",
            (version,)
        ):
            key, value_json, source, ts = row
            value = json.loads(value_json)
            self._data[key] = ContextEntry(
                value=value, source=source, timestamp=ts,
                version=version)
        return version

    def list_versions(self) -> List[dict]:
        """列出所有版本及其步骤信息。"""
        if not hasattr(self, '_db'):
            return []
        rows = self._db.execute(
            "SELECT DISTINCT version, step_name, timestamp, parent_version FROM commits ORDER BY version"
        ).fetchall()
        return [
            {"version": r[0], "step_name": r[1],
             "timestamp": r[2], "parent_version": r[3]}
            for r in rows
        ]

    def restore(self, version: int) -> bool:
        """回滚到指定版本（Config 不变，只恢复 State/Data）。"""
        loaded = self.load(version)
        return loaded == version

    # ── 自动保存 ──

    def put(self, key: str, value: Any, source: str = "",
            step_name: str = "") -> None:
        """写入数据。如果启用了持久化，自动 save。"""
        old = self._data.get(key)
        new_version = (old.version + 1) if old else 1
        self._data[key] = ContextEntry(
            value=deepcopy(value) if isinstance(value, (dict, list)) else value,
            source=source, timestamp=time.time(),
            version=new_version,
        )
        # 自动持久化
        if hasattr(self, '_auto_save') and self._auto_save:
            self.save(step_name or source)

    def __repr__(self) -> str:
        items = ", ".join(
            f"{k}(v{e.version})" for k, e in self._data.items()
        )
        return f"ContextStore({items})"

    def summary(self) -> Dict[str, Any]:
        """返回扁平摘要（对标原型的 ctx 字典视图）。
        不替代分层结构，只提供快速概览。"""
        import time
        return {
            "keys": list(self._data.keys()),
            "entry_count": len(self._data),
            "sources": list(set(e.source for e in self._data.values())),
            "latest_timestamp": max(
                (e.timestamp for e in self._data.values()), default=0
            ),
            "snapshot": self.snapshot(),
        }


# ═══════════════════════════════════════════════════════════════
# Pydantic Schema (保留兼容)
# ═══════════════════════════════════════════════════════════════

from pydantic import BaseModel, Field as PydField   # noqa: E402


class SpecContext(BaseModel):
    test_points: List[dict] = PydField(default_factory=list)
    features: List[dict]    = PydField(default_factory=list)
    interfaces: List[dict]  = PydField(default_factory=list)
    registers: List[dict]   = PydField(default_factory=list)
    coverage_goals: dict    = PydField(default_factory=dict)
    verification_architecture: dict = PydField(default_factory=dict)
    design_name: str = PydField(default="")
    version: str     = PydField(default="")
    overview: str    = PydField(default="")


class DesignArchContext(BaseModel):
    module_name: str       = PydField(default="")
    function_hier: dict    = PydField(default_factory=dict)
    registers: List[dict]  = PydField(default_factory=list)
    signoff_checklist: List[dict] = PydField(default_factory=list)


class EnvContext(BaseModel):
    env_name: str    = PydField(default="")
    output_dir: str  = PydField(default="")
    filelist: str    = PydField(default="")
    agent_count: int = PydField(default=0)
    agents: List[str] = PydField(default_factory=list)
    files: List[str]  = PydField(default_factory=list)


class TestsContext(BaseModel):
    test_names: List[str]   = PydField(default_factory=list)
    test_count: int         = PydField(default=0)
    scenario_count: int     = PydField(default=0)
    scenarios: List[dict]   = PydField(default_factory=list)
    test_cases: List[dict]  = PydField(default_factory=list)


class RegressionContext(BaseModel):
    compile: str       = PydField(default="")
    compile_status: str = PydField(default="")
    passed: int        = PydField(default=0)
    failed: int        = PydField(default=0)
    total: int         = PydField(default=0)
    pass_rate: str     = PydField(default="")
    tests: List[dict]  = PydField(default_factory=list)


class CoverageContext(BaseModel):
    line_pct: float      = PydField(default=0.0)
    branch_pct: float    = PydField(default=0.0)
    toggle_pct: float    = PydField(default=0.0)
    coverage_pct: float  = PydField(default=0.0)
    gaps: List[dict]     = PydField(default_factory=list)
    suggestions: List[dict] = PydField(default_factory=list)
