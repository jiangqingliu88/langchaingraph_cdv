"""Verification state machine 1.0."""
from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    INTAKE = "intake"
    REQUIREMENT = "requirement"
    ARCHITECTURE = "architecture"
    PLANNING = "planning"
    GENERATE = "generate"
    EXECUTE = "execute"
    ANALYZE = "analyze"
    REPAIR = "repair"
    SIGNOFF = "signoff"
    BLOCKED = "blocked"
    DONE = "done"


ALLOWED = {
    Phase.INTAKE: {Phase.REQUIREMENT, Phase.BLOCKED},
    Phase.REQUIREMENT: {Phase.ARCHITECTURE, Phase.BLOCKED},
    Phase.ARCHITECTURE: {Phase.PLANNING, Phase.BLOCKED},
    Phase.PLANNING: {Phase.GENERATE, Phase.BLOCKED},
    Phase.GENERATE: {Phase.EXECUTE, Phase.BLOCKED},
    Phase.EXECUTE: {Phase.ANALYZE, Phase.BLOCKED},
    Phase.ANALYZE: {Phase.REPAIR, Phase.SIGNOFF, Phase.BLOCKED},
    Phase.REPAIR: {Phase.GENERATE, Phase.SIGNOFF, Phase.BLOCKED},
    Phase.SIGNOFF: {Phase.DONE, Phase.BLOCKED},
    Phase.BLOCKED: set(),
    Phase.DONE: set(),
}


class StateMachine:
    def __init__(self):
        self.phase = Phase.INTAKE

    def move(self, target: Phase) -> Phase:
        if target not in ALLOWED[self.phase]:
            raise ValueError(f"illegal transition {self.phase.value} -> {target.value}")
        self.phase = target
        return self.phase
