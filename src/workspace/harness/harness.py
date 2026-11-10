"""Harness 驱动 —— 状态机、决策、回填、压缩、goal rounds、暂停/恢复。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..staging.tools import SandboxTools
from ..zones import WorkspaceError, WorkspaceZones
from . import goal as goal_mod
from .backfill import record_assistant, record_result
from .context import Compactor, estimate_messages, estimate_tokens, prompt_messages
from .events import EventLog, EventSink
from .jobs import JobManager
from .permissions import PermissionPolicy
from .plan import extract_plan, plan_required_message
from .session import Session, new_session_id
from .skills import SkillLibrary
from .state import HarnessState, StateMachine
from .tools import TOOL_BY_NAME, TOOL_NAMES, tool_specs_prompt

DECISION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["tool"],
    "additionalProperties": False,
    "properties": {
        "thought": {"type": "string"},
        "plan": {"type": "string"},
        "subgoals": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "title"],
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "success": {"type": "string"},
                },
            },
        },
        "subgoal_id": {"type": "string"},
        "tool": {"enum": list(TOOL_NAMES)},
        "args": {"type": "object"},
    },
}

SYSTEM_PROMPT = """You are a verification sandbox agent.

Zones: main/ is READ-ONLY signed-off content; staging/ is your writable sandbox;
proposals/ and gate/ are managed by the deterministic gate, not by you.

Rules:
  1. Read main/ for context; every write/delete goes under staging/.
  2. Commands run with cwd=staging/; record real commands, never invent evidence.
  3. First response may include `subgoals: [{id,title,success}]` to decompose a
     complex objective. Work one subgoal per round: reason → act → observe.
     Mark it done with `complete_subgoal(summary, evidence)` only when you have
     tool-backed evidence; if blocked, `block_subgoal(reason)` (it becomes an
     open question for the human gate).
  4. After all subgoals, call `propose` with before/after/reasoning_trace and
     open_questions (list every uncertainty). Use `finish` to stop without a proposal.
  5. First response must include a `plan` (one short paragraph) when plan mode is on.
  6. Long outputs are pruned from context; full logs stay in staging/.

