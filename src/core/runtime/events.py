"""EventStore —— 执行事实的**单一追加日志**。

边界（很关键）
    仓库里已经有三份过程记录：`docs/run_events.jsonl`（RunJournal，给界面实时看）、
    `docs/tool_receipts.jsonl`（工具回执）、`coverage/round_manifest.json`（轮次
    事实表）。本模块**不替代它们，也不复制它们**：

      · run/stage/decision/approval/coverage 事件：由 `_stream_run` 在**一个**
        位置把 RunJournal 的事件镜像进来（source="journal"）；
      · 其余事实（job.* / artifact.produced / decision.evaluated / round.facts /
        provenance.built / quality.gate）由各自的产生者写一次。

    于是同一件事只有一个 appender，不存在"两份日志谁对"的问题。

格式：`<run>/docs/events.jsonl`，一行一个 JSON。只追加、seq 单调、只放可 JSON
化的东西 —— 与 RunJournal 同一条纪律。
"""
from __future__ import annotations
from src.core.contracts import versions

import contextvars
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = versions.EVENTS

#: 环境变量关闭事件日志（测试 / 兼容旧 run 目录时用）。
ENV_FLAG = "SIGNOFFAI_EVENT_STORE"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _jsonable(value: Any, _depth: int = 0) -> Any:
    """把任意值压成有界、可序列化的形状。大对象只留引用或摘要。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if _depth >= 4:
        return repr(value)[:500]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v, _depth + 1)
                for k, v in list(value.items())[:100]}
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        out = [_jsonable(v, _depth + 1) for v in items[:50]]
        if len(items) > 50:
            out.append({"_truncated": True, "_total": len(items)})
        return out
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)[:500]


class EventStore:
    """`<run>/docs/events.jsonl` 的追加写入器。线程安全，可重开续写。"""

    def __init__(self, output_root: str | Path, run_id: str = "",
                 enabled: Optional[bool] = None):
        self.output_root = Path(output_root)
        self.run_id = run_id or self.output_root.name
        if enabled is None:
            enabled = os.environ.get(ENV_FLAG, "on").strip().lower() != "off"
        self.enabled = bool(enabled)
        self.path = self.output_root / "docs" / "events.jsonl"
        self._lock = threading.RLock()
        self._seq = 0
        self._seen: set = set()
        if self.enabled:
            self._path().parent.mkdir(parents=True, exist_ok=True)
            self._load()

    # ── 生命周期 ──

    def _path(self) -> Path:
        return self.path

    def _load(self) -> None:
        """续写时从最后一行恢复 seq，并记住已写入的 dedup key。"""
        try:
            with self._path().open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        doc = json.loads(line)
                    except ValueError:
                        continue          # 崩溃留下的半行，跳过即可
                    self._seq = max(self._seq, int(doc.get("seq", 0) or 0))
                    key = doc.get("dedup_key")
                    if key:
                        self._seen.add(str(key))
        except FileNotFoundError:
            return
        except OSError:
            return

    # ── 写 ──

    def append(self, event_type: str, *, stage: str = "", agent: str = "",
               round: int = 0, status: str = "", job_id: str = "",
               payload: Optional[Dict[str, Any]] = None, source: str = "",
               dedup_key: str = "") -> Optional[Dict[str, Any]]:
        """追加一条事实。重复的 `dedup_key` 直接跳过（节点重跑是常态）。

        返回写入的事件；被去重或日志关闭时返回 None。
        """
        if not self.enabled:
            return None
        with self._lock:
            key = str(dedup_key or "")
            if key and key in self._seen:
                return None
            self._seq += 1
            event = {
                "schema": SCHEMA,
                "seq": self._seq,
                "ts": _now(),
                "run_id": self.run_id,
                "round": int(round or 0),
                "stage": str(stage or ""),
                "agent": str(agent or ""),
                "event_type": str(event_type or ""),
                "status": str(status or ""),
                "job_id": str(job_id or ""),
                "source": str(source or ""),
                "payload": _jsonable(payload or {}),
            }
            if key:
                event["dedup_key"] = key
                self._seen.add(key)
            try:
                with self._path().open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
                    fh.flush()
            except OSError:
                # 事件日志是观测手段，不是流程的一部分 —— 写失败不能让 run 崩
                self._seq -= 1
                if key:
                    self._seen.discard(key)
                return None
            return event

    # ── 读 ──

    def read(self, event_type: Optional[str] = None,
             round_num: Optional[int] = None) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            with self._path().open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        doc = json.loads(line)
                    except ValueError:
                        continue
                    if event_type and doc.get("event_type") != event_type:
                        continue
                    if round_num is not None and int(doc.get("round", 0)) != round_num:
                        continue
                    out.append(doc)
        except OSError:
            return out
        return out


class Spool:
    """没有绑定 run 时的缓冲 —— `n_finalize` 一次性灌进 run 的 EventStore。"""

    def __init__(self, maxlen: int = 1024):
        self.maxlen = maxlen
        self._items: List[Dict[str, Any]] = []
        self._keys: set = set()
        self._lock = threading.RLock()

    def emit(self, event_type: str, *, round: int = 0, stage: str = "",
             agent: str = "", status: str = "", job_id: str = "",
             payload: Optional[Dict[str, Any]] = None, source: str = "",
             dedup_key: str = "") -> None:
        key = str(dedup_key or "")
        with self._lock:
            if key and key in self._keys:
                return
            if key:
                self._keys.add(key)
            if len(self._items) >= self.maxlen:
                self._items.pop(0)       # 缓冲不是证据，溢出丢最旧
            self._items.append({
                "event_type": event_type, "round": int(round or 0),
                "stage": stage, "agent": agent, "status": status,
                "job_id": job_id, "payload": _jsonable(payload or {}),
                "source": source, "dedup_key": key,
            })

    def drain(self) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
            self._keys.clear()
            return items

    def __len__(self) -> int:
        return len(self._items)


_SPOOL = Spool()
_ACTIVE_STORE: "contextvars.ContextVar[Optional[EventStore]]" = contextvars.ContextVar(
    "signoffai_event_store", default=None)


def set_active_store(store: Optional[EventStore]):
    """在当前执行上下文里指定默认 EventStore；返回 token 供 reset。"""
    return _ACTIVE_STORE.set(store)


def active_store() -> Optional[EventStore]:
    return _ACTIVE_STORE.get()


def emit(event_type: str, **kwargs) -> Optional[Dict[str, Any]]:
    """路由：有活动 store 就写 store，否则进 Spool。**永远不抛**。"""
    store = _ACTIVE_STORE.get()
    try:
        if store is not None:
            return store.append(event_type, **kwargs)
        _SPOOL.emit(event_type, **kwargs)
        return None
    except Exception:                      # noqa: BLE001 观测不能带崩主流程
        return None


def flush_spool(store: Optional[EventStore], spool: Optional[Spool] = None) -> int:
    """把 Spool 灌进 store（只灌一次）。返回灌入条数。"""
    if store is None:
        return 0
    written = 0
    for item in (spool or _SPOOL).drain():
        dedup = item.pop("dedup_key", "")
        item["dedup_key"] = dedup
        if store.append(item.pop("event_type"), **item) is not None:
            written += 1
    return written
