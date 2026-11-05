"""签核三态判定 —— **唯一实现**。

audit 与离线回放（`signoff_package.replay_tier_a` / 生成的 `replay.py`）必须
用同一套规则；各写一份必然漂移（实测风险：audit 判 PASS、replay 判 NEEDS_FIX）。

规则：

    hard_ok=False                     → NEEDS_FIX
    hard_ok=True + 未接受的 caveat     → PASS_WITH_CAVEAT
    hard_ok=True + 无有效 caveat       → READY

`accepted_codes` 来自模块签核策略；caveat 的机器码是稳定的，文案可以改。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set

VERDICT_READY = "READY"
VERDICT_CAVEAT = "PASS_WITH_CAVEAT"
VERDICT_FIX = "NEEDS_FIX"

STATUS = {
    VERDICT_READY: "APPROVED",
    VERDICT_CAVEAT: "CONDITIONAL",
    VERDICT_FIX: "REJECTED",
}


def accepted_codes_from_policy(policy: Dict[str, Any] | None) -> Set[str]:
    accepted = (policy or {}).get("accepted_caveats") or {}
    return {str(code) for code, val in accepted.items()
            if isinstance(val, dict) and val.get("accepted")}


def effective_caveats(raw: Iterable[Dict[str, Any]] | None,
                      accepted_codes: Iterable[str] | None) -> List[Dict[str, Any]]:
    accepted = {str(c) for c in (accepted_codes or ())}
    return [c for c in (raw or [])
            if isinstance(c, dict) and str(c.get("code") or "") not in accepted]


def decide_verdict(*, hard_ok: bool,
                   raw_caveats: Iterable[Dict[str, Any]] | None,
                   accepted_codes: Iterable[str] | None) -> str:
    if not hard_ok:
        return VERDICT_FIX
    return VERDICT_CAVEAT if effective_caveats(raw_caveats, accepted_codes) else VERDICT_READY


def signoff_status(verdict: str) -> str:
    return STATUS.get(str(verdict), "REJECTED")
