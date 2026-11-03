"""UVM IR 影子模式 —— 先比较 IR 与现有模型/ctx，不改变任何产物字节。

三步走的第 1 步：把 `AgentModel` / `EnvironmentModel` 映射成 IR，再和现有
渲染上下文逐项比对；只 print warning。确认稳定后再做字节门禁，最后 IR-first。
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from .uvm_ir import build_agent_ir, build_uvm_ir

ENV_FLAG = "SIGNOFFAI_UVM_IR_SHADOW"


def shadow_enabled() -> bool:
    return os.environ.get(ENV_FLAG, "on").strip().lower() != "off"


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def compare_agent_context(agent: Any, ctx: Dict[str, Any]) -> List[str]:
    """返回差异说明；空列表 = 影子比对一致（或 ctx 没有可比字段）。"""
    issues: List[str] = []
    ir = build_agent_ir(agent)
    obj = ctx.get("agent", agent)
    for key, ir_value in (("name", ir.name), ("interface", ir.interface),
                          ("agent_type", ir.agent_type)):
        value = _attr(obj, key, None)
        if value is not None and str(value) != str(ir_value):
            issues.append(f"{key}: ctx={value!r} ir={ir_value!r}")
    ports = _attr(obj, "ports", None)
    if isinstance(ports, list) and ports:
        ir_ports = [(p.name, p.direction) for p in ir.ports]
        ctx_ports = [(str(p.get("name") or ""), str(p.get("direction") or p.get("dir") or ""))
                     for p in ports if isinstance(p, dict)]
        if ir_ports != ctx_ports:
            issues.append(f"ports: ctx={ctx_ports[:5]} ir={ir_ports[:5]}")
    return issues


def compare_environment_context(env: Any, ctx: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    ir = build_uvm_ir(env)
    obj = ctx.get("environment", env)
    name = _attr(obj, "env_name", None)
    if name is not None and str(name) != ir.env.name:
        issues.append(f"env_name: ctx={name!r} ir={ir.env.name!r}")
    agents = _attr(obj, "agents", None)
    if isinstance(agents, list):
        names = [_attr(a, "name", "") for a in agents]
        if [n for n in names if n] != ir.env.agents:
            issues.append(f"agents: ctx={names} ir={ir.env.agents}")
    return issues


def warn_shadow(scope: str, issues: List[str]) -> None:
    for issue in issues:
        print(f"  [gen_uvm] IR shadow {scope}: {issue}", flush=True)
