"""运行视图 —— 任务总览 / agent 产出 / 决策轨迹 / 清单 / 产物 / TODO。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.layers.l2_orchestration.flow_shared import (
    MAX_FILES_PER_DIR, UVM_SCHEMA, _artifact, _artifacts_of, _line_of, _num,
    _read_json, _read_journal, _resolve_run_dir, _schema_issues, _short,
    _size_kb, _stages_of,
)

ROLE_TITLES = {
    "design": "设计构建", "model": "参考模型", "verify": "验证构建",
    "ops": "编译与回归", "coverage": "覆盖率", "debug": "调试技术",
    "audit": "签核审查",
}


def run_agent_outputs(run_dir: str = "", role: str = "") -> Dict[str, Any]:
    """某个 agent 在这次运行里**做了什么**（阶段）+ **产出了什么**（文件）。

    阶段来自运行日志 —— 日志事件自带 `agent` 字段（写日志时就解析好了），
    所以这里不需要 import 任何领域代码就能按 agent 过滤。

    返回：
        {"role", "role_title", "run_dir", "stages": [...], "artifacts": [...],
         "notes": [...], "counts": {"stages", "files"}}
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error
    role = str(role or "").strip()
    if not role:
        return {"error": "没有给 agent 角色（清单里该模块的 params.role）"}

    events = _read_journal(root)
    stages = _stages_of(events, role)
    artifacts, notes = _artifacts_of(root, role)

    if not stages and not artifacts:
        notes.append(f"这次运行里没有 {role} 的痕迹 —— 可能还没跑到，或者被跳过了。")

    return {
        "role": role,
        "role_title": ROLE_TITLES.get(role, role),
        "run_dir": str(root),
        "stages": stages,
        "artifacts": artifacts,
        "notes": notes,
        "counts": {"stages": len(stages),
                   "files": sum(a["file_count"] for a in artifacts)},
    }


_SOURCE_TITLES = {
    "rule_hard": "硬规则",
    "rule": "规则",
    "rl_suggested": "RL 采纳",
    "rl_overridden": "RL 被退回",
    "terminal": "终态",
}


