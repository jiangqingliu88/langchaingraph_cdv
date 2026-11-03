"""质量门的词汇与总状态规则 —— 一处定义，证据/CLI/Workbench 共用。"""
from __future__ import annotations

DIMENSIONS = ("functional", "coverage", "model", "structural", "evidence")

STATUSES = ("pass", "warn", "fail", "unknown", "not_applicable")

#: 质量门执行策略：report（只报告）/ warn（告警）/ block（硬门禁）。
#: 默认 report；升级 block 要同步 caveat code 与 mutation。
ENFORCEMENT_MODES = ("report", "warn", "block")

#: 总状态优先级：fail > unknown > warn > pass；not_applicable 不拉高不拉低。
_RANK = {"pass": 0, "not_applicable": 0, "warn": 1, "unknown": 2, "fail": 3}


def overall_status(statuses) -> str:
    """从各维度状态合成总状态。`unknown` 不折算成 pass。"""
    overall = "pass"
    for status in statuses:
        status = str(status or "unknown")
        if status not in _RANK:
            status = "unknown"
        if _RANK[status] > _RANK[overall]:
            overall = status
    return "unknown" if overall == "not_applicable" else overall
