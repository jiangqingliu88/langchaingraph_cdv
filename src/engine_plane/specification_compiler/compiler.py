"""确定性 Specification Compiler。

Engine 只检查结构、来源绑定、冲突和确认状态；没有 Agent/LLM import，
不会把“模型推断”改写成“设计要求已经证明”。VALIDATED 只表示规格编译
就绪，不表示仿真或 Verification Signoff 已通过。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.ir_plane.specification_compiler import (
    READINESS_SCHEMA,
    ConflictRecord,
    GapRecord,
    LifecycleStage,
    SpecificationContract,
    SpecRequirement,
    SpecSchemaError,
    SpecSource,
    SpecStatus,
    contract_from,
)


@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: str = "ERROR"
    field: str = ""
    refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "field": self.field,
            "refs": self.refs,
        }


@dataclass
class CompilationResult:
    contract: SpecificationContract
    status: str
    issues: list[ValidationIssue]
    counts: dict[str, int]
    spec_hash: str
    traceability: list[dict[str, str]]

    @property
    def execution_allowed(self) -> bool:
        return self.status == "VALIDATED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": READINESS_SCHEMA,
            "status": self.status,
            "spec_hash": self.spec_hash,
            "execution_allowed": self.execution_allowed,
            "counts": self.counts,
            "issues": [issue.to_dict() for issue in self.issues],
            "traceability": self.traceability,
            "contract": self.contract.to_dict(),
            "boundary": "规格编译就绪不是 RTL 仿真或 Verification Signoff 通过",
        }


class SpecificationCompiler:
    """IR + Engine 的确定性编译器；required_fields 由 Knowledge 侧提供。"""

    def __init__(self, required_fields: tuple[str, ...] = ()) -> None:
        self.required_fields = tuple(dict.fromkeys(required_fields))

    def compile(self, document: SpecificationContract | dict[str, Any]) -> CompilationResult:
        contract = contract_from(document)
        issues = self._schema_issues(contract)
        self._complete_gaps(contract)
        self._detect_conflicts(contract, issues)
        open_gaps = [gap for gap in contract.gaps if gap.status == "OPEN"]
        open_conflicts = [row for row in contract.conflicts if row.status == "OPEN"]
        confirmed = [r for r in contract.requirements if r.status == SpecStatus.CONFIRMED.value]
        pending = [r for r in contract.requirements if r.status in (SpecStatus.DERIVED.value, SpecStatus.ASSUMED.value)]
        unknown = [r for r in contract.requirements if r.status == SpecStatus.UNKNOWN.value]
        if any(issue.severity == "ERROR" for issue in issues):
            status = "INCOMPLETE"
        elif open_conflicts or any(r.status == SpecStatus.CONFLICT.value for r in contract.requirements):
            status = "CONFLICT"
        elif not confirmed or pending or unknown or open_gaps:
            status = "INCOMPLETE"
        else:
            status = "VALIDATED"
        counts = {
            "requirements": len(contract.requirements),
            "confirmed": len(confirmed),
            "pending": len(pending),
            "unknown": len(unknown),
            "open_gaps": len(open_gaps),
            "open_conflicts": len(open_conflicts),
            "issues": len(issues),
        }
        return CompilationResult(contract, status, issues, counts, contract.content_hash(), contract.traceability())

    def clarify(
        self,
        document: SpecificationContract | dict[str, Any],
        *,
        field: str,
        value: Any,
        human_approved: bool = False,
        approved_by: str = "",
        approval_ref: str = "",
    ) -> SpecificationContract:
        """只有显式人工决定转 CONFIRMED；无批准时保留 ASSUMED，绝不假通过。"""
        contract = contract_from(document)
        if not field:
            raise SpecSchemaError("clarification 必须指定字段")
        if human_approved and (not approved_by.strip() or not approval_ref.strip()):
            raise SpecSchemaError("CONFIRMED 需要 approved_by 与 approval_ref")
        status = SpecStatus.CONFIRMED.value if human_approved else SpecStatus.ASSUMED.value
        matches = [r for r in contract.requirements if r.field == field]
        if human_approved:
            source_id = f"approval:{approval_ref}"
            if all(s.source_id != source_id for s in contract.sources):
                contract.sources.append(SpecSource(source_id, "human_approval", approval_ref, producer=approved_by))
            refs = [source_id]
        else:
            refs = []
        if matches:
            for requirement in matches:
                previous = requirement.value
                requirement.value = value
                requirement.status = status
                requirement.confirmed_by = approved_by if human_approved else ""
                if human_approved and source_id not in requirement.source_ids:
                    requirement.source_ids.append(source_id)
                requirement.rationale = f"由 {previous!r} 澄清为 {value!r}；status={status}"
        else:
            slug = field.lower().replace("_", "-")
            contract.requirements.append(
                SpecRequirement(
                    requirement_id=f"REQ-{slug}",
                    field=field,
                    value=value,
                    statement=f"澄清字段：{field}",
                    status=status,
                    source_ids=refs,
                    confirmed_by=approved_by if human_approved else "",
                )
            )
        for gap in contract.gaps:
            if gap.field == field and gap.status == "OPEN":
                gap.status = "RESOLVED" if human_approved else "ASSUMED"
        contract.version += 1
        contract.advance(LifecycleStage.CLARIFICATION, f"{field}: status={status}; approval={approval_ref or 'none'}")
        return contract

    def _schema_issues(self, contract: SpecificationContract) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not contract.document_id:
            issues.append(ValidationIssue("missing_document_id", "缺少 document_id"))
        source_ids = [s.source_id for s in contract.sources]
        if len(source_ids) != len(set(source_ids)):
            issues.append(ValidationIssue("duplicate_source_id", "source_id 必须唯一"))
        registered = set(source_ids)
        known_sources = {s.source_id: s for s in contract.sources}
        req_ids = [r.requirement_id for r in contract.requirements]
        if len(req_ids) != len(set(req_ids)):
            issues.append(ValidationIssue("duplicate_requirement_id", "requirement_id 必须唯一"))
        statuses = {status.value for status in SpecStatus}
        for req in contract.requirements:
            if not req.requirement_id or not req.field:
                issues.append(
                    ValidationIssue("missing_requirement_field", "需求缺少 id 或 field", field=req.requirement_id)
                )
            if req.status not in statuses:
                issues.append(ValidationIssue("invalid_status", f"未知状态：{req.status}", field=req.field))
            missing = [sid for sid in req.source_ids if sid not in registered]
            if missing:
                issues.append(
                    ValidationIssue("unknown_source", f"未登记来源：{missing}", field=req.field, refs=missing)
                )
            if req.status == SpecStatus.CONFIRMED.value:
                self._confirmed_issues(req, known_sources, issues)
        for source in contract.sources:
            if not source.source_id or not source.locator:
                issues.append(ValidationIssue("missing_source_locator", "来源必须有 source_id 与 locator"))
        for gap in contract.gaps:
            if not gap.field:
                issues.append(ValidationIssue("missing_gap_field", "Gap 缺少 field"))
        return issues

    def _confirmed_issues(
        self, req: SpecRequirement, sources: dict[str, SpecSource], issues: list[ValidationIssue]
    ) -> None:
        if not req.source_ids and not req.confirmed_by:
            issues.append(
                ValidationIssue("unconfirmed_requirement", "CONFIRMED 必须有正式来源或人工确认", field=req.field)
            )
        if req.confirmed_by and req.status != SpecStatus.CONFIRMED.value:
            issues.append(ValidationIssue("invalid_confirmation", "候选不能自称为 CONFIRMED", field=req.field))
        for sid in req.source_ids:
            source = sources.get(sid)
            if source and source.kind in ("agent", "generation", "experience") and not req.confirmed_by:
                issues.append(
                    ValidationIssue(
                        "candidate_not_approved", "生成/经验来源不能自动确认设计要求", field=req.field, refs=[sid]
                    )
                )

    def _complete_gaps(self, contract: SpecificationContract) -> None:
        for req in contract.requirements:
            if req.status == SpecStatus.UNKNOWN.value:
                self._add_gap(contract, req.field, "字段尚未确认")
        for name in self.required_fields:
            found = [
                r
                for r in contract.requirements
                if r.field == name and r.status == SpecStatus.CONFIRMED.value and r.value not in (None, "")
            ]
            if not found:
                self._add_gap(contract, name, "知识域要求缺少已确认的值")

    @staticmethod
    def _add_gap(contract: SpecificationContract, field: str, reason: str) -> None:
        if field and all(gap.field != field or gap.status != "OPEN" for gap in contract.gaps):
            contract.gaps.append(GapRecord(field, reason))

    @staticmethod
    def _detect_conflicts(contract: SpecificationContract, issues: list[ValidationIssue]) -> None:
        by_field: dict[str, list[SpecRequirement]] = {}
        for req in contract.requirements:
            if req.field and req.status != SpecStatus.UNKNOWN.value:
                by_field.setdefault(req.field, []).append(req)
        for name, requirements in by_field.items():
            confirmed = [r for r in requirements if r.status == SpecStatus.CONFIRMED.value]
            values = {json.dumps(r.value, sort_keys=True, default=str) for r in confirmed}
            if len(values) > 1 and not any(c.field == name and c.status == "OPEN" for c in contract.conflicts):
                hints = {r.requirement_id: r.value for r in confirmed}
                refs = sorted({sid for r in confirmed for sid in r.source_ids})
                contract.conflicts.append(
                    ConflictRecord(name, "不同正式来源对同一字段给出不同值", hints, source_ids=refs)
                )
            elif len(confirmed) == 1 and len(requirements) > 1:
                distinct = {json.dumps(r.value, sort_keys=True, default=str) for r in requirements}
                if len(distinct) > 1:
                    issues.append(
                        ValidationIssue(
                            "candidate_differs",
                            "候选值与正式来源不同，只作候选不覆盖正式值",
                            severity="ADVISORY",
                            field=name,
                        )
                    )


__all__ = ["CompilationResult", "SpecificationCompiler", "ValidationIssue"]