def run_decision_trace(run_dir: str = "") -> Dict[str, Any]:
    """每轮的决策与驾驭裁决。

    来源是 `decide` / `governor` 两个阶段的**结束事件**：节点写回的状态增量整个
    挂在 `payload.delta` 里（`RunJournal._summarise` 把它保留了），决策动作就在
    `delta.pending_action`、驾驭结论在 `delta.governance_outcome`。

    为什么不去读 `decision` 事件：`RunJournal.decision()` **定义了但没有任何调用点**
    —— 日志里根本没有那种事件。拿它当数据源会画出一张永远空的表。

    返回：`{"run_dir", "available", "rounds": [...], "note"}`
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    events = _read_journal(root)
    if not events:
        return {"run_dir": str(root), "available": False, "rounds": [],
                "note": "没有运行日志（docs/run_events.jsonl）—— 这次运行还没开始写，或目录不对"}

    by_round: Dict[int, Dict[str, Any]] = {}
    for event in events:
        stage = str(event.get("stage", ""))
        if event.get("kind") not in ("stage.finished", "stage.failed"):
            continue
        if stage not in ("decide", "governor", "coverage"):
            continue
        round_no = int(event.get("round", 0) or 0)
        row = by_round.setdefault(round_no, {
            "round": round_no, "action": "", "reason": "", "priority": "",
            "params": "", "governance": "", "source": "", "source_label": "",
            "reward": ""})
        delta = (event.get("payload") or {}).get("delta") or {}
        if stage == "decide":
            action = delta.get("pending_action") or {}
            if isinstance(action, dict):
                row["action"] = str(action.get("action_type", "") or "")
                row["reason"] = str(action.get("reason", "") or "")
                row["priority"] = str(action.get("priority", "") or "")
                source = str(action.get("source", "") or "")
                row["source"] = source
                row["source_label"] = _SOURCE_TITLES.get(source, source)
                params = action.get("params")
                row["params"] = ("、".join(f"{k}={v}" for k, v in sorted(params.items()))
                                 if isinstance(params, dict) and params else "")
        elif stage == "governor":
            row["governance"] = str(delta.get("governance_outcome", "") or "")
        elif stage == "coverage":
            reward = delta.get("sim_reward") or {}
            if isinstance(reward, dict) and reward.get("total") is not None:
                row["reward"] = (f"{reward.get('total'):g}"
                                 f"（最弱 {reward.get('weakest') or '?'}）")

    rounds = [by_round[k] for k in sorted(by_round)]
    note = "" if rounds else ("日志里没有 decide/governor 阶段事件 —— 这次运行可能停在"
                              "更早的阶段，或者只是还没转第一轮。")
    return {"run_dir": str(root), "available": bool(rounds), "rounds": rounds, "note": note}


_MANIFEST_KEYS = (
    ("architecture", "架构"), ("run_id", "运行 id"), ("iterations", "轮次"),
    ("final_coverage", "最终覆盖率"), ("effective_coverage", "有效覆盖率"),
    ("target", "目标"), ("generator", "生成器"),
)


def run_manifest_info(run_dir: str = "") -> Dict[str, Any]:
    """运行清单（`docs/manifest.json`）+ 文件变更链（`docs/file_change_chain.json`）。

    **只展示、不校验**：哈希链的完整性校验要调 L2 的 `FileAuditTrail.verify_persisted`
    —— 工具层不该反向依赖层代码。校验属于「治理动作」，留给 P3（见
    docs/design/agent_gui_business_architecture.md §6）。

    返回：`{"run_dir", "manifest": {...}, "change_chain": {...}, "notes"}`
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    notes: List[str] = []
    raw = _read_json(root / "docs" / "manifest.json")
    manifest: Dict[str, Any] = {"available": False, "rows": []}
    if raw is None:
        notes.append("没有 docs/manifest.json —— 这次运行还没跑完（manifest 是收尾时写的）")
    else:
        rows = [{"key": title, "value": _short(raw.get(key))}
                for key, title in _MANIFEST_KEYS if raw.get(key) not in (None, "")]
        hashes = raw.get("rtl_hashes")
        if isinstance(hashes, dict):
            rows.append({"key": "RTL 文件哈希", "value": f"{len(hashes)} 个"})
        manifest = {"available": True, "rows": rows,
                    "manifest_hash": str(raw.get("manifest_hash", "") or ""),
                    "evidence_hash": str(raw.get("evidence_hash", "") or "")}

    chain_raw = _read_json(root / "docs" / "file_change_chain.json")
    chain: Dict[str, Any] = {"available": False, "entries": 0, "rows": []}
    if chain_raw is None:
        notes.append("没有 docs/file_change_chain.json —— 没有记录到文件变更")
    else:
        changes = chain_raw.get("changes") if isinstance(chain_raw, dict) else None
        if not isinstance(changes, list):
            changes = []
        chain = {
            "available": bool(changes),
            "entries": len(changes),
            "rows": [{"seq": str(c.get("seq", "")),
                      "agent": str(c.get("agent", "")),
                      "file": str(c.get("file", c.get("file_path", ""))),
                      "reason": str(c.get("reason", ""))} for c in changes[:MAX_FILES_PER_DIR]],
        }
        if len(changes) > MAX_FILES_PER_DIR:
            notes.append(f"变更链有 {len(changes)} 条，界面只列前 {MAX_FILES_PER_DIR} 条。")

    return {"run_dir": str(root), "manifest": manifest,
            "change_chain": chain, "notes": notes}


_TERMINAL_STATES = {
    "run.finished": "completed",
    "run.failed": "failed",
    "run.cancelled": "cancelled",
    "run.interrupted": "waiting",       # 挂着等人审批
}