Tools:
"""
SYSTEM_PROMPT += tool_specs_prompt()


class _RetryRound(Exception):
    """提案不合法 → 结束当前轮，交给 `_loop` 开下一轮。"""


_PLAN_RETRY = object()


@dataclass
class HarnessConfig:
    max_steps: int = 12
    max_rounds: int = 2
    max_steps_per_subgoal: int = 6
    max_attempts_per_subgoal: int = 2
    max_tool_errors: int = 3
    max_tokens: int = 200_000
    decompose: bool = True
    max_subgoals: int = 6
    goal: str = ""
    coverage_target: float = 0.0
    project: str = ""
    project_root: str = ""
    evidence: str = ""
    allow_unreviewed: bool = True
    auto_export: bool = False
    export_out: str = ""
    plan_first: bool = False
    require_plan_approval: bool = False
    require_exec_approval: bool = False
    allow_subagent: bool = True
    emit_proposal: bool = True
    compaction: bool = True
    event_sink: Optional[EventSink] = None


class Harness:
    def __init__(self, zones: WorkspaceZones, *, config: Optional[HarnessConfig] = None,
                 planner: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 tools: Optional[SandboxTools] = None,
                 session_id: Optional[str] = None):
        self.zones = zones.ensure()
        self.config = config or HarnessConfig()
        self.planner = planner
        self.sandbox = tools or SandboxTools(self.zones)
        from ..resources import ProjectResources
        self.resources = ProjectResources(
            self.config.project_root or self.zones.project_root())
        self.skills = SkillLibrary(self.zones)
        self.jobs = JobManager(self.zones)
        self.policy = PermissionPolicy(require_exec=self.config.require_exec_approval)
        self.compactor = Compactor(self.config.max_tokens)
        self._cancelled = False
        self._llm_unavailable = False
        self._tool_errors = 0

        if session_id:
            self.session = Session.load(self.zones, session_id)
            state = HarnessState(self.session.state)
        else:
            self.session = Session(session_id=new_session_id(), task="")
            state = HarnessState.NEW
        self.events = EventLog(self.zones, self.session.session_id,
                               self.config.event_sink)
        self.machine = StateMachine(state, on_transition=self._on_transition)

    # ── 状态 ──────────────────────────────────────────────────────────────

    def _on_transition(self, previous: HarnessState, target: HarnessState,
                       reason: str) -> None:
        self.session.state = target.value
        self.events.emit("state", **{"from": previous.value, "to": target.value,
                                     "reason": reason,
                                     "round": self.session.round,
                                     "step": self.session.step})
        self.session.save(self.zones)

    def _transition(self, target: HarnessState, reason: str = "") -> None:
        self.machine.transition(target, reason)

    # ── 主入口 ────────────────────────────────────────────────────────────

    def run(self, task: str, *, max_steps: Optional[int] = None) -> Dict[str, Any]:
        task = str(task or "").strip()
        if not task:
            return {"status": "invalid", "error": "task 为空"}
        if not self.session.task:
            self.session.task = task
            self.session.goal = goal_mod.new_goal(task, self.config.max_rounds)
            self.session.save(self.zones)
        elif task and task != self.session.task and self.machine.state == HarnessState.NEW:
            self.session.task = task
            self.session.goal = goal_mod.new_goal(task, self.config.max_rounds)
        if self.machine.state == HarnessState.NEW:
            self._transition(HarnessState.PLANNING, "run")
        elif self.machine.state in (HarnessState.AWAITING_PLAN, HarnessState.PAUSED):
            return self._paused_result()
        elif self.machine.terminal:
            return self._terminal_result()
        return self._loop(max_steps)

    # ── 循环 ──────────────────────────────────────────────────────────────

    def _loop(self, max_steps: Optional[int]) -> Dict[str, Any]:
        self._ensure_subgoals()
        while True:
            subgoal = self._next_subgoal()
            if subgoal is None:
                return self._finalize()
            try:
                outcome = self._run_subgoal(subgoal, max_steps)
            except _RetryRound:
                continue
            if outcome is not None:
                return outcome

    def _run_subgoal(self, subgoal: Dict[str, Any],
                     max_steps: Optional[int]) -> Optional[Dict[str, Any]]:
        per = int(self.config.max_steps_per_subgoal or max_steps
                  or self.config.max_steps)
        limit = self.session.step + max(1, per)
        round_row = goal_mod.current_round(self.session.goal)
        if round_row is None or round_row.get("state") != "running":
            round_row = self._start_round_for(subgoal)
        if self.machine.state != HarnessState.PLANNING:
            self._transition(HarnessState.PLANNING, "next step")
        outcome = self._steps_until(limit, round_row)
        if outcome is None:
            active = self._active_subgoal_obj() or subgoal
            self._close_subgoal(active, "blocked", "max steps for subgoal")
            return None
        if isinstance(outcome, dict) and outcome.get("__subgoal__"):
            return None
        return outcome

    def _steps_until(self, limit: int, round_row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        while self.session.step < limit:
            self.session.step += 1
            round_row["steps"] = self.session.step
            early = self._pre_step()
            if early is not None:
                return early
            decision = self._decide()
            if decision is None:
                outcome = self._decide_failed()
                if outcome is not None:
                    return outcome
                continue
            outcome = self._step(decision)
            if outcome is not None:
                return outcome
        return None

    # ── 子目标（ReAct） ──────────────────────────────────────────────────

    def _ensure_subgoals(self) -> None:
        if self.session.subgoals:
            return
        if self.config.goal == "coverage" and self.config.evidence:
            from .domain import collect_evidence, decompose_coverage
            evidence = collect_evidence(self.config.evidence,
                                        target=self.config.coverage_target)
            self.session.working.setdefault("eda", {}).update({
                "before": evidence, "after": evidence,
                "target": self.config.coverage_target,
                "run_dir": evidence.get("run_dir", "")})
            provided = decompose_coverage(
                evidence, self.config.coverage_target,
                max_subgoals=self.config.max_subgoals)
            if provided:
                self.session.subgoals = self._normalize_subgoals(provided)
                self._implicit_subgoal = False
                self.events.emit("subgoal.decompose",
                                 source="eda_evidence",
                                 subgoals=[row["title"] for row in self.session.subgoals])
                self.session.save(self.zones)
                return
        self.session.subgoals = [{
            "id": "G1", "title": self.session.task,
            "success": "task complete with evidence", "status": "pending",
            "attempts": 0, "max_attempts": self.config.max_attempts_per_subgoal,
            "steps": 0, "summary": "", "notes": [],
            "commands": [], "logs": [],
        }]
        self._implicit_subgoal = True

    def _normalize_subgoals(self, provided: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        subgoals = []
        for index, item in enumerate(provided, 1):
            if not isinstance(item, dict):
                continue
            subgoals.append({
                "id": str(item.get("id") or f"G{index}"),
                "title": str(item.get("title") or f"subgoal {index}"),
                "success": str(item.get("success") or ""),
                "status": "pending", "attempts": 0,
                "max_attempts": self.config.max_attempts_per_subgoal,
                "steps": 0, "summary": "", "notes": [],
                "commands": [], "logs": [],
            })
        return subgoals

    def _next_subgoal(self) -> Optional[Dict[str, Any]]:
        if not self.session.subgoals:
            self._ensure_subgoals()
        active = self._active_subgoal_obj()
        if active is not None:
            return active
        for subgoal in self.session.subgoals:
            if subgoal.get("status") != "pending":
                continue
            subgoal["status"] = "active"
            subgoal["attempts"] = int(subgoal.get("attempts") or 0) + 1
            self.session.active_subgoal = str(subgoal["id"])
            self._start_round_for(subgoal)
            self.events.emit("subgoal.start", subgoal_id=subgoal["id"],
                             title=subgoal.get("title", ""),
                             round=self.session.round)
            self.session.save(self.zones)
            return subgoal
        return None

    def _active_subgoal_obj(self) -> Optional[Dict[str, Any]]:
        sid = self.session.active_subgoal
        if not sid:
            return None
        for subgoal in self.session.subgoals:
            if subgoal.get("id") == sid and subgoal.get("status") == "active":
                return subgoal
        return None

    def _start_round_for(self, subgoal: Dict[str, Any]) -> Dict[str, Any]:
        row = goal_mod.start_round(self.session.goal, str(subgoal.get("title") or ""))
        self.session.round = int(row["index"])
        return row

    def _maybe_decompose(self, decision: Dict[str, Any]) -> None:
        provided = decision.get("subgoals")
        if not self.config.decompose or not isinstance(provided, list) or not provided:
            return
        if not getattr(self, "_implicit_subgoal", False):
            self.session.append("system", "[harness] 目标已分解；忽略后续 subgoals 字段")
            return
        subgoals = self._normalize_subgoals(provided)
        if not subgoals:
            return
        self.session.subgoals = subgoals
        self._implicit_subgoal = False
        self.session.active_subgoal = ""
        goal_mod.finish_round(self.session.goal, "decomposed", "")
        row = self._start_round_for(subgoals[0])
        subgoals[0]["status"] = "active"
        subgoals[0]["attempts"] = 1
        self.session.active_subgoal = str(subgoals[0]["id"])
        self.session.round = int(row["index"])
        self.events.emit("subgoal.decompose",
                         subgoals=[row.get("title") for row in subgoals])
        self.session.save(self.zones)

    def _close_subgoal(self, subgoal: Dict[str, Any], state: str,
                       summary: str, *, finish_round: bool = True) -> None:
        subgoal["status"] = state
        subgoal["summary"] = str(summary)
        evidence = self.session.working.get("evidence") or {}
        subgoal["commands"] = list(evidence.get("commands") or [])
        subgoal["logs"] = list(evidence.get("logs") or [])
        if state == "blocked" and summary:
            questions = self.session.working.setdefault("open_questions", [])
            questions.append(summary)
        if finish_round:
            goal_mod.finish_round(self.session.goal, state, str(summary))
        if self.session.active_subgoal == str(subgoal.get("id")):
            self.session.active_subgoal = ""
        self.events.emit("subgoal.finish", subgoal_id=subgoal["id"],
                         status=state, summary=str(summary)[:500],
                         round=self.session.round)
        self.session.save(self.zones)

    def _finalize(self) -> Dict[str, Any]:
        if self.machine.state != HarnessState.PLANNING:
            self._transition(HarnessState.PLANNING, "finalize")
        self.session.append("system",
                            "[harness] 所有子目标已结束；现在调用 propose 汇总证据与疑点")
        for _ in range(2):
            self.session.step += 1
            decision = self._decide()
            if decision is None:
                break
            tool = str(decision.get("tool") or "")
            call_id = f"final-{self.session.step}"
            if tool == "propose":
                record_assistant(self.session, decision, call_id)
                return self._finish_proposal(dict(decision.get("args") or {}), call_id)
            if tool == "finish":
                record_assistant(self.session, decision, call_id)
                return self._finish_without_proposal(dict(decision.get("args") or {}), call_id)
            self.session.append("system", "[harness] 请调用 propose 或 finish")
        return self._auto_proposal()

    def _auto_proposal(self) -> Dict[str, Any]:
        done = [s for s in self.session.subgoals if s.get("status") == "done"]
        blocked = [s for s in self.session.subgoals if s.get("status") == "blocked"]
        summary = "; ".join(f"{s['id']}:{s.get('summary', '')}" for s in done) or "无"
        questions = [str(s.get("summary") or s.get("title")) for s in blocked]
        args = {"before": "baseline", "after": f"{len(done)} done / {len(blocked)} blocked",
                "reasoning_trace": f"auto proposal: {summary}",
                "open_questions": questions}
        return self._finish_proposal(args, "auto-final", record=False)

    def _pre_step(self) -> Optional[Dict[str, Any]]:
        if self._cancelled:
            return self._cancel_result("cancelled by caller")
        usage = sum(int(v) for v in (self.session.usage or {}).values()
                    if isinstance(v, int))
        if usage > self.config.max_tokens:
            return self._block("BUDGET_EXHAUSTED", f"token 估算 {usage} > {self.config.max_tokens}")
        return None

    def _decide_failed(self) -> Optional[Dict[str, Any]]:
        self._tool_errors += 1
        if self._llm_unavailable:
            return self._block("LLM_UNAVAILABLE", self.session.last_error)
        if self._tool_errors >= self.config.max_tool_errors:
            return self._block("DECISION_ERRORS", self.session.last_error)
        self.session.append("system", f"[harness] invalid decision: {self.session.last_error}")
        self.session.save(self.zones)
        return None

    # ── 单步 ──────────────────────────────────────────────────────────────

    def _step(self, decision: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self._maybe_decompose(decision)
        tool = str(decision.get("tool") or "")
        args = dict(decision.get("args") or {})
        planned = self._maybe_plan(decision)
        if planned is _PLAN_RETRY:
            return None
        if planned is not None:
            return planned
        call_id = f"call-{self.session.round}-{self.session.step}"
        if tool == "complete_subgoal":
            return self._complete_subgoal(decision, args, call_id)
        if tool == "block_subgoal":
            return self._block_subgoal(decision, args, call_id)
        if tool == "propose":
            record_assistant(self.session, decision, call_id)
            return self._finish_proposal(args, call_id)
        if tool == "finish":
            record_assistant(self.session, decision, call_id)
            return self._finish_without_proposal(args, call_id)
        if tool == "ask_user":
            return self._ask_user(decision, call_id)
        return self._run_tool(decision, tool, args, call_id)

    def _complete_subgoal(self, decision: Dict[str, Any], args: Dict[str, Any],
                          call_id: str) -> Optional[Dict[str, Any]]:
        subgoal = self._active_subgoal_obj()
        if subgoal is None:
            self.session.append("system", "[harness] 没有 active subgoal 可完成")
            return None
        summary = str(args.get("summary") or args.get("evidence") or "").strip()
        if not summary:
            self.session.append("system",
                                "[harness] complete_subgoal 需要 summary（工具证据说明）")
            return None
        record_assistant(self.session, decision, call_id)
        self._close_subgoal(subgoal, "done", summary)
        record_result(self.session, call_id, "complete_subgoal",
                      {"ok": True, "subgoal_id": subgoal["id"]}, self.zones, args)
        return {"__subgoal__": "done", "subgoal_id": subgoal["id"]}

    def _block_subgoal(self, decision: Dict[str, Any], args: Dict[str, Any],
                       call_id: str) -> Optional[Dict[str, Any]]:
        subgoal = self._active_subgoal_obj()
        if subgoal is None:
            self.session.append("system", "[harness] 没有 active subgoal 可阻塞")
            return None
        reason = str(args.get("reason") or "blocked").strip()
        record_assistant(self.session, decision, call_id)
        self._close_subgoal(subgoal, "blocked", reason)
        record_result(self.session, call_id, "block_subgoal",
                      {"ok": True, "subgoal_id": subgoal["id"], "reason": reason},
                      self.zones, args)
        return {"__subgoal__": "blocked", "subgoal_id": subgoal["id"]}

    def _maybe_plan(self, decision: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.config.plan_first or self.session.plan:
            return None
        plan = extract_plan(decision)
        if not plan:
            self.session.last_error = plan_required_message()
            self.session.append("system", f"[harness] {self.session.last_error}")
            self.session.save(self.zones)
            return _PLAN_RETRY
        self.session.plan = plan
        self.session.plan_approved = not self.config.require_plan_approval
        self.session.append("assistant", f"PLAN: {plan}")
        self.events.emit("plan", plan=plan, round=self.session.round)
        if not self.config.require_plan_approval:
            self.session.save(self.zones)
            return None
        self.session.pending = {"kind": "plan", "plan": plan}
        self._transition(HarnessState.AWAITING_PLAN, "plan approval")
        return self._paused_result()

    def _run_tool(self, decision: Dict[str, Any], tool: str, args: Dict[str, Any],
                  call_id: str) -> Optional[Dict[str, Any]]:
        spec = TOOL_BY_NAME.get(tool)
        if spec is None:
            self.session.last_error = f"未知工具：{tool}"
            return None
        record_assistant(self.session, decision, call_id)
        permission = self.policy.decide(tool, spec.risk,
                                        requires_approval=spec.requires_approval)
        if permission.action == "deny":
            record_result(self.session, call_id, tool,
                          {"ok": False, "error": permission.reason},
                          self.zones, args)
            return None
        if permission.action == "ask":
            self.session.pending = {"kind": "approval", "tool": tool,
                                    "args": args, "call_id": call_id,
                                    "reason": permission.reason}
            self._transition(HarnessState.PAUSED, "tool approval")
            return self._paused_result()
        return self._execute_and_backfill(tool, args, call_id)

    def _execute_and_backfill(self, tool: str, args: Dict[str, Any],
                              call_id: str) -> Optional[Dict[str, Any]]:
        self._transition(HarnessState.ACTING, tool)
        self.events.emit("tool.call", tool=tool, args=args,
                         round=self.session.round, step=self.session.step)
        self.events.emit("react.act", tool=tool, args=args,
                         subgoal_id=self.session.active_subgoal)
        result = self._execute_tool(tool, args)
        self._transition(HarnessState.OBSERVING, tool)
        self.events.emit("tool.result", tool=tool, ok=bool(result.get("ok")),
                         error=str(result.get("error") or "")[:300],
                         round=self.session.round, step=self.session.step)
        self.events.emit("react.observe", tool=tool, ok=bool(result.get("ok")),
                         error=str(result.get("error") or "")[:300],
                         subgoal_id=self.session.active_subgoal)
        record_result(self.session, call_id, tool, result, self.zones, args)
        self._account_usage(args, result)
        if self.config.compaction and self.compactor.maybe_compact(self.session):
            self.events.emit("compaction", compactions=self.session.compactions)
        if not result.get("ok"):
            self._tool_errors += 1
            if self._tool_errors >= self.config.max_tool_errors:
                return self._block("TOOL_ERRORS", str(result.get("error") or "tool failed"))
        else:
            self._tool_errors = 0
        self._transition(HarnessState.PLANNING, "observe")
        return None

    # ── 出口 ──────────────────────────────────────────────────────────────

    def _finish_proposal(self, args: Dict[str, Any], call_id: str, *,
                         record: bool = True) -> Optional[Dict[str, Any]]:
        active = self._active_subgoal_obj()
        pending = [s for s in self.session.subgoals
                   if s.get("status") == "pending"]
        questions = list(args.get("open_questions") or [])
        if not isinstance(questions, list):
            questions = [str(questions)]
        questions.extend(self.session.working.get("open_questions") or [])
        questions.extend(f"subgoal not attempted: {s.get('title')}" for s in pending)
        questions = list(dict.fromkeys(str(q) for q in questions if str(q).strip()))
        evidence = self._proposal_evidence(args)
        try:
            from ..proposal.schema import ProposalError, new_proposal
            proposal = new_proposal(self.session.task, self.zones,
                                    evidence=evidence, open_questions=questions)
        except ProposalError as exc:
            return self._invalid_proposal(exc, call_id)
        # 只有提案合法后才关闭子目标；否则 retry 还能看到 active。
        if active is not None:
            self._close_subgoal(active, "done",
                                str(args.get("reasoning_trace") or "proposal"))
        for subgoal in pending:
            self._close_subgoal(subgoal, "blocked", "not attempted",
                                finish_round=False)
        proposal.evidence = {**evidence, "subgoals": self._subgoal_snapshot()}
        proposal.open_questions = questions
        if self.config.emit_proposal:
            proposal.save(self.zones)
            self.session.proposal_id = proposal.proposal_id
        if record:
            record_result(self.session, call_id, "propose",
                          {"ok": True, "proposal_id": proposal.proposal_id},
                          self.zones, args)
        self._transition(HarnessState.PROPOSING, "proposal")
        self._transition(HarnessState.DONE, "proposal")
        complete = all(s.get("status") == "done" for s in self.session.subgoals)
        goal_mod.finish_goal(self.session.goal,
                             "completed" if complete else "partial",
                             proposal.proposal_id)
        self.session.pending = {}
        self.session.save(self.zones)
        self.events.emit("proposal", proposal_id=proposal.proposal_id,
                         saved=self.config.emit_proposal)
        return {"status": "proposal", "proposal_id": proposal.proposal_id,
                "path": (str(self.zones.proposal_path(proposal.proposal_id))
                         if self.config.emit_proposal else ""),
                "proposal": proposal.to_dict(), "session": self.session.projection()}

    def _proposal_evidence(self, args: Dict[str, Any]) -> Dict[str, Any]:
        working_evidence = self.session.working.get("evidence") or {}
        return {
            "before": str(args.get("before") or ""),
            "after": str(args.get("after") or ""),
            "commands": list(working_evidence.get("commands") or []),
            "logs": list(working_evidence.get("logs") or []),
            "reasoning_trace": str(args.get("reasoning_trace") or ""),
            "subgoals": self._subgoal_snapshot(),
            "eda": self.session.working.get("eda") or {},
            "exports": list(self.session.working.get("exports") or []),
            "target": self.config.coverage_target,
            "goal": self.config.goal,
        }

    def _subgoal_snapshot(self) -> List[Dict[str, Any]]:
        return [{key: sub.get(key) for key in
                 ("id", "title", "status", "summary", "commands", "logs")}
                for sub in self.session.subgoals]

    def _invalid_proposal(self, exc: Exception, call_id: str) -> Optional[Dict[str, Any]]:
        message = str(exc)
        record_result(self.session, call_id, "propose", {"ok": False, "error": message},
                      self.zones)
        self.session.last_error = message
        subgoal = self._active_subgoal_obj()
        if subgoal is not None and (int(subgoal.get("attempts") or 0)
                                    < int(subgoal.get("max_attempts") or 1)):
            subgoal["attempts"] = int(subgoal.get("attempts") or 0) + 1
            subgoal["status"] = "active"
            self.session.active_subgoal = str(subgoal["id"])
            goal_mod.finish_round(self.session.goal, "invalid", message)
            self._start_round_for(subgoal)
            self.session.append("system",
                                f"[harness] proposal 不合法，重试当前子目标：{message}")
            self.session.save(self.zones)
            raise _RetryRound(message)
        if subgoal is not None:
            self._close_subgoal(subgoal, "blocked", message)
        if any(s.get("status") == "pending" for s in self.session.subgoals):
            self.session.save(self.zones)
            return None
        return self._block("PROPOSAL_INVALID", message, status="proposal_invalid")

    def _finish_without_proposal(self, args: Dict[str, Any],
                                 call_id: str) -> Dict[str, Any]:
        reason = str(args.get("reason") or "finished without proposal")
        record_result(self.session, call_id, "finish", {"ok": True, "reason": reason},
                      self.zones, args)
        active = self._active_subgoal_obj()
        if active is not None:
            self._close_subgoal(active, "blocked", reason)
        for subgoal in self.session.subgoals:
            if subgoal.get("status") == "pending":
                self._close_subgoal(subgoal, "blocked", "not attempted",
                                    finish_round=False)
        self._transition(HarnessState.DONE, "finish")
        goal_mod.finish_goal(self.session.goal, "finished_no_proposal", reason)
        self.session.save(self.zones)
        return {"status": "finished_no_proposal", "reason": reason,
                "session": self.session.projection()}

    def _ask_user(self, decision: Dict[str, Any], call_id: str) -> Optional[Dict[str, Any]]:
        record_assistant(self.session, decision, call_id)
        question = str((decision.get("args") or {}).get("question") or "")
        options = (decision.get("args") or {}).get("options") or []
        self.session.pending = {"kind": "answer", "question": question,
                                "options": options, "call_id": call_id}
        self._transition(HarnessState.PAUSED, "ask_user")
        return self._paused_result()

    # ── 工具执行 ──────────────────────────────────────────────────────────

    def _execute_tool(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool in ("str_replace",):
            return self._str_replace(args)
        if tool == "read_skill":
            return self._read_skill(args)
        if tool == "job_start":
            return self._job("start", args)
        if tool in ("job_output", "job_kill"):
            return self._job(tool.split("_", 1)[1], args)
        if tool == "run_verify":
            return self._run_verify(args)
        if tool == "collect_evidence":
            return self._collect_evidence(args)
        if tool == "compare_evidence":
            return self._compare_evidence(args)
        if tool == "export_evidence":
            return self._export_evidence(args)
        if tool in ("project_map", "read_project_file", "search_project"):
            return self._project_tool(tool, args)
        if tool == "todo_write":
            todos = args.get("todos")
            return {"ok": True, "result": {"todos": todos if isinstance(todos, list) else []}}
        if tool == "spawn_subagent":
            from .subagent import run_subagent
            return run_subagent(self, str(args.get("task") or ""),
                                max_steps=int(args.get("max_steps") or 6))
        return self.sandbox.call(tool, args)

    def _project_tool(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """只读项目视图：RTL/验证/覆盖率/环境/spec/模型，写出口仍是 staging。"""
        try:
            if tool == "project_map":
                return {"ok": True, "result": self.resources.inventory(
                    str(args.get("kind") or ""), int(args.get("limit") or 200))}
            if tool == "read_project_file":
                return {"ok": True,
                        "result": self.resources.read(str(args.get("path") or ""))}
            return {"ok": True, "result": self.resources.search(
                str(args.get("pattern") or ""), str(args.get("kind") or ""),
                str(args.get("glob") or "*"))}
        except (OSError, ValueError, re.error) as exc:
            return {"ok": False, "error": str(exc)}

    def _str_replace(self, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            path = self.zones.staging_path(args.get("path") or "", must_exist=True)
            old = str(args.get("old") or "")
            new = str(args.get("new") or "")
            if not old:
                return {"ok": False, "error": "old 不能为空"}
            text = path.read_text(encoding="utf-8")
            if old not in text:
                return {"ok": False, "error": f"old 文本未找到：{args.get('path')}"}
            self.zones.write_staging(args["path"], text.replace(old, new, 1))
            return {"ok": True, "result": {"path": args["path"],
                                           "replaced": text.count(old)}}
        except (WorkspaceError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    def _read_skill(self, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return {"ok": True, "result": self.skills.read(str(args.get("name") or ""))}
        except KeyError as exc:
            return {"ok": False, "error": str(exc)}

    def _run_verify(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from .domain import run_verify
        try:
            project = str(args.get("project") or self.config.project
                          or self.zones.staging)
            run_dir = self._evidence_run_dir(args.get("run_dir"))
            result = run_verify(
                project, run_dir,
                target=float(args.get("target") or self.config.coverage_target),
                timeout=int(args.get("timeout") or 1800),
                allow_unreviewed=self.config.allow_unreviewed)
            if self.config.auto_export:
                result["export"] = self._export(run_dir, self.config.export_out)
            return {"ok": True, "result": result}
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def _collect_evidence(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from .domain import collect_evidence
        try:
            run_dir = self._evidence_run_dir(args.get("run_dir"))
            return {"ok": True, "result": collect_evidence(
                run_dir, target=float(args.get("target") or self.config.coverage_target))}
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def _compare_evidence(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from .domain import compare_evidence
        try:
            return {"ok": True, "result": compare_evidence(
                args.get("before"), args.get("after"))}
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def _export_evidence(self, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            run_dir = self._evidence_run_dir(args.get("run_dir"))
            return {"ok": True, "result": self._export(run_dir, args.get("out"))}
        except (OSError, ValueError, WorkspaceError) as exc:
            return {"ok": False, "error": str(exc)}

    def _export(self, run_dir: Path, out: Any = None) -> Dict[str, Any]:
        """导出证据包；out 只能落 staging（run 目录默认已经在 staging 内）。"""
        from .domain import export_evidence
        try:
            out_path = self.zones.staging_path(str(out)) if out else None
            return export_evidence(run_dir, out_path)
        except (OSError, ValueError, WorkspaceError) as exc:
            return {"ok": False, "run_dir": str(run_dir), "error": str(exc)}

    def _evidence_run_dir(self, value: Any) -> Path:
        if value:
            text = str(value).strip().replace("\\", "/")
            path = Path(text) if Path(text).is_absolute() else self.zones.staging_path(text)
            path = path.resolve()
            path.relative_to(self.zones.staging.resolve())
            return path
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return self.zones.staging_path(f".evidence/runs/run-{stamp}")

    def _job(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if action == "start":
                return {"ok": True, "result": self.jobs.start(
                    args.get("command"), str(args.get("name") or ""))}
            if action == "output":
                return {"ok": True, "result": self.jobs.output(
                    str(args.get("job_id") or ""), int(args.get("tail") or 4000))}
            if action == "kill":
                return {"ok": True, "result": self.jobs.kill(str(args.get("job_id") or ""))}
            return {"ok": False, "error": f"未知 job 动作：{action}"}
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    # ── 决策 ──────────────────────────────────────────────────────────────

    def _decide(self) -> Optional[Dict[str, Any]]:
        messages = prompt_messages(self.session, SYSTEM_PROMPT,
                                   skills_section=self.skills.prompt_section())
        raw = self._ask_llm(messages)
        if raw is None:
            return None
        try:
            decision = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            self.session.last_error = "BAD_LLM_OUTPUT（不是 JSON）"
            return None
        if not isinstance(decision, dict) or decision.get("tool") not in TOOL_NAMES:
            self.session.last_error = "BAD_LLM_OUTPUT（tool 不在白名单）"
            return None
        self.session.usage["prompt_tokens"] = int(
            self.session.usage.get("prompt_tokens", 0)) + estimate_messages(messages)
        self.session.usage["completion_tokens"] = int(
            self.session.usage.get("completion_tokens", 0)) + estimate_tokens(raw)
        self.events.emit("decision", tool=decision.get("tool"),
                         thought=str(decision.get("thought") or "")[:500],
                         round=self.session.round, step=self.session.step)
        self.events.emit("react.reason",
                         thought=str(decision.get("thought") or "")[:500],
                         subgoal_id=self.session.active_subgoal,
                         tool=decision.get("tool"))
        return decision

    def _ask_llm(self, messages: List[Dict[str, Any]]):
        payload = {
            "task": self.session.task,
            "state": self.machine.state.value,
            "round": self.session.round,
            "step": self.session.step,
            "plan": self.session.plan,
            "subgoals": self.session.subgoals,
            "active_subgoal": self.session.active_subgoal,
            "changed_files": self.session.working.get("changed_files") or [],
            "todos": self.session.working.get("todos") or [],
            "history": self._history(),
            "messages": messages,
        }
        try:
            if self.planner is not None:
                return self.planner(payload)
            from src.tools.common.lib.llm_call import call_llm_messages
            raw = call_llm_messages(
                messages, output_schema=DECISION_SCHEMA,
                prompt_version="workspace_harness_v1",
                task_type="sandbox_loop")
            if not raw:
                self._llm_unavailable = True
                self.session.last_error = "LLM_UNAVAILABLE（无 key 或调用失败）"
                return None
            return raw
        except Exception as exc:                  # noqa: BLE001 决策失败按错误步处理
            self.session.last_error = f"LLM_ERROR: {exc}"
            self._llm_unavailable = True
            return None

    def _history(self) -> List[Dict[str, Any]]:
        rows = []
        for message in self.session.messages[-12:]:
            rows.append({"role": message.get("role"),
                         "content": str(message.get("content"))[:1200],
                         "tool": (message.get("tool_calls") or [{}])[0]
                         .get("function", {}).get("name", "")
                         if message.get("role") == "assistant" else message.get("name", "")})
        return rows

    # ── 恢复 / 取消 ───────────────────────────────────────────────────────

    def resume(self, *, approve: Optional[bool] = None, answer: str = "",
               plan: str = "") -> Dict[str, Any]:
        if self.machine.state == HarnessState.AWAITING_PLAN:
            return self._resume_plan(approve, plan)
        if self.machine.state == HarnessState.PAUSED:
            return self._resume_paused(approve, answer)
        if self.machine.terminal:
            return self._terminal_result()
        return self._loop(None)

    def _resume_plan(self, approve: Optional[bool], plan: str) -> Dict[str, Any]:
        if approve is None:
            return self._paused_result()
        if approve is False:
            return self._cancel_result("plan rejected")
        if plan:
            self.session.plan = plan
        self.session.plan_approved = True
        self.session.pending = {}
        self._transition(HarnessState.PLANNING, "plan approved")
        return self._loop(None)

    def _resume_paused(self, approve: Optional[bool], answer: str) -> Dict[str, Any]:
        pending = dict(self.session.pending or {})
        kind = pending.get("kind")
        if kind == "answer":
            return self._resume_answer(pending, answer)
        if kind == "approval":
            return self._resume_approval(pending, approve)
        return self._paused_result()

    def _resume_answer(self, pending: Dict[str, Any], answer: str) -> Dict[str, Any]:
        record_result(self.session, pending.get("call_id", ""), "ask_user",
                      {"ok": True, "result": {"answer": answer}}, self.zones)
        self.session.append("user", answer)
        self.session.pending = {}
        self._transition(HarnessState.PLANNING, "user answered")
        return self._loop(None)

    def _resume_approval(self, pending: Dict[str, Any],
                         approve: Optional[bool]) -> Dict[str, Any]:
        if approve is None:
            return self._paused_result()
        tool = str(pending.get("tool") or "")
        args = dict(pending.get("args") or {})
        call_id = str(pending.get("call_id") or "")
        self.session.pending = {}
        if not approve:
            record_result(self.session, call_id, tool,
                          {"ok": False, "error": "denied by human"}, self.zones, args)
            self._transition(HarnessState.PLANNING, "approval denied")
            return self._loop(None)
        self._transition(HarnessState.ACTING, "approval granted")
        result = self._execute_tool(tool, args)
        self._transition(HarnessState.OBSERVING, tool)
        record_result(self.session, call_id, tool, result, self.zones, args)
        self._transition(HarnessState.PLANNING, "approved tool done")
        return self._loop(None)

    def cancel(self, reason: str = "cancelled") -> Dict[str, Any]:
        self._cancelled = True
        return self._cancel_result(reason)

    def _cancel_result(self, reason: str) -> Dict[str, Any]:
        if self.machine.can(HarnessState.CANCELLED):
            self._transition(HarnessState.CANCELLED, reason)
        goal_mod.finish_round(self.session.goal, "cancelled", reason)
        goal_mod.finish_goal(self.session.goal, "cancelled", reason)
        self.session.last_error = reason
        self.session.save(self.zones)
        return {"status": "cancelled", "reason": reason,
                "session": self.session.projection()}

    # ── 结果辅助 ──────────────────────────────────────────────────────────

    def _block(self, code: str, message: str, *, status: str = "blocked") -> Dict[str, Any]:
        if self.machine.can(HarnessState.BLOCKED):
            self._transition(HarnessState.BLOCKED, f"{code}: {message}")
        goal_mod.finish_round(self.session.goal, "blocked", message)
        goal_mod.finish_goal(self.session.goal, "blocked", message)
        self.session.last_error = message
        self.session.save(self.zones)
        return {"status": status, "reason": code, "error": message,
                "session": self.session.projection()}

    def _paused_result(self) -> Dict[str, Any]:
        self.session.save(self.zones)
        return {"status": "paused", "pending": dict(self.session.pending),
                "session": self.session.projection()}

    def _terminal_result(self) -> Dict[str, Any]:
        return {"status": self.machine.state.value,
                "session": self.session.projection()}

    def _account_usage(self, args: Dict[str, Any], result: Any) -> None:
        text = json.dumps(result, ensure_ascii=False, default=str)
        self.session.usage["completion_tokens"] = int(
            self.session.usage.get("completion_tokens", 0)) + estimate_tokens(text)
