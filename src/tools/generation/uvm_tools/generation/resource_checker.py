"""Resource checker 的**生成计划**（适配器，不重算策略）。

输入是 verify 已经落盘的两份构建物：

    coverage/resource_model.json     资源 / 操作 / 访问（含 agent + watch 表达式）
    coverage/resource_scenarios.json 编译后的交互规则（conflict / requires_checker）

输出一份渲染计划给 `resource_checker.sv.j2`。**没有 `agent` / `watch` 的操作
不生成观测点**（不猜事务字段名），unsupported 如实返回给调用方记录。

依赖方向：这里只读 JSON 产物与 AgentModel 的形状，不 import layers。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _attr(obj: Any, name: str, default: Any = "") -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _agent_row(agent: Any) -> Dict[str, str]:
    return {"name": str(_attr(agent, "name", "")),
            "seq_item_type": str(_attr(agent, "seq_item_type", ""))}


def _operations(model: Dict[str, Any],
                agents: Dict[str, Dict[str, str]]) -> tuple:
    operations: List[Dict[str, Any]] = []
    index: Dict[str, int] = {}
    unsupported: List[Dict[str, str]] = []
    for op in model.get("operations") or []:
        if not isinstance(op, dict):
            continue
        oid = str(op.get("id") or op.get("operation_id") or "")
        agent = str(op.get("agent") or "")
        watch = op.get("watch") or {}
        if not oid:
            continue
        if agent not in agents:
            unsupported.append({"operation": oid, "agent": agent,
                                "reason": "agent 未在环境声明（无法观测）"})
            continue
        if not (watch.get("address") and watch.get("length")):
            unsupported.append({"operation": oid, "agent": agent,
                                "reason": "缺 watch.address / watch.length"})
            continue
        index[oid] = len(operations)
        operations.append({
            "index": len(operations), "id": oid, "agent": agent,
            "resource": str(op.get("resource") or op.get("resource_id") or ""),
            "address": str(watch.get("address")),
            "length": str(watch.get("length")),
            "write": str(watch.get("write") or "1'b1"),
        })
    return operations, index, unsupported


def _rules(scenarios: List[Dict[str, Any]],
           index: Dict[str, int]) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    seen = set()
    for sc in scenarios or []:
        ops = [str(o) for o in (sc.get("operations") or [])]
        if len(ops) != 2 or ops[0] not in index or ops[1] not in index:
            continue
        a, b = index[ops[0]], index[ops[1]]
        if a == b:
            continue                       # 同一操作与自身比较没有语义
        # 顺序无关：I1(a,b) 与 I2(b,a) 是同一条规则，避免每次访问报两遍。
        key = (min(a, b), max(a, b), str(sc.get("resource_id") or ""),
               str(sc.get("policy") or ""), bool(sc.get("conflict")))
        if key in seen:
            continue
        seen.add(key)
        rules.append({
            "a": a, "b": b,
            "interaction": str(sc.get("scenario_id") or ""),
            "policy": str(sc.get("policy") or ""),
            "resource": str(sc.get("resource_id") or ""),
            "conflict": bool(sc.get("conflict")),
            "requires_checker": bool(sc.get("requires_checker")),
        })
    return rules


def build_checker_plan(output_dir: str | Path, env_name: str,
                       agents: List[Any]) -> Dict[str, Any]:
    """→ `{class_name, window, operations, agents, rules, unsupported}`；不可生成时 `{}`。"""
    root = Path(output_dir)
    model = _read_json(root / "coverage" / "resource_model.json")
    scenarios = _read_json(root / "coverage" / "resource_scenarios.json") \
        .get("scenarios") or []
    # seq_item_type 是 imp 的事务类型；拿不到它就无法生成合法的 analysis imp。
    agent_map = {row["name"]: row for row in map(_agent_row, agents or [])
                 if row["name"] and row["seq_item_type"]}
    if not model.get("operations") or not scenarios or not agent_map:
        return {}
    operations, index, unsupported = _operations(model, agent_map)
    rules = _rules(scenarios, index)
    if not operations or not rules:
        return {}
    used = sorted({op["agent"] for op in operations})
    return {
        "class_name": f"{env_name}_resource_checker",
        "env_name": env_name,
        "window": int(model.get("check_window") or 0),
        "operations": operations,
        "agents": [agent_map[name] for name in used],
        "rules": rules,
        "unsupported": unsupported,
    }


__all__ = ["build_checker_plan"]
