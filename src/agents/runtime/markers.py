"""Small pure marker nodes shared by expert subgraphs."""
from __future__ import annotations

from typing import Any


def marker(**updates: Any):
    async def _node(state, config):
        return dict(updates)
    return _node


__all__ = ["marker"]
