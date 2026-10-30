"""StimulusPlan IR —— AI 生成“结构化激励声明”，后端负责执行。

这是 **generated / player 两个后端的公共前置层**：

    TP IR ──► StimulusPlan（本模块，确定性、可哈希）
                   ├─ generated：当前默认后端（UVM test/sequence 生成）
                   └─ player   ：可选后端（限定 stimulus/sequence、单 agent、静态 plan）

设计约束（第一版，刻意保守）：
  · 只接受 `stimulus` / `sequence` / `backdoor` 三类 realization 进入 plan；
    `observe` 不产生激励，进 `unsupported`；
  · player 后端第一版只支持 `stimulus` / `sequence`，且要求单 agent；
  · **不在这里执行任何 UVM**，也不让 LLM 手写 adapter —— plan 的字段来自
    casemodel 的 `realization.field`，adapter 应由生成器从同一份字段表产出；
  · 同输入 → 同 sha256；plan + seed + PlaybackLog 才能构成可复现证据。

当前状态：generated 可用；player 的 **runtime 尚未实现**。选 player 会得到
显式 `StimulusBackendError`，不静默退回 generated —— 这正是“不静默降级”。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

SCHEMA = "stimulus_plan_v1"
DEFAULT_BACKEND = "generated"
PLAYER_KINDS = ("stimulus", "sequence")

#: 后端能力表。`runtime` 是**能否执行**，不是“能否生成 plan”。
BACKENDS: Dict[str, Dict[str, Any]] = {
    "generated": {
        "kinds": ("stimulus", "sequence", "backdoor"),
        "runtime": True,
        "note": "默认后端：编译期检查 + 标准 UVM 调试路径",
    },
    "player": {
        "kinds": PLAYER_KINDS,
        "runtime": False,
        "note": "可选后端：第一版限定 stimulus/sequence、单 agent、静态 plan；runtime 未实现",
    },
}


class StimulusBackendError(RuntimeError):
    """后端选择/能力不满足 —— 显式失败，不静默换后端。"""


def backend_info(name: str) -> Dict[str, Any]:
    backend = BACKENDS.get(str(name or ""))
    if backend is None:
        raise StimulusBackendError(
            f"未知 stimulus 后端 {name!r}（已知：{'、'.join(BACKENDS)}）")
    return backend


def ensure_backend_executable(name: str) -> None:
    """执行前检查。player 在 runtime 落地前**明确报错**。"""
    info = backend_info(name)
    if not info.get("runtime"):
        raise StimulusBackendError(
            f"stimulus 后端 {name!r} 的 runtime 尚未实现 —— 当前可执行后端只有 "
            f"{[k for k, v in BACKENDS.items() if v.get('runtime')]}；"
            f"plan 仍可生成（用于对照/预演），但不允许假装执行")


def _canonical(doc: Dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, default=str)


def plan_digest(plan: Dict[str, Any]) -> str:
    body = {k: v for k, v in plan.items() if k != "sha256"}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def _transactions(realization: Dict[str, Any],
                  kind: str) -> List[Dict[str, Any]]:
    if kind == "stimulus":
        return [{"field": realization.get("field", ""),
                 "value": realization.get("value")}]
    if kind == "sequence":
        return [{"value": v, "ordinal": i}
                for i, v in enumerate(realization.get("values") or [])]
    if kind == "backdoor":
        return [{"path": realization.get("path", ""),
                 "value": realization.get("value")}]
    return []


def _entry(tp: Dict[str, Any], realization: Dict[str, Any],
           kind: str) -> Dict[str, Any]:
    execution = tp.get("execution") or {}
    return {
        "tp_id": str(tp.get("tp_id") or ""),
        "kind": kind,
        "agent": str(realization.get("agent") or ""),
        "test": str(execution.get("test") or ""),
        "stage": str(execution.get("stage") or ""),
        "transactions": _transactions(realization, kind),
    }


def _unsupported(tp: Dict[str, Any], kind: str, backend: str) -> Dict[str, Any]:
    return {
        "tp_id": str(tp.get("tp_id") or ""), "kind": kind or "unknown",
        "reason": ("observe 不产生激励" if kind == "observe"
                   else f"后端 {backend} 不支持 {kind or 'unknown'}"),
    }


def _single_agent(entries: List[Dict[str, Any]]):
    """player v1 只保留一个 agent；其余如实进 unsupported。"""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        groups.setdefault(entry["agent"], []).append(entry)
    if len(groups) <= 1:
        return entries, []
    keep = sorted(groups)[0]
    kept, dropped = [], []
    for agent, group in sorted(groups.items()):
        if agent == keep:
            kept.extend(group)
            continue
        dropped.extend({"tp_id": e["tp_id"], "kind": e["kind"],
                        "reason": f"player v1 只支持单 agent（已选 {keep}）"}
                       for e in group)
    return kept, dropped


def build_stimulus_plan(testpoints: List[Dict[str, Any]],
                        backend: str = DEFAULT_BACKEND,
                        module: str = "",
                        seed: int = 0) -> Dict[str, Any]:
    """TP IR → StimulusPlan。纯函数，不读盘、不跑 EDA、不调 LLM。"""
    info = backend_info(backend)
    allowed = set(info.get("kinds") or ())
    entries: List[Dict[str, Any]] = []
    unsupported: List[Dict[str, Any]] = []

    for tp in testpoints or []:
        if not isinstance(tp, dict) or not tp.get("tp_id"):
            continue
        realization = tp.get("realization") or {}
        kind = str(realization.get("kind") or "")
        if kind not in allowed:
            unsupported.append(_unsupported(tp, kind, backend))
        else:
            entries.append(_entry(tp, realization, kind))

    if backend == "player":
        entries, dropped = _single_agent(entries)
        unsupported.extend(dropped)

    plan = {
        "schema": SCHEMA,
        "backend": backend,
        "module": module,
        "seed": int(seed or 0),
        "testpoints": entries,
        "unsupported": unsupported,
        "stats": {
            "total": len(entries) + len(unsupported),
            "planned": len(entries),
            "unsupported": len(unsupported),
            "by_kind": _count(entries, "kind"),
        },
    }
    plan["sha256"] = plan_digest(plan)
    return plan


def _count(rows: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows:
        k = str(row.get(key) or "")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def write_stimulus_plan(output_dir: str | Path,
                        plan: Dict[str, Any]) -> Dict[str, Any]:
    """落 `coverage/stimulus_plan.json`；返回路径/哈希/计数。"""
    root = Path(output_dir)
    path = root / "coverage" / "stimulus_plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return {
        "path": str(path),
        "schema": plan.get("schema", SCHEMA),
        "sha256": plan.get("sha256") or plan_digest(plan),
        "backend": plan.get("backend", DEFAULT_BACKEND),
        "planned": (plan.get("stats") or {}).get("planned", 0),
        "unsupported": (plan.get("stats") or {}).get("unsupported", 0),
    }


def load_stimulus_plan(output_dir: str | Path) -> Dict[str, Any]:
    path = Path(output_dir) / "coverage" / "stimulus_plan.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def build_and_write(testpoints: List[Dict[str, Any]],
                    output_dir: str | Path,
                    backend: str = DEFAULT_BACKEND,
                    module: str = "", seed: int = 0) -> Dict[str, Any]:
    """常用组合：建 plan → 落盘。"""
    plan = build_stimulus_plan(testpoints, backend=backend,
                               module=module, seed=seed)
    return write_stimulus_plan(output_dir, plan)
