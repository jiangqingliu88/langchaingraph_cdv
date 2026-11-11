"""十个验证角色 1.0 — 每个 handler 只做职责内的事。"""
from __future__ import annotations

import re
from typing import List

from ..contracts import TaskContract, TaskResult
from ..ir.models import (
    CoverageEvidence, EvidenceArtifact, ExecutionIR, Objective, Requirement,
    RunEvidence, Scenario, TestCase,
)
from ..runtime.context import AgentContext


def _lines(text: str) -> List[str]:
    rows = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^(?:[-*+]|\d+[.)])\s*", "", line)
        if len(line) >= 8:
            rows.append(line)
    return rows[:40]


def requirement_extraction(task: TaskContract, ctx: AgentContext) -> TaskResult:
    text = task.inputs.get("spec_text") or ctx.metadata.get("spec_text", "")
    if not text.strip():
        return TaskResult(task.id, task.agent, "blocked",
                          error="spec_text is empty")
    rows = _lines(text) or [text.strip()[:500]]
    for index, line in enumerate(rows, 1):
        req = Requirement(id=f"R{index:03d}", text=line, source="spec")
        ctx.ir.intent.requirements.append(req)
        ctx.ir.intent.objectives.append(Objective(
            id=f"O{index:03d}", requirement_id=req.id,
            target=ctx.target, description=line[:200]))
    return TaskResult(task.id, task.agent, "ok",
                      outputs={"requirements": len(ctx.ir.intent.requirements),
                               "objectives": len(ctx.ir.intent.objectives)})


def architecture_analysis(task: TaskContract, ctx: AgentContext) -> TaskResult:
    design = ctx.metadata.get("design") or {}
    top = str(design.get("top") or ctx.metadata.get("top") or "")
    if not top:
        return TaskResult(task.id, task.agent, "blocked",
                          error="design top/module is unknown")
    ctx.ir.design.top = top
    modules = design.get("modules") or []
    for row in modules:
        if isinstance(row, dict) and row.get("name"):
            from ..ir.models import Module, Port
            ctx.ir.design.modules.append(Module(
                name=str(row["name"]),
                ports=[Port(**p) for p in row.get("ports", [])
                       if isinstance(p, dict)]))
    return TaskResult(task.id, task.agent, "ok",
                      outputs={"top": top,
                               "modules": len(ctx.ir.design.modules)})


def planning(task: TaskContract, ctx: AgentContext) -> TaskResult:
    if not ctx.ir.intent.objectives:
        return TaskResult(task.id, task.agent, "blocked",
                          error="no objectives; run requirement first")
    for objective in ctx.ir.intent.objectives:
        ctx.ir.intent.scenarios.append(Scenario(
            id=f"S-{objective.id}", objective_id=objective.id,
            stimulus="directed + constrained-random",
            checker="scoreboard + assertion"))
    return TaskResult(task.id, task.agent, "ok",
                      outputs={"scenarios": len(ctx.ir.intent.scenarios)})


def uvm_generation(task: TaskContract, ctx: AgentContext) -> TaskResult:
    if not ctx.ir.intent.scenarios:
        return TaskResult(task.id, task.agent, "blocked",
                          error="no scenarios; run planning first")
    for index, scenario in enumerate(ctx.ir.intent.scenarios, 1):
        ctx.ir.execution.tests.append(TestCase(
            id=f"TC_{index:03d}", objective_ids=[scenario.objective_id],
            sequence=f"// sequence for {scenario.id}",
            scoreboard="scoreboard compares DUT vs model",
            constraints="// constraints from scenario"))
    return TaskResult(task.id, task.agent, "ok",
                      outputs={"tests": len(ctx.ir.execution.tests)})


