"""历史决策/失败案例仅作参考，不能自动晋升为当前设计规范。"""

from __future__ import annotations

from typing import Any


class ExperienceReferences:
    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self._records = records or []

    def recall(self, domain: str) -> list[dict[str, Any]]:
        out = []
        for index, row in enumerate(self._records):
            if row.get("domain") and row["domain"] != domain:
                continue
            out.append(
                {
                    "reference_id": str(row.get("reference_id") or row.get("id") or f"EXP-{index + 1}"),
                    "summary": str(row.get("summary") or row.get("content") or ""),
                    "outcome": str(row.get("outcome") or ""),
                    "normative_for_current_design": False,
                    "status": "ADVISORY_ONLY",
                }
            )
        return out


__all__ = ["ExperienceReferences"]
