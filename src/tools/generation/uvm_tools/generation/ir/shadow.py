"""UVM IR 影子模式 —— **双写比对**：IR 派生视图 vs 现有渲染上下文。

三步走的第 1 步：把 `AgentModel` / `EnvironmentModel` 映射成 IR，再从 IR
派生一份"渲染上下文"，与模板真正吃的 dataclass ctx 逐项比对：

    · 差异 → print warning + 记进 `docs/ir_shadow_diff.json`
    · **不改变任何产物字节**（模板仍吃 ctx，IR 还不是渲染输入）

为什么要落盘而不是只 print：`[gen_uvm] IR shadow` 混在几千行生成日志里没人
看得见，"IR 到底还差多少"就永远是个感觉。报告是机读的 —— 跑一个 sprint 后
可以直接回答：差异为 0 的字段有哪些、哪些字段 IR 还没映射（`ir_only` /
`ctx_only`），再决定字节门禁与 IR-first 的切换顺序。

关闭：`SIGNOFFAI_UVM_IR_SHADOW=off`（默认开）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .uvm_ir import build_agent_ir, build_uvm_ir

ENV_FLAG = "SIGNOFFAI_UVM_IR_SHADOW"
SCHEMA = "uvm_ir_shadow_v1"
DIFF_NAME = "ir_shadow_diff.json"
DIFF_REL = Path("docs") / DIFF_NAME

#: 影子比对的**契约字段** —— IR 必须复现这些；新增要先改这里，别悄悄放过。
AGENT_FIELDS = ("name", "interface", "agent_type", "ports")
ENV_FIELDS = ("env_name", "agents", "tests")


def shadow_enabled() -> bool:
    return os.environ.get(ENV_FLAG, "on").strip().lower() != "off"


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _port_rows(raw: Any) -> List[Dict[str, Any]]:
    """端口 → 可比较的规范行（`dir`/`direction` 两种写法和一律归一）。"""
    rows: List[Dict[str, Any]] = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        rows.append({
            "name": str(p.get("name") or ""),
            "direction": str(p.get("direction") or p.get("dir") or ""),
            "width": p.get("width", 1),
            "protocol": str(p.get("protocol") or p.get("proto") or ""),
        })
    return rows


def _agent_ir_ctx(agent: Any) -> Dict[str, Any]:
    ir = build_agent_ir(agent)
    return {
        "name": ir.name,
        "interface": ir.interface,
        "agent_type": ir.agent_type,
        "ports": [{"name": p.name, "direction": p.direction,
                   "width": p.width, "protocol": p.protocol}
                  for p in ir.ports],
    }


def _agent_ctx(agent: Any, ctx: Dict[str, Any]) -> Dict[str, Any]:
    obj = ctx.get("agent", agent)
    return {
        "name": _attr(obj, "name", ""),
        "interface": _attr(obj, "interface", ""),
        "agent_type": _attr(obj, "agent_type", ""),
        "ports": _port_rows(_attr(obj, "ports", [])),
    }


def _env_ir_ctx(env: Any) -> Dict[str, Any]:
    ir = build_uvm_ir(env)
    return {
        "env_name": ir.env.name,
        "agents": [a.name for a in ir.agents],
        "tests": [t.name for t in ir.tests],
    }


def _env_ctx(env: Any, ctx: Dict[str, Any]) -> Dict[str, Any]:
    obj = ctx.get("environment", env)
    agents = _attr(obj, "agents", []) or []
    names = [_attr(a, "name", "") if not isinstance(a, dict) else str(a.get("name") or "")
             for a in agents]
    tests = _attr(obj, "tests", []) or []
    return {
        "env_name": _attr(obj, "env_name", ""),
        "agents": [n for n in names if n],
        "tests": [str(t.get("name")) for t in tests
                  if isinstance(t, dict) and t.get("name")],
    }


def _norm(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list):
        return [_norm(v) for v in value]
    if isinstance(value, dict):
        return {k: _norm(v) for k, v in sorted(value.items())}
    return value


def _diff(ir_ctx: Dict[str, Any], ctx: Dict[str, Any],
          fields) -> List[Dict[str, Any]]:
    """逐字段比对 → `[{field, ir, ctx}]`（空 = 一致）。"""
    out: List[Dict[str, Any]] = []
    for key in fields:
        expected, actual = ir_ctx.get(key), ctx.get(key)
        if _norm(expected) != _norm(actual):
            out.append({"field": key, "ir": expected, "ctx": actual})
    return out


def compare_agent_context(agent: Any, ctx: Dict[str, Any] = None) -> List[str]:
    """agent：IR 派生视图 vs 渲染 ctx。返回人读差异（空 = 一致）。"""
    ir_ctx = _agent_ir_ctx(agent)
    model_ctx = _agent_ctx(agent, ctx or {})
    return [f"{d['field']}: ctx={d['ctx']!r} ir={d['ir']!r}"
            for d in _diff(ir_ctx, model_ctx, AGENT_FIELDS)]


def compare_environment_context(env: Any, ctx: Dict[str, Any] = None) -> List[str]:
    """environment：IR 派生视图 vs 渲染 ctx。返回人读差异（空 = 一致）。"""
    ir_ctx = _env_ir_ctx(env)
    model_ctx = _env_ctx(env, ctx or {})
    return [f"{d['field']}: ctx={d['ctx']!r} ir={d['ir']!r}"
            for d in _diff(ir_ctx, model_ctx, ENV_FIELDS)]


def agent_diff(agent: Any, ctx: Dict[str, Any] = None) -> Dict[str, Any]:
    """结构化的 agent 比对结果（写报告用）。"""
    ir_ctx = _agent_ir_ctx(agent)
    model_ctx = _agent_ctx(agent, ctx or {})
    return {"fields": list(AGENT_FIELDS),
            "differences": _diff(ir_ctx, model_ctx, AGENT_FIELDS),
            "ir": ir_ctx, "ctx": model_ctx}


def environment_diff(env: Any, ctx: Dict[str, Any] = None) -> Dict[str, Any]:
    """结构化的 environment 比对结果（写报告用）。"""
    ir_ctx = _env_ir_ctx(env)
    model_ctx = _env_ctx(env, ctx or {})
    return {"fields": list(ENV_FIELDS),
            "differences": _diff(ir_ctx, model_ctx, ENV_FIELDS),
            "ir": ir_ctx, "ctx": model_ctx}


def warn_shadow(scope: str, issues: List[str]) -> None:
    for issue in issues:
        print(f"  [gen_uvm] IR shadow {scope}: {issue}", flush=True)


# ────────────────────────────────────────────────────────────────
# 报告落盘：`docs/ir_shadow_diff.json`（同 scope 幂等覆盖）
# ────────────────────────────────────────────────────────────────

def _read_report(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def record_shadow(output_dir: str | Path, scope: str, kind: str,
                  result: Dict[str, Any]) -> Optional[Path]:
    """把一条比对并进报告。写失败不抛：影子比对是旁路，不该拦住生成。"""
    if not output_dir:
        return None
    path = Path(output_dir) / DIFF_REL
    doc = _read_report(path)
    entries = [e for e in (doc.get("scopes") or [])
               if isinstance(e, dict) and e.get("scope") != scope]
    differences = result.get("differences") or []
    entries.append({
        "scope": scope,
        "kind": kind,
        "ok": not differences,
        "fields": list(result.get("fields") or []),
        "differences": differences,
        "ir": result.get("ir") or {},
        # ctx 只留**比对字段**，别把整个 dataclass（含事务字段）灌进报告
        "ctx": result.get("ctx") or {},
    })
    entries.sort(key=lambda e: (str(e.get("kind")), str(e.get("scope"))))
    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scopes": entries,
        "counts": {
            "scopes": len(entries),
            "inconsistent": sum(1 for e in entries if not e.get("ok")),
            "differences": sum(len(e.get("differences") or []) for e in entries),
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError as exc:                      # noqa: BLE001 旁路
        print(f"  [gen_uvm] IR shadow 报告写失败（不影响生成）: {exc}", flush=True)
        return None
    return path


def record_agent(output_dir: str | Path, agent: Any,
                 ctx: Dict[str, Any] = None) -> Optional[Path]:
    return record_shadow(output_dir, f"agent {_attr(agent, 'name', '')}",
                         "agent", agent_diff(agent, ctx))


def record_environment(output_dir: str | Path, env: Any,
                       ctx: Dict[str, Any] = None) -> Optional[Path]:
    return record_shadow(output_dir, f"environment {_attr(env, 'env_name', '')}",
                         "environment", environment_diff(env, ctx))


__all__ = [
    "AGENT_FIELDS", "DIFF_NAME", "DIFF_REL", "ENV_FIELDS", "ENV_FLAG", "SCHEMA",
    "agent_diff", "compare_agent_context", "compare_environment_context",
    "environment_diff", "record_agent", "record_environment", "record_shadow",
    "shadow_enabled", "warn_shadow",
]
