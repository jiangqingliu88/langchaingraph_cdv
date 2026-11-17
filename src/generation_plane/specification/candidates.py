"""Generation 产生候选 Requirement/Constraint，不负责批准设计意图。"""

from __future__ import annotations

from typing import Any, Callable

from src.mental_ir_plane.specification_compiler import SpecRequirement, SpecSchemaError, SpecStatus


class CandidateSynthesizer:
    def __init__(self, generator: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None) -> None:
        self._generator = generator

    def synthesize(
        self, document: dict[str, Any], *, source_id: str = "generation:candidates"
    ) -> tuple[list[SpecRequirement], dict[str, str]]:
        if self._generator is None:
            return [], {}
        draft = self._generator(document)
        if not isinstance(draft, list):
            raise SpecSchemaError("规格生成器必须返回候选列表")
        requirements = []
        for index, row in enumerate(draft):
            if not isinstance(row, dict):
                raise SpecSchemaError("候选 Requirement 必须是对象")
            field = str(row.get("field") or "")
            requirements.append(
                SpecRequirement(
                    requirement_id=str(row.get("requirement_id") or f"CAND-{field or index + 1}"),
                    field=field,
                    value=row.get("value"),
                    statement=str(row.get("statement") or row.get("text") or ""),
                    status=SpecStatus.DERIVED.value,
                    source_ids=[source_id],
                    intent_ids=list(row.get("intent_ids") or []),
                    rationale="Generation 候选，未获设计意图批准",
                    properties=dict(row.get("properties") or {}),
                )
            )
        source = {
            "source_id": source_id,
            "kind": "generation",
            "locator": "generated-candidates",
            "producer": "existing_generation_workflow",
        }
        return requirements, source


__all__ = ["CandidateSynthesizer"]