def run_task(run_dir: str = "") -> Dict[str, Any]:
    """一次运行**作为一个验证任务**的总览：目标 / 进度 / 收敛判断 / 卡在哪。

    面向的问题只有一个 —— **这个任务现在什么情况、还差多少、该不该继续。**

    数据源两条，按"谁更权威"取：
      · 跑完了 → `docs/manifest.json`（含 `planning.convergence_forecast`，规划器
        按最近提升速率算的"还要几轮"）
      · 还在跑 → `docs/run_events.jsonl`（逐轮的 coverage.updated 与阶段事件）

    返回：
        {"run_dir", "available", "state", "target",
         "coverage": {history, final, effective, target, gap, converged},
         "forecast": {rounds_to_target, converging, note},
         "phases": {total, passed, failed, skipped, rows},
         "current": {stage, title, status}, "blockers": [...], "summary"}
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    events = _read_journal(root)
    manifest = _read_json(root / "docs" / "manifest.json")
    if not events and manifest is None:
        return {"run_dir": str(root), "available": False,
                "state": "unknown", "target": None,
                "coverage": _empty_coverage(), "forecast": {},
                "phases": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "rows": []},
                "current": {}, "blockers": [],
                "summary": "这次运行还没有任何记录（既没有运行日志也没有运行清单）。"}

    state = _task_state(events, manifest)
    coverage = _task_coverage(events, manifest)
    forecast = _forecast_of(manifest)
    phases = _phases_of(manifest, events)
    current = _current_stage(events)
    blockers = _blockers_of(events, phases)

    return {
        "run_dir": str(root),
        "available": True,
        "state": state,
        "target": coverage.get("target"),
        "coverage": coverage,
        "forecast": forecast,
        "phases": phases,
        "current": current,
        "blockers": blockers,
        "summary": _task_summary(state, coverage, forecast, phases, blockers),
    }


def _empty_coverage() -> Dict[str, Any]:
    return {"history": [], "final": None, "effective": None, "target": None,
            "gap": None, "converged": None}


def _task_state(events: List[Dict[str, Any]], manifest: Optional[Dict[str, Any]]) -> str:
    """任务的生命周期状态。

    `completed_with_errors` 是沿用 DB 里 `PipelineRun.state` 的既有取值 ——
    "跑完了"和"跑成功了"是两件事：跑完但没达标/有卡点，得能一眼看出来。
    """
    for event in reversed(events):
        mapped = _TERMINAL_STATES.get(str(event.get("kind", "")))
        if mapped:
            return mapped
    if isinstance(manifest, dict) and manifest:
        # 有 manifest = 收尾过；再按"达标了没"细分
        return "completed" if manifest.get("converged") else "completed_with_errors"
    return "running"


def _task_coverage(events: List[Dict[str, Any]],
                   manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """逐轮覆盖率曲线 + 最终值 + 与目标差多少。"""
    history: List[List[Any]] = []
    for event in events:
        if event.get("kind") != "coverage.updated":
            continue
        payload = event.get("payload") or {}
        total = _num(payload.get("total"))
        if total is None:
            continue
        # 与 evidence / run_common 同一口径：事件里的 round 本身就是 1-based
        round_no = max(1, int(event.get("round", 0) or 0))
        history.append([round_no, total])

    out = _empty_coverage()
    out["history"] = history

    if isinstance(manifest, dict) and manifest:
        target = _num(manifest.get("target"))
        final = _num(manifest.get("final_coverage"))
        effective = _num(manifest.get("effective_coverage"))
        converged = manifest.get("converged")
        if effective is None:
            effective = final
    else:
        target, final, effective, converged = None, None, None, None
        # 跑完了的 run 会在 run.finished 里带最终值
        for event in reversed(events):
            if event.get("kind") == "run.finished":
                payload = event.get("payload") or {}
                target = _num(payload.get("target"))
                final = _num(payload.get("final_coverage"))
                effective = _num(payload.get("effective_coverage")) or final
                converged = payload.get("converged")
                break
        if final is None and history:
            final = effective = history[-1][1]

    out["target"] = target
    out["final"] = final
    out["effective"] = effective
    out["converged"] = bool(converged) if converged is not None else None
    # 差多少 —— 用「有效覆盖率」算，那是决策层真正看的数
    base = effective if effective is not None else final
    out["gap"] = (round(target - base, 1)
                  if target is not None and base is not None else None)
    return out


def _forecast_of(manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """规划器的收敛预测。`inf` 在 JSON 里不是合法值，这里换成 None + 说明。"""
    if not isinstance(manifest, dict):
        return {}
    planning = manifest.get("planning")
    if not isinstance(planning, dict):
        return {}
    raw = planning.get("convergence_forecast")
    if not isinstance(raw, dict):
        return {}
    rounds = raw.get("rounds_to_target")
    note = str(raw.get("note", "") or "")
    if isinstance(rounds, float) and rounds == float("inf"):
        return {"rounds_to_target": None, "converging": False,
                "note": note or "覆盖率停滞，需换策略"}
    return {"rounds_to_target": rounds, "converging": raw.get("converging"),
            "note": note}


def _phases_of(manifest: Optional[Dict[str, Any]],
               events: List[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """阶段统计。

    跑完了看 `manifest.phases`；**还在跑时没有 manifest** —— 退回到运行日志里的
    阶段结束事件，否则"运行中"那一行会是空的（看不到跑到第几步了）。
    """
    rows: List[Dict[str, Any]] = []
    counts = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    source = (manifest or {}).get("phases") if isinstance(manifest, dict) else None
    if source:
        for phase in source:
            if not isinstance(phase, dict):
                continue
            status = str(phase.get("status", "") or "")
            rows.append({"name": str(phase.get("name", "")), "status": status,
                         "score": phase.get("score", "")})
    else:
        for event in events:
            kind = str(event.get("kind", ""))
            if kind not in ("stage.finished", "stage.failed"):
                continue
            status = "failed" if kind == "stage.failed" else "passed"
            rows.append({"name": str(event.get("title") or event.get("stage") or ""),
                         "status": status, "score": ""})

    for row in rows:
        counts["total"] += 1
        if row["status"] in counts:
            counts[row["status"]] += 1
    return {**counts, "rows": rows}


def _current_stage(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """最后一条阶段事件的落点 —— 还在跑时用来看「现在在哪一步」。"""
    for event in reversed(events):
        if not str(event.get("kind", "")).startswith("stage."):
            continue
        return {"stage": str(event.get("stage", "")),
                "title": str(event.get("title") or event.get("stage") or ""),
                "status": str(event.get("status", ""))}
    return {}


def _blockers_of(events: List[Dict[str, Any]], phases: Dict[str, Any]) -> List[Dict[str, Any]]:
    """卡在哪：失败/出错的阶段（阶段事件 + manifest.phases 两处都收）。"""
    blockers: List[Dict[str, Any]] = []
    for event in events:
        if event.get("kind") != "stage.failed":
            continue
        blockers.append({"title": str(event.get("title") or event.get("stage") or ""),
                         "round": int(event.get("round", 0) or 0),
                         "error": str((event.get("payload") or {}).get("error", ""))})
    if not blockers:
        for row in phases.get("rows") or []:
            if row["status"] in ("failed", "error"):
                blockers.append({"title": row["name"], "round": 0, "error": ""})
    return blockers


def _task_summary(state: str, coverage: Dict[str, Any], forecast: Dict[str, Any],
                  phases: Dict[str, Any], blockers: List[Dict[str, Any]]) -> str:
    """一句话总览 —— 界面顶部那行。**先说要紧的（卡住 / 差距），再说过程。**"""
    bits: List[str] = []
    state_cn = {"completed": "已完成", "completed_with_errors": "完成但有错",
                "running": "运行中", "failed": "失败", "cancelled": "已取消",
                "waiting": "等待审批", "unknown": "未知"}.get(state, state)
    bits.append(state_cn)

    target, final = coverage.get("target"), coverage.get("final")
    if final is not None:
        cov = f"覆盖率 {final:g}%"
        if target is not None:
            cov += f" / 目标 {target:g}%"
        bits.append(cov)
        if coverage.get("converged") is True:
            bits.append("已达标")
        elif coverage.get("gap") is not None and coverage["gap"] > 0:
            bits.append(f"还差 {coverage['gap']:g} 个点")

    if phases["total"]:
        bits.append(f"阶段 {phases['passed']}/{phases['total']} 过")
    if blockers:
        bits.append(f"{len(blockers)} 处卡点：" + "、".join(b["title"] for b in blockers[:3]))
    if forecast.get("rounds_to_target") is not None:
        bits.append(f"预测还需 {forecast['rounds_to_target']} 轮")
    elif forecast.get("converging") is False:
        bits.append("覆盖率停滞")
    return "　".join(bits) + "。"


from src.layers.l2_orchestration.run_artifacts import run_artifacts  # noqa: F401,E402

TODO_KINDS = {
    "approval": ("待审批", "warn"),
    "exclude": ("待签豁免", "warn"),
    "human": ("需人工确认", "warn"),
    "stuck": ("卡住的运行", "warn"),
    "harness": ("bench 侧挂死", "info"),
    "incomplete": ("产物不全", "info"),
}


def collect_todos(run_dir: str = "") -> Dict[str, Any]:
    """**「现在该干什么」** —— 把散在四个页面里的"需要人做的事"聚成一页。

    数据全是现成的，这页只做**聚合与排序**：

      · 待签的覆盖率豁免  —— 豁免登记册里 `pending` 的那几条（批了会动覆盖率分母）
      · 需人工确认        —— 阶段里的 `needs_human`（如 CDC："同步器对不对机器判不了"）
      · 待审批            —— 运行停在人工审批上（`approval` 阶段有 token 而没有结论）
      · 卡住的运行        —— 状态还是 running 但产物已经不再更新
      · bench 侧挂死      —— `harness_triage` 归过类的那几条（看一眼，**不改 RTL**）
      · 产物不全          —— 没有 `report.json`（没跑到 audit）→ 后面的页多半是空的

    排序：**要你动手的（warn）在前**，看一眼的（info）在后 —— 这页是"待办"，
    不是"概览"。
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    rows: List[Dict[str, Any]] = []

    # ── 待签豁免（**全局登记册**，不只这次运行）──
    # 提议由覆盖率阶段的自动发现一直攒，而批准会动覆盖率分母（不可逆），
    # 所以"有没有攒着没人批的"是这页最该先说的一条。
    try:
        from src.layers.l3_decision.evidence.exclude_api import read_excludes

        pending = (read_excludes() or {}).get("pending") or []
        if pending:
            rows.append({
                "kind": "exclude", "priority": 10,
                "item": f"{len(pending)} 条覆盖率豁免待签字",
                "detail": "、".join(str(p.get("id") or p) for p in pending[:5]),
                "action": "在「覆盖率豁免」页签（批准会把该点从覆盖率分母里拿掉）",
            })
    except Exception:                                  # noqa: BLE001 注册册读不到不算待办
        pass

    progress = _read_json(root / "docs" / "progress.json") or {}
    phases = progress.get("phases") or []

    # ── 需人工确认（根因的验证计划里 needs_human 那一档）──
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        if phase.get("needs_human"):
            rows.append({
                "kind": "human", "priority": 20,
                "item": f"「{phase.get('name', '')}」需要人工确认（{phase.get('root_cause', '')}）",
                "detail": str(phase.get("needs_human"))[:160],
                "action": "看「决策轨迹」里这一轮的根因与验证计划",
            })

    # ── 待审批：停在人工审批上的运形 ──
    stuck_approval = [p for p in phases
                      if isinstance(p, dict) and p.get("name") == "approval"
                      and p.get("token") and not p.get("outcome")]
    if stuck_approval:
        rows.append({
            "kind": "approval", "priority": 5,
            "item": f"运行停在人工审批上（{len(stuck_approval)} 处）",
            "detail": "、".join(str(p.get("action", "")) for p in stuck_approval[:3]),
            "action": "在「验证流程」页批准或拒绝，然后继续",
        })

    # ── 卡住 / 产物不全 ──
    has_report = (root / "report.json").exists()
    events = _read_journal(root)
    finished = bool(events) and str(events[-1].get("kind", "")) == "run.finished"
    if events and not finished:
        rows.append({
            "kind": "stuck", "priority": 8,
            "item": "这次运行没有正常结束（没有 run.finished 事件）",
            "detail": f"最后一条事件：{events[-1].get('kind', '')} "
                      f"{events[-1].get('stage', '')} @ {events[-1].get('ts', '')}",
            "action": "看「控制台」尾部日志；必要时重起一次运行",
        })
    elif not has_report:
        rows.append({
            "kind": "incomplete", "priority": 30,
            "item": "这次运行没有 report.json（没跑到 audit）",
            "detail": "签核判定 / 运行清单那几页会因此是空的",
            "action": "让它跑完，或换一次完整运行（「运行历史」）",
        })

    # ── bench 侧挂死（归过类的）──
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        triage = phase.get("harness_triage") or []
        if triage:
            prints = [str(t.get("fingerprint", "")) for t in triage if t.get("fingerprint")]
            rows.append({
                "kind": "harness", "priority": 40,
                "item": f"{len(triage)} 个 test 挂在 bench 侧（不是 DUT 功能错）",
                "detail": ("指纹：" + "、".join(p for p in prints[:3]) if prints
                           else str(triage[0].get("note", ""))[:120]),
                "action": "这些不改 RTL；看「回归状态」页的日志确认原因",
            })
            break

    rows.sort(key=lambda r: r.get("priority", 99))
    summary = {k: sum(1 for r in rows if r["kind"] == k) for k in TODO_KINDS}
    return {"run_dir": str(root), "rows": rows, "summary": summary,
            "notes": ([f"{sum(1 for r in rows if TODO_KINDS[r['kind']][1] == 'warn')} 项要你动手"]
                      if rows else ["没有待办 —— 这次运行没有需要人处理的事项"])}


