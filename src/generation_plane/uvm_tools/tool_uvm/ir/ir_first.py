"""P0 —— UVM IR-first 的切换接口（先提供审计与合并，不强行改渲染）。

    AgentModel / EnvironmentModel
                 │
                 ▼
              UVM IR
                 │
                 ▼
          IR Validation
                 │
                 ▼
         Render Context
                 │
                 ▼
            Jinja Templates

现阶段：
- `audit()`：IR 与现有 ctx 逐字段比对，给出是否可切 IR-first 的读数；
- `merge_context()`：把 IR 拥有的字段覆盖到 ctx（`SIGNOFFAI_UVM_IR_FIRST=on`
  时调用方可用）；
- `assert_consistent()`：不一致直接报错，避免“shadow 绿、渲染仍绕 IR”。
"""
from __future__ import annotations

import dataclasses
import os
from typing import Any, Dict, List

from .shadow import compare_agent_context, compare_environment_context
from .uvm_ir import build_agent_ir, build_uvm_ir, validate_ir

IR_FIRST_FLAG = "SIGNOFFAI_UVM_IR_FIRST"


def enabled() -> bool:
    return os.environ.get(IR_FIRST_FLAG, "").strip().lower() in (
        "1", "on", "true", "yes")


def _agent_ir_fields(agent: Any) -> Dict[str, Any]:
    ir = build_agent_ir(agent)
    return {
        "name": ir.name,
        "interface": ir.interface,
        "agent_type": ir.agent_type,
        "ports": [{"name": p.name, "direction": p.direction,
                   "width": p.width, "protocol": p.protocol}
                  for p in ir.ports],
    }


def ir_context(env: Any) -> Dict[str, Any]:
    """IR 拥有的渲染字段（agent / env 两层）。"""
    ir = build_uvm_ir(env)
    return {
        "env_name": ir.env.name,
        "agents": [_agent_ir_fields(a) for a in ir.agents],
        "tests": [t.name for t in ir.tests],
    }


def _name_of(agent: Any) -> str:
    if isinstance(agent, dict):
        return str(agent.get("name") or "")
    return str(getattr(agent, "name", "") or "")


def _ir_field(ir_agent: Any, key: str) -> str:
    value = ir_agent.get(key) if isinstance(ir_agent, dict) \
        else getattr(ir_agent, key, "")
    return str(value or "")


def _merge_agent(agent: Any, ir_agent: Any) -> Any:
    """IR 拥有的字段覆盖到**原对象**上（保留模板需要的其余字段与派生属性）。"""
    if ir_agent is None:
        return agent
    fields = {"name": _ir_field(ir_agent, "name"),
              "interface": _ir_field(ir_agent, "interface"),
              "agent_type": _ir_field(ir_agent, "agent_type")}
    if dataclasses.is_dataclass(agent) and not isinstance(agent, type):
        return dataclasses.replace(agent, **fields)
    if isinstance(agent, dict):
        return {**agent, **fields}
    for key, value in fields.items():
        if value:
            try:
                setattr(agent, key, value)
            except (AttributeError, TypeError):
                pass
    return agent


def merge_agent_context(agent: Any, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """单 agent 渲染 ctx：IR 字段覆盖（保留 dataclass 类型与派生属性）。"""
    ir_agent = build_agent_ir(agent)
    merged = dict(ctx or {})
    merged["name"] = ir_agent.name or merged.get("name", "")
    merged["interface"] = ir_agent.interface or merged.get("interface", "")
    merged["agent_type"] = ir_agent.agent_type or merged.get("agent_type", "")
    return merged


def merge_context(env: Any, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """把 IR 字段覆盖到 ctx；**不改 ctx 里 IR 不拥有的字段**。"""
    merged = dict(ctx or {})
    owned = ir_context(env)
    merged["env_name"] = owned["env_name"] or merged.get("env_name", "")
    agents = list(merged.get("agents") or [])
    if agents and owned["agents"]:
        by_name = {a["name"]: a for a in owned["agents"]}
        merged["agents"] = [
            _merge_agent(agent, by_name[_name_of(agent)])
            if _name_of(agent) in by_name else agent
            for agent in agents
        ]
    return merged


def assert_consistent(env: Any, ctx: Dict[str, Any] = None) -> None:
    """IR 与 ctx 不一致 → 抛错；IR-first 切换前的硬闸。"""
    issues = compare_environment_context(env, ctx)
    issues += [f"agent {i}" for i in compare_agent_context(env, ctx)]
    ir = build_uvm_ir(env)
    structural = validate_ir(ir, require_ports=False)
    if structural:
        raise ValueError(f"UVM IR 结构不合法: {structural}")
    if issues:
        raise ValueError("UVM IR 与渲染 ctx 不一致: " + "; ".join(issues))


def write_audit(root: Any, environments: List[Any]) -> Dict[str, Any]:
    """把 IR-first 就绪读数落到 `docs/ir_first_audit.json`（可多环境合并）。"""
    import json
    from pathlib import Path

    doc = audit(environments)
    path = Path(root) / "docs" / "ir_first_audit.json"
    try:
        existing = json.loads(path.read_text(encoding="utf-8",
                                             errors="replace"))
    except (OSError, ValueError):
        existing = {}
    rows = {str(r.get("env_name")): r for r in (existing.get("envs") or [])
            if isinstance(r, dict)}
    for row in doc.get("envs") or []:
        rows[str(row.get("env_name"))] = row
    merged = list(rows.values())
    doc["envs"] = merged
    doc["ready"] = all(r.get("ready") for r in merged) if merged else True
    doc["differences"] = sum(len(r.get("shadow_differences") or [])
                             for r in merged)
    doc["structural_errors"] = sum(len(r.get("structural_errors") or [])
                                   for r in merged)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return doc


def audit(environments: List[Any]) -> Dict[str, Any]:
    """IR-first 就绪读数：结构合法性 + shadow 差异数。"""
    rows: List[Dict[str, Any]] = []
    for env in environments or []:
        ir = build_uvm_ir(env)
        structural = validate_ir(ir, require_ports=False)
        diffs = compare_environment_context(env)
        rows.append({
            "env_name": ir.env.name,
            "agents": len(ir.agents),
            "tests": len(ir.tests),
            "structural_errors": structural,
            "shadow_differences": diffs,
            "ready": not structural and not diffs,
        })
    return {
        "schema": "uvm_ir_first_audit_v1",
        "enabled": enabled(),
        "envs": rows,
        "ready": all(r["ready"] for r in rows) if rows else True,
        "differences": sum(len(r["shadow_differences"]) for r in rows),
        "structural_errors": sum(len(r["structural_errors"]) for r in rows),
    }


__all__ = [
    "IR_FIRST_FLAG", "assert_consistent", "audit", "enabled", "ir_context",
    "merge_agent_context", "merge_context", "write_audit",
]
