"""executor 节点 · 签核

审查：跑签核门禁，出通过/待修结论。
"""
from __future__ import annotations

from typing import Any, Dict

import structlog

from src.orchestration_plane.l2.runtime import (
    _rt, _run_agent,
)
from src.orchestration_plane.l2.state import PipelineState

logger = structlog.get_logger()


async def n_audit(state: PipelineState, config) -> Dict[str, Any]:
    """签核 audit —— 每条退出路径都要跑（包括 eda_blocked）。"""
    rt = _rt(config)
    # 退出路径可能没经过 round_bump（eda_blocked / abort）—— 签核前补记
    # **最后完成的轮次**。正常路径 round_bump 已把 round_num 推到下一轮，
    # 这里必须记 `round_num - 1`，否则同一轮会被写成两条（轮次双计）。
    try:
        from src.orchestration_plane.l2.evidence.round_facts import (
            record_round_facts)

        _round = state.round_num - 1 if state.round_num > 1 else state.round_num
        record_round_facts(state.output_root, _round)
    except Exception as _e:                        # noqa: BLE001 证据旁路
        logger.warning(f"round 事实表写入失败: {_e}")
    data, phase = await _run_agent(rt, state, "audit", "audit")
    updates: Dict[str, Any] = {"phases": [phase]}
    if isinstance(data.get("audit"), dict):
        updates["audit"] = data["audit"]
    return updates


