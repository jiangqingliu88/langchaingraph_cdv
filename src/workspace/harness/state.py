"""显式状态机 —— 状态、合法转移、与非法转移的响亮失败。"""
from __future__ import annotations

from enum import Enum
from typing import Callable, Dict, Optional, Set


class HarnessState(str, Enum):
    NEW = "new"
    PLANNING = "planning"
    AWAITING_PLAN = "awaiting_plan"
    ACTING = "acting"
    OBSERVING = "observing"
    PROPOSING = "proposing"
    PAUSED = "paused"
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    FAILED = "failed"


TRANSITIONS: Dict[HarnessState, Set[HarnessState]] = {
    HarnessState.NEW: {HarnessState.PLANNING, HarnessState.BLOCKED, HarnessState.FAILED},
    HarnessState.PLANNING: {
        HarnessState.AWAITING_PLAN, HarnessState.ACTING, HarnessState.PROPOSING,
        HarnessState.PAUSED, HarnessState.DONE, HarnessState.BLOCKED,
        HarnessState.CANCELLED, HarnessState.FAILED,
    },
    HarnessState.AWAITING_PLAN: {
        HarnessState.PLANNING, HarnessState.CANCELLED, HarnessState.FAILED,
    },
    HarnessState.ACTING: {
        HarnessState.OBSERVING, HarnessState.PAUSED, HarnessState.BLOCKED,
        HarnessState.CANCELLED, HarnessState.FAILED,
    },
    HarnessState.OBSERVING: {
        HarnessState.PLANNING, HarnessState.PROPOSING, HarnessState.DONE,
        HarnessState.BLOCKED, HarnessState.CANCELLED, HarnessState.FAILED,
    },
    HarnessState.PROPOSING: {HarnessState.DONE, HarnessState.BLOCKED, HarnessState.FAILED},
    HarnessState.PAUSED: {
        HarnessState.PLANNING, HarnessState.ACTING, HarnessState.CANCELLED,
        HarnessState.BLOCKED, HarnessState.FAILED,
    },
    HarnessState.DONE: set(),
    HarnessState.BLOCKED: {HarnessState.PLANNING, HarnessState.CANCELLED},
    HarnessState.CANCELLED: set(),
    HarnessState.FAILED: set(),
}


class StateTransitionError(RuntimeError):
    pass


class StateMachine:
    def __init__(self, state: HarnessState = HarnessState.NEW,
                 on_transition: Optional[Callable[[HarnessState, HarnessState, str], None]] = None):
        self.state = HarnessState(state)
        self.on_transition = on_transition

    def can(self, target: HarnessState) -> bool:
        return HarnessState(target) in TRANSITIONS[self.state]

    def transition(self, target: HarnessState, reason: str = "") -> HarnessState:
        target = HarnessState(target)
        if target == self.state:
            return self.state
        if target not in TRANSITIONS[self.state]:
            raise StateTransitionError(
                f"非法状态转移：{self.state.value} → {target.value}（{reason}）")
        previous, self.state = self.state, target
        if self.on_transition is not None:
            self.on_transition(previous, target, reason)
        return target

    @property
    def terminal(self) -> bool:
        return not TRANSITIONS[self.state]
