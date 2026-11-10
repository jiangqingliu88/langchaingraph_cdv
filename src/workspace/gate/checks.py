"""Gate 的默认检查清单 —— 全部确定、可机械校验。

裁决逻辑是代码，不是模型：模型只“提议”，这里只回答“结构/证据/基线/差异
是否对得上”。领域检查（契约、回归、覆盖率阈值）通过 `extra_checks` 注入，
同样必须返回结构化结果。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List

from ..proposal.schema import Proposal
from ..zones import WorkspaceZones

#: 领域钩子：proposal + zones -> [{"name","status","severity","detail"}]
GateHook = Callable[[Proposal, WorkspaceZones], Iterable[Dict[str, Any]]]


def _row(name: str, status: str, detail: str = "",
         severity: str = "block", **extra: Any) -> Dict[str, Any]:
    row = {"name": name, "status": status, "severity": severity,
           "detail": detail}
    row.update(extra)
    return row


def check_schema(proposal: Proposal, zones: WorkspaceZones) -> List[Dict[str, Any]]:
    errors = proposal.validate(zones)
    if errors:
        return [_row("proposal_schema", "fail", "; ".join(errors))]
    return [_row("proposal_schema", "pass")]


def check_base(proposal: Proposal, zones: WorkspaceZones) -> List[Dict[str, Any]]:
    """proposal 基于的 main 基线必须还是当前 main；否则需要 rebase。"""
    expected = str((proposal.base or {}).get("main_fingerprint") or "")
    actual = zones.fingerprint("main")
    if not expected:
        return [_row("main_baseline", "fail", "proposal 缺 base.main_fingerprint")]
    if expected != actual:
        return [_row("main_baseline", "fail",
                     f"main 已变化（{expected[:12]} → {actual[:12]}），请 rebase")]
    return [_row("main_baseline", "pass")]


def check_diff(proposal: Proposal, zones: WorkspaceZones) -> List[Dict[str, Any]]:
    """proposal 的 changed_files 必须与 staging 当前差异逐项一致。"""
    expected = sorted((r.get("path"), r.get("action"), r.get("sha256"))
                      for r in proposal.changed_files)
    actual = sorted((r.get("path"), r.get("action"), r.get("sha256"))
                    for r in zones.changed_files())
    if expected != actual:
        missing = [item for item in actual if item not in expected]
        extra = [item for item in expected if item not in actual]
        return [_row("changed_files", "fail",
                     f"与 staging 差异不一致；未申报={missing[:5]}，"
                     f"申报但不存在={extra[:5]}")]
    if not actual:
        return [_row("changed_files", "fail", "staging 没有任何变更")]
    return [_row("changed_files", "pass", f"{len(actual)} 个文件")]


def check_evidence(proposal: Proposal, zones: WorkspaceZones) -> List[Dict[str, Any]]:
    evidence = proposal.evidence or {}
    rows: List[Dict[str, Any]] = []
    commands = evidence.get("commands") or []
    ok_commands = [c for c in commands if isinstance(c, dict)
                   and c.get("exit_code") == 0]
    failed = [c for c in commands if isinstance(c, dict)
              and type(c.get("exit_code")) is int and c.get("exit_code") != 0]
    if not ok_commands:
        rows.append(_row("evidence_commands", "fail",
                         "至少需要一条 exit_code=0 的复现命令"))
    else:
        rows.append(_row("evidence_commands", "pass",
                         f"{len(ok_commands)}/{len(commands)} 条成功"))
    if failed:
        rows.append(_row("evidence_commands_nonzero", "warn",
                         f"{len(failed)} 条命令非 0 退出（迭代过程可接受，需人工确认）",
                         severity="warn", human=True))
    # 日志已经由 proposal.validate 校过存在性；这里只确认数量非空。
    if not (evidence.get("logs") or []):
        rows.append(_row("evidence_logs", "fail", "没有日志"))
    else:
        rows.append(_row("evidence_logs", "pass"))
    return rows


def check_subgoals(proposal: Proposal, zones: WorkspaceZones) -> List[Dict[str, Any]]:
    """分解过的提案：每个子目标必须 done；blocked 进人工门。"""
    rows = (proposal.evidence or {}).get("subgoals") or []
    if not rows:
        return [_row("subgoals", "pass", "未分解（单目标）")]
    open_rows = [r for r in rows if r.get("status") in ("pending", "active")]
    blocked = [r for r in rows if r.get("status") == "blocked"]
    if open_rows:
        return [_row("subgoals", "fail",
                     "仍有未完成子目标：" + ", ".join(
                         f"{r.get('id')}:{r.get('title')}" for r in open_rows[:5]))]
    if blocked:
        return [_row("subgoals", "warn",
                     f"{len(blocked)} 个子目标 blocked（人工门必看）",
                     severity="warn", human=True,
                     questions=[r.get("summary") or r.get("title") for r in blocked])]
    return [_row("subgoals", "pass", f"{len(rows)} 个子目标全部完成")]


def check_open_questions(proposal: Proposal, zones: WorkspaceZones) -> List[Dict[str, Any]]:
    questions = [str(q) for q in (proposal.open_questions or []) if str(q).strip()]
    if questions:
        return [_row("open_questions", "warn",
                     f"{len(questions)} 个待决问题（人工门必看）",
                     severity="warn", human=True, questions=questions)]
    return [_row("open_questions", "pass", "无疑点")]


DEFAULT_CHECKS = (check_schema, check_base, check_diff, check_evidence,
                  check_subgoals, check_open_questions)
