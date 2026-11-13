"""State contract guard for agent nodes (moved from old graph.py)."""
from __future__ import annotations

import functools
import os

import structlog

from src.layers.l2_orchestration.state import (
    CRITICAL_STATE_FIELDS, unexpected_state_writers,
)

logger = structlog.get_logger()
_STATE_WARNED: set[tuple[str, str]] = set()


def _guarded_node(name: str, fn):
    """包一层 State 契约检查：越权写关键字段 → 硬失败，其余 → warning。"""
    if getattr(fn, "__state_guard__", False):
        return fn

    @functools.wraps(fn)
    async def _wrapped(state, config):
        update = await fn(state, config)
        if isinstance(update, dict):
            bad = unexpected_state_writers(name, update)
            strict = os.environ.get(
                "SIGNOFFAI_STATE_CONTRACT", "strict").strip().lower() != "warn"
            critical = [f for f in bad if f in CRITICAL_STATE_FIELDS]
            if strict and critical:
                raise RuntimeError(
                    f"State 契约违规（硬失败）: 节点 {name!r} 写了不属于它的关键"
                    f"字段 {critical}（写入者见 state.STATE_CONTRACTS；"
                    f"如确属无害，用 SIGNOFFAI_STATE_CONTRACT=warn 退回告警）")
            for field in bad:
                key = (name, field)
                if key in _STATE_WARNED:
                    continue
                _STATE_WARNED.add(key)
                logger.warning(
                    f"State 契约告警: 节点 {name!r} 写了不属于它的字段 "
                    f"{field!r}（写入者见 state.STATE_CONTRACTS）")
        return update

    _wrapped.__state_guard__ = True
    return _wrapped


__all__ = ["_guarded_node"]
