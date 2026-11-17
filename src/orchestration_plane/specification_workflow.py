"""Specification Lifecycle 编排：协调既有九平面，而不是新增平面或 Agent。

外部可注入现有 analyst / synthesizer。默认流程不接受语言模型自称事实；
未决字段经 clarification 交给人工确认，最终由 Engine 给出 Readiness。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.engine_plane.specification_compiler import CompilationResult, SpecificationCompiler
from src.experience_plane.specification_decisions import ExperienceReferences
from src.mental_ir_plane.specification_compiler import (
    LifecycleStage,
    SpecificationContract,
    SpecSource,
    SpecStatus,
    contract_from,
)
from src.knowledge_plane.specification_rules import ProtocolKnowledge


class SpecificationWorkflow:
    def __init__(
        self,
        *,
        analyst: Any = None,
        synthesizer: Any = None,
        knowledge: ProtocolKnowledge | None = None,
        experience: ExperienceReferences | None = None,
    ) -> None:
        self.analyst = analyst
        self.synthesizer = synthesizer
        self.knowledge = knowledge or ProtocolKnowledge()
        self.experience = experience or ExperienceReferences()
        self._versions: dict[str, tuple[str, str]] = {}

    def run(
        self,
        document: SpecificationContract | dict[str, Any],
        *,
        analysis: dict[str, Any] | None = None,
        decisions: list[dict[str, Any]] | None = None,
        required_fields: tuple[str, ...] | None = None,
    ) -> CompilationResult:
        if len(decisions or []) > 3:
            raise ValueError("单次澄清最多 3 轮，剩余缺口必须回到编排/人工流程")
        contract = self._extract(contract_from(deepcopy(document)), analysis)
        required = self.knowledge.required_for(contract.domain) if required_fields is None else tuple(required_fields)
        contract.metadata["knowledge_reference"] = self.knowledge.cite(contract.domain)
        contract.metadata["experience_references"] = self.experience.recall(contract.domain)
        compiler = SpecificationCompiler(required)
        preliminary = compiler.compile(contract)
        contract.advance(LifecycleStage.GAP_ANALYSIS, f"{preliminary.counts['open_gaps']} 个开放缺口")
        pending = [gap for gap in contract.gaps if gap.status == "OPEN"]
        contract.advance(
            LifecycleStage.CLARIFICATION,
            f"{len(pending)} 项需要人工或补充分析",
            status="PENDING" if pending else "VISITED",
        )
        contract = self._clarify(contract, compiler, decisions or [])
        contract.advance(LifecycleStage.SYNTHESIS, "只生成候选，不自动批准")
        self._synthesize(contract)
        contract.advance(LifecycleStage.IR_COMPILATION, "schema=specification_contract_v1")
        preliminary = compiler.compile(contract)
        contract.advance(LifecycleStage.VALIDATION, preliminary.status)
        old = self._versions.get(contract.document_id)
        contract.metadata["evolution"] = {
            "previous_hash": old[0] if old else "",
            "previous_status": old[1] if old else "",
            "supersedes_previous": bool(old and old[0] != preliminary.spec_hash),
            "scope": "当前编排器内演进；跨 Run Evidence 失效传播另由 M2 实现",
        }
        contract.advance(LifecycleStage.EVOLUTION, f"previous={old[0] if old else 'new-document'}")
        # Lifecycle 参与哈希；最后统一计算，避免 report 与 contract 不同版本。
        result = compiler.compile(contract)
        self._versions[contract.document_id] = (result.spec_hash, result.status)
        return result

    def _extract(self, contract: SpecificationContract, analysis: dict[str, Any] | None) -> SpecificationContract:
        contract.advance(LifecycleStage.INGESTION, f"{len(contract.sources)} 个已登记来源")
        contract.advance(LifecycleStage.EXTRACTION, "复用结构化输入；未默认调用 LLM")
        if analysis is None and self.analyst is not None:
            analysis = self.analyst.analyze(contract.to_dict())
        if analysis is not None:
            contract = self._merge_analysis(contract, analysis)
        contract.advance(LifecycleStage.RECONCILIATION, f"{len(contract.requirements)} 条需求/候选")
        return contract

    @staticmethod
    def _clarify(
        contract: SpecificationContract, compiler: SpecificationCompiler, decisions: list[dict[str, Any]]
    ) -> SpecificationContract:
        for decision in decisions:
            contract = compiler.clarify(
                contract,
                field=str(decision.get("field") or ""),
                value=decision.get("value"),
                human_approved=bool(decision.get("human_approved", False)),
                approved_by=str(decision.get("approved_by") or ""),
                approval_ref=str(decision.get("approval_ref") or ""),
            )
        return contract

    def _synthesize(self, contract: SpecificationContract) -> None:
        if self.synthesizer is None:
            return
        candidates, source = self.synthesizer.synthesize(contract.to_dict())
        if source:
            contract.sources.append(SpecSource(**source))
        for candidate in candidates:
            if not any(old.requirement_id == candidate.requirement_id for old in contract.requirements):
                contract.requirements.append(candidate)

    @staticmethod
    def _merge_analysis(contract: SpecificationContract, analysis: dict[str, Any]) -> SpecificationContract:
        data = contract.to_dict()
        for row in analysis.get("requirements") or []:
            candidate = dict(row)
            candidate["status"] = SpecStatus.DERIVED.value
            data["requirements"].append(candidate)
        data["gaps"].extend(deepcopy(analysis.get("gaps") or []))
        data["conflicts"].extend(deepcopy(analysis.get("conflicts") or []))
        merged = SpecificationContract.from_dict(data)
        merged.advance(LifecycleStage.EXTRACTION, "Agent 分析已合入，状态均为 DERIVED")
        return merged

    @staticmethod
    def next_clarifications(result: CompilationResult) -> list[dict[str, str]]:
        return [
            {
                "field": gap.field,
                "question": f"请确认字段 {gap.field}",
                "reason": gap.reason,
                "requires_human_decision": "true",
            }
            for gap in result.contract.gaps
            if gap.status == "OPEN"
        ]


__all__ = ["SpecificationWorkflow"]
