"""
State Encoder —— 把 Observation 编码成 RL 可用的离散状态（V3 决策学习层）

V3 的 RL 需要「状态 → 动作」的映射。Observation 是结构化对象（coverage/gaps/gap_paths），
不能直接当状态，这里降维成离散状态 key：

    state = "cov:<bucket>|reason:<dominant_reason>|sugg:<dominant_suggestion>"

- cov bucket：覆盖率分桶（<80 / 80-target / >=target）
- reason：dominant gap reason（constraint / unstimulated / unreachable / none）
- suggestion：dominant 语义建议（RELAX_CONSTRAINT / GENERATE_DIRECTED_TEST / INVESTIGATE / none）

这是「语义状态」——把 V2 的 gap_paths 语义归因编码进状态，让 RL 学的不是「覆盖率数字」，
而是「哪类语义 gap 在哪个覆盖率阶段，用哪个动作最有效」。

用法:
    from src.layers.l3_decision.brain.state_encoder import encode_state
    key = encode_state(obs)   # "cov:80_90|reason:constraint|sugg:RELAX_CONSTRAINT"
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _coverage_bucket(functional: float, target: float) -> str:
    if functional >= target:
        return "at_target"
    if functional >= 80:
        return "80_target"
    return "below_80"


def _dominant_reason(gaps: List[Dict]) -> str:
    reasons = [g.get("reason") for g in gaps or []
               if isinstance(g, dict) and g.get("reason")]
    if not reasons:
        return "none"
    # 优先级：unreachable > constraint > unstimulated（跟决策规则一致）
    for r in ("unreachable", "constraint", "unstimulated"):
        if r in reasons:
            return r
    return reasons[0]


def _dominant_suggestion(gap_paths: List[Dict]) -> str:
    suggs = [g.get("suggestion") for g in gap_paths or []
             if isinstance(g, dict) and g.get("suggestion")]
    if not suggs:
        return "none"
    # 优先级：RELAX_CONSTRAINT（已有测试约束过紧）> GENERATE_DIRECTED_TEST
    for s in ("RELAX_CONSTRAINT", "GENERATE_DIRECTED_TEST"):
        if s in suggs:
            return s
    return suggs[0]


def encode_state(observation, target: float = 95.0) -> str:
    """把 Observation 编码成离散状态 key。"""
    cov = observation.coverage or {}
    functional = float(cov.get("functional", 0) or 0)
    bucket = _coverage_bucket(functional, target)
    reason = _dominant_reason(observation.gaps)
    suggestion = _dominant_suggestion(observation.gap_paths)
    return f"cov:{bucket}|reason:{reason}|sugg:{suggestion}"


def decode_state(state: str) -> Dict[str, str]:
    """把状态 key 解码回 dict（调试/可解释性用）。"""
    parts = {}
    for kv in state.split("|"):
        if ":" in kv:
            k, v = kv.split(":", 1)
            parts[k] = v
    return parts