def run_rule_drafts(run_dir: str = "") -> Dict[str, Any]:
    """这次运行起草了哪些规则草案、**哪些还没被人接受**。

    只读 + 带粘贴骨架：这一页的价值是"让草案看得见、点一下就接走" ——
    原来它只写在 `docs/rule_drafts.md` 里，得有人想起来去翻。
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error
    try:
        from src.knowledge.rule_draft import (STAGE_TITLES, accepted_ids,
                                                    collect_drafts, rule_skeleton)

        drafts = collect_drafts(root)
        done = set(accepted_ids(root))
        rows = [{
            "rule_id": str(d.get("rule_id", "")),
            "stage": STAGE_TITLES.get(str(d.get("stage", "")), str(d.get("stage", ""))),
            "severity": str(d.get("severity", "")),
            "evidence": str(d.get("note", ""))[:160],
            "fingerprint": str(d.get("fingerprint", ""))[:12],
            "accepted": str(d.get("rule_id", "")) in done,
            "skeleton": rule_skeleton(d),
        } for d in drafts]
        pending = [r for r in rows if not r["accepted"]]
        return {"run_dir": str(root), "rows": rows, "pending": len(pending),
                "md_path": str(root / "docs" / "rule_drafts.md"),
                "notes": ([f"{len(pending)} 条草案等人拍板 —— 接了就写进 semantic_check"]
                          if pending else ["没有待拍板的草案"])}
    except Exception as exc:                           # noqa: BLE001
        return {"error": f"读草案失败：{exc}"[:200]}
