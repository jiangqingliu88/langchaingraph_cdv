"""
SSE (Server-Sent Events) — 实时管线状态推送

SignOffAI 使用 SSE 而非 WebSocket:
  - 单向推送（server → client），无需双向通信
  - 浏览器原生支持 EventSource API
  - 更适合管线状态监控场景
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Dict, List

# 全局 SSE 频道: run_id → [asyncio.Queue, ...]
_subscribers: Dict[str, List[asyncio.Queue]] = {}


async def subscribe(run_id: str) -> asyncio.Queue:
    """订阅某个 run 的状态更新，返回消息队列"""
    q = asyncio.Queue()
    if run_id not in _subscribers:
        _subscribers[run_id] = []
    _subscribers[run_id].append(q)
    return q


def unsubscribe(run_id: str, q: asyncio.Queue):
    """取消订阅"""
    if run_id in _subscribers and q in _subscribers[run_id]:
        _subscribers[run_id].remove(q)


async def publish(run_id: str, event: str, data: dict):
    """向所有订阅者推送事件"""
    if run_id not in _subscribers:
        return
    msg = json.dumps({"event": event, "data": data, "timestamp": datetime.now().isoformat()})
    dead = []
    for q in _subscribers[run_id]:
        try:
            await q.put(msg)
        except Exception:
            dead.append(q)
    for q in dead:
        _subscribers[run_id].remove(q)


async def notify_phase_update(run_id: str, phase_name: str, status: str, score: int, elapsed: float):
    """推送阶段更新"""
    await publish(run_id, "phase_update", {
        "phase": phase_name, "status": status, "score": score, "elapsed": round(elapsed, 1),
    })


async def notify_run_complete(run_id: str, passed: int, total: int, overall_score: int):
    """推送运行完成"""
    await publish(run_id, "run_complete", {
        "passed": passed, "total": total, "overall_score": overall_score,
    })

# 供 api.py 调用的便捷函数
_sse_notify_phase = notify_phase_update
_sse_notify_complete = notify_run_complete