def formal_generation(task: TaskContract, ctx: AgentContext) -> TaskResult:
    if not ctx.ir.intent.objectives:
        return TaskResult(task.id, task.agent, "blocked",
                          error="no objectives")
    for index, objective in enumerate(ctx.ir.intent.objectives, 1):
        ctx.ir.execution.tests.append(TestCase(
            id=f"SVA_{index:03d}", objective_ids=[objective.id],
            sva=f"assert property (@(posedge clk) ...); // {objective.id}"))
    return TaskResult(task.id, task.agent, "ok",
                      outputs={"sva": len(ctx.ir.execution.tests)})


def regression(task: TaskContract, ctx: AgentContext) -> TaskResult:
    results = ctx.engine.run(ctx.ir.execution)
    for index, result in enumerate(results, 1):
        ctx.ir.evidence.runs.append(RunEvidence(
            id=f"RUN_{index:03d}",
            test_id=ctx.ir.execution.tests[index - 1].id
            if index <= len(ctx.ir.execution.tests) else "unknown",
            status=result.status,
            error=result.error,
            log=",".join(result.evidence)))
    status = "ok" if all(r.status in ("passed", "failed", "blocked")
                         for r in ctx.ir.evidence.runs) else "failed"
    if any(r.status == "blocked" for r in ctx.ir.evidence.runs):
        status = "blocked"
    return TaskResult(task.id, task.agent, status,
                      outputs={"runs": len(ctx.ir.evidence.runs)},
                      error="EDA_MISSING" if status == "blocked" else "")


def debug(task: TaskContract, ctx: AgentContext) -> TaskResult:
    failed = [r for r in ctx.ir.evidence.runs
              if r.status not in ("passed", "waived")]
    if not failed:
        return TaskResult(task.id, task.agent, "ok",
                          outputs={"diagnosis": "no failures"})
    diagnosis = [{"test_id": r.test_id, "error": r.error or "unclassified"}
                 for r in failed]
    return TaskResult(task.id, task.agent, "ok",
                      outputs={"diagnosis": diagnosis,
                               "failed": len(failed)})


def coverage_analysis(task: TaskContract, ctx: AgentContext) -> TaskResult:
    values = ctx.engine.coverage()
    for objective in ctx.ir.intent.objectives:
        value = float(values.get(objective.id, 0.0))
        ctx.ir.evidence.coverage.append(CoverageEvidence(
            objective_id=objective.id, value=value,
            target=objective.target))
    gaps = [c.objective_id for c in ctx.ir.evidence.coverage
            if c.value < c.target]
    return TaskResult(task.id, task.agent, "ok",
                      outputs={"coverage": values, "gaps": gaps})


def repair(task: TaskContract, ctx: AgentContext) -> TaskResult:
    gaps = [c.objective_id for c in ctx.ir.evidence.coverage
            if c.value < c.target]
    existing = {t.id for t in ctx.ir.execution.tests}
    added = []
    for index, gid in enumerate(gaps, 1):
        test_id = f"TC_REPAIR_{index:03d}"
        if test_id in existing:
            continue
        ctx.ir.execution.tests.append(TestCase(
            id=test_id, objective_ids=[gid],
            sequence=f"// directed repair sequence for {gid}",
            scoreboard="scoreboard compares DUT vs model",
            constraints="// gap-targeted constraint"))
        added.append(test_id)
    return TaskResult(task.id, task.agent, "ok",
                      outputs={"actions": [
                          f"add directed scenario for {gid}" for gid in gaps],
                          "added_tests": added,
                          "gaps": gaps})


def signoff(task: TaskContract, ctx: AgentContext) -> TaskResult:
    return TaskResult(task.id, task.agent, "ok",
                      outputs={"summary": "ready for deterministic gate"})


HANDLERS = {
    "requirement_extraction": requirement_extraction,
    "architecture_analysis": architecture_analysis,
    "planning": planning,
    "uvm_generation": uvm_generation,
    "formal_generation": formal_generation,
    "regression": regression,
    "debug": debug,
    "coverage_analysis": coverage_analysis,
    "repair": repair,
    "signoff": signoff,
}
