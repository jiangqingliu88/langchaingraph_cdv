"""executor 节点 · 签核

审查：跑签核门禁，出通过/待修结论。
"""
from __future__ import annotations

from typing import Any, Dict

import structlog

from src.layers.l2_orchestration.runtime import (
    _rt, _run_agent,
)
from src.layers.l2_orchestration.state import PipelineState

logger = structlog.get_logger()


async def n_audit(state: PipelineState, config) -> Dict[str, Any]:
    """签核 audit —— 每条退出路径都要跑（包括 eda_blocked）。"""
    rt = _rt(config)
    data, phase = await _run_agent(rt, state, "audit", "audit")
    updates: Dict[str, Any] = {"phases": [phase]}
    if isinstance(data.get("audit"), dict):
        updates["audit"] = data["audit"]
    return updates


