"""SemanticValidator —— 渲染前语义校验层（Phase A）。

目标：把「生成合法但行为错误 / 编译期才暴露」的问题在渲染前拦截，
所有 Issue 汇总后一次性报告（error 阻断生成，warning 不阻断）。

Phase B 约定（持续）：
  新增 YAML schema 特性时，在此登记一条规则（@rule 装饰器）+ 一条测试。
  规则输入 = parse_documents 的产物（纯数据模型），只读、不抛异常。
"""
from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class Issue:
    severity: str   # "error" | "warning"
    rule: str
    target: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.rule} @ {self.target}: {self.message}"


# (kind, rule_id) -> (severity, fn)
_RULES: Dict[Tuple[str, str], Tuple[str, Callable[[Any], List[str]]]] = {}
_RULE_DOCS: List[str] = []


def rule(kind: str, rule_id: str, severity: str, doc: str = ""):
    """规则注册器。kind ∈ {agent, env, bench, harness}。"""
    def deco(fn: Callable[[Any], List[str]]) -> Callable[[Any], List[str]]:
        _RULES[(kind, rule_id)] = (severity, fn)
        _RULE_DOCS.append(f"- `{rule_id}` ({severity}): {doc}")
        return fn
    return deco


# ════════════════════════════════════════════════════════════
# agent（interface）级规则
# ════════════════════════════════════════════════════════════

@rule("agent", "param_width_undefined", "error",
      "端口 width 引用的参数未在 parameters 中定义")
def _param_width_undefined(agent) -> List[str]:
    params = {p.get("name") for p in (agent.parameters or []) if isinstance(p, dict)}
    msgs = []
    for port in agent.ports or []:
        if not isinstance(port, dict):
            continue
        w = port.get("width")
        if isinstance(w, str) and not w.isdigit() and w not in params:
            msgs.append(f"port '{port.get('name')}' width references "
                        f"undefined parameter '{w}'")
    return msgs


@rule("agent", "port_dup_name", "error", "端口重名")
def _port_dup_name(agent) -> List[str]:
    names = [p.get("name") for p in (agent.ports or []) if isinstance(p, dict)]
    return [f"port '{n}' declared more than once"
            for n in set(names) if names.count(n) > 1]


@rule("agent", "txn_var_dup_name", "error", "事务字段重名")
def _txn_var_dup_name(agent) -> List[str]:
    names = [v.get("name") for v in (agent.transaction_vars or []) if isinstance(v, dict)]
    return [f"transaction var '{n}' declared more than once"
            for n in set(names) if names.count(n) > 1]


@rule("agent", "txn_var_port_mismatch", "warning",
      "事务字段没有同名端口（driver/monitor 模板静默跳过，该字段不被驱动/采样）")
def _txn_var_port_mismatch(agent) -> List[str]:
    port_names = {p.get("name") for p in (agent.ports or []) if isinstance(p, dict)}
    return [f"transaction var '{v.get('name')}' has no matching port"
            for v in (agent.transaction_vars or [])
            if isinstance(v, dict) and v.get("name") not in port_names]


# ── typedefs：类型别名（YAML 为 list，归一化后是保序 名字→类型 映射）──
#
# 只查「同一个 map 内部」的顺序问题（视野完整，不会误报）。
# 刻意不查「这个名字在别处有没有定义」—— 校验器看不到 common_typedefs_pkg、
# uvm_pkg、手写包、其它 VIP 的类型，那个视野天生残缺，查了必然误伤。


def _sv_identifiers(text: str) -> List[str]:
    """从类型表达式里抽出标识符，仅用于识别「对其它名字的引用」。

    先剥掉 struct / enum 的成员体（{...}）与尺寸字面量（8'hFF 里的 hFF），
    否则成员名会被当成类型引用而误报。
    """
    t = re.sub(r"\{[^}]*\}", " ", text or "")
    return re.findall(r"(?<!')[A-Za-z_][A-Za-z0-9_$]*", t)


@rule("agent", "typedef_forward_ref", "error",
      "typedef 引用了同一 typedefs 映射里「后面才声明」的名字 —— YAML 顺序即声明顺序，"
      "写反了生成的 pkg 里该名字尚未声明，编译不过")
def _typedef_forward_ref(agent) -> List[str]:
    td = getattr(agent, "typedefs", None) or {}
    if not isinstance(td, dict):
        return []
    order = {name: i for i, name in enumerate(td.keys())}
    msgs = []
    for i, (name, ty) in enumerate(td.items()):
        for ref in _sv_identifiers(str(ty)):
            j = order.get(ref)
            if j is not None and j > i:
                msgs.append(f"typedef '{name}' references '{ref}', which is declared "
                            f"later — 把 '{ref}' 移到 '{name}' 之前")
    return msgs


@rule("agent", "typedef_self_ref", "error",
      "typedef 的类型引用了它自己（无限递归，编译不过）")
def _typedef_self_ref(agent) -> List[str]:
    td = getattr(agent, "typedefs", None) or {}
    if not isinstance(td, dict):
        return []
    return [f"typedef '{name}' references itself"
            for name, ty in td.items()
            if name in _sv_identifiers(str(ty))]


# 协议控制端口（由协议默认驱动/采样逻辑直接处理，不要求有事务字段）
PROTOCOL_CONTROL_PORTS = {
    "apb": {"psel", "penable", "pready"},
}


@rule("agent", "protocol_apb_ports_missing", "error",
      "protocol=apb 时默认时序依赖这些端口（缺失则默认驱动/采样不成立）")
def _protocol_apb_ports_missing(agent) -> List[str]:
    if str(getattr(agent, "protocol", "")).lower() != "apb":
        return []
    required = {"psel", "penable", "pready", "paddr", "pwrite", "pwdata", "prdata"}
    have = {p.get("name") for p in (agent.ports or []) if isinstance(p, dict)}
    return [f"protocol=apb requires port '{p}'" for p in sorted(required - have)]


@rule("agent", "port_not_in_txn", "warning",
      "端口没有对应事务字段（默认驱动/采样逻辑不处理该端口；控制类端口属正常）")
def _port_not_in_txn(agent) -> List[str]:
    txn_names = {v.get("name") for v in (agent.transaction_vars or []) if isinstance(v, dict)}
    exempt = PROTOCOL_CONTROL_PORTS.get(str(getattr(agent, "protocol", "")).lower(), set())
    return [f"port '{p.get('name')}' not covered by any transaction var"
            for p in (agent.ports or [])
            if isinstance(p, dict) and p.get("name") not in txn_names
            and p.get("name") not in exempt]


# ════════════════════════════════════════════════════════════
# env 级规则
# ════════════════════════════════════════════════════════════

@rule("env", "analysis_port_dup_name", "error",
      "analysis_exports/analysis_ports 重名（生成同名成员，SV 编译失败）")
def _analysis_port_dup_name(env) -> List[str]:
    names = [p.get("name") for p in (env.analysis_exports or []) if isinstance(p, dict)]
    names += [p.get("name") for p in (env.analysis_ports or []) if isinstance(p, dict)]
    return [f"analysis port/export '{n}' declared more than once"
            for n in set(names) if names.count(n) > 1]


@rule("env", "tlm_connection_unknown_ref", "warning",
      "tlm_connections 引用了不存在的 agent/组件名（连接将悬空）")
def _tlm_connection_unknown_ref(env) -> List[str]:
    known = {a.name for a in env.agents or []}
    # env 模板自动生成的分析口（environment.sv.j2: `{agent}_agent_ap`），合法引用目标
    known |= {f"{a.name}_agent_ap" for a in env.agents or []}
    known |= {c.get("name") for c in (env.analysis_components or []) if isinstance(c, dict)}
    known |= {s.get("name") for s in (env.scoreboards or []) if isinstance(s, dict)}
    known |= {s.get("name") for s in (env.subenvs or []) if isinstance(s, dict)}
    msgs = []
    for conn in env.tlm_connections or []:
        if not isinstance(conn, dict):
            continue
        for side in ("driver", "receiver"):
            ref = conn.get(side, "")
            head = str(ref).split(".")[0]
            if head and head not in known:
                msgs.append(f"tlm_connections.{side} '{ref}' references unknown '{head}'")
    return msgs


@rule("env", "register_model_bus_unmatched", "warning",
      "register_model bus 条目的 type/bus_name 未匹配到任何 env agent（回退第一个 agent）")
def _register_model_bus_unmatched(env) -> List[str]:
    rm = env.register_model or {}
    if rm.get("bus_entry_seen") and not rm.get("bus_matched"):
        return [f"register_model bus entry did not match any of "
                f"{[a.name for a in env.agents] or '[]'}"]
    return []


@rule("env", "harness_connect_path_missing", "error",
      "harness_connect 存在但缺少 path（set_vifs 调用无法渲染）")
def _harness_connect_path_missing(env) -> List[str]:
    hc = env.harness_connect or {}
    if hc and not hc.get("path"):
        return ["harness_connect present but 'path' is empty"]
    return []


@rule("env", "coverage_cross_unknown", "error",
      "coverage_crosses 引用的字段不在第一个 agent 的 transaction_vars 中")
def _coverage_cross_unknown(env) -> List[str]:
    crosses = env.coverage_crosses or []
    if not crosses or not env.agents:
        return []
    first = next((a for a in env.agents
                  if getattr(a, "transaction_vars", None)), None)
    if first is None:
        return []
    fields = {v.get("name") for v in (getattr(first, "transaction_vars", []) or [])
              if isinstance(v, dict)}
    msgs = []
    for cross in crosses:
        for f in cross:
            if f not in fields:
                msgs.append(f"coverage_crosses 字段 '{f}' 不在 agent '{first.name}' "
                            f"的 transaction_vars 中")
    return msgs


# ════════════════════════════════════════════════════════════
# bench 级规则
# ════════════════════════════════════════════════════════════

def _bench_allowed_signals(bench) -> set:
    allowed = {w.get("name") for w in (bench.wire_decls or []) if isinstance(w, dict)}
    clk_rst = bench.clk_rst or {}
    allowed |= {c.get("name") for c in (clk_rst.get("clocks") or []) if isinstance(c, dict)}
    allowed |= {r.get("name") for r in (clk_rst.get("resets") or []) if isinstance(r, dict)}
    allowed |= {a.get("lhs") for a in (bench.assignments or []) if isinstance(a, dict)}
    return allowed


@rule("bench", "agent_wire_undefined", "error",
      "classic 风格 agent 连接的信号未声明（仅无 harness 时检查）")
def _agent_wire_undefined(bench) -> List[str]:
    if bench.harness:
        return []
    allowed = _bench_allowed_signals(bench)
    msgs = []
    for agent in (bench.agents or {}).values():
        for conn in getattr(agent, "connections", []) or []:
            if isinstance(conn, dict) and conn.get("wire") not in allowed:
                msgs.append(f"agent '{agent.name}' connects to undeclared signal "
                            f"'{conn.get('wire')}'")
    return msgs


# ════════════════════════════════════════════════════════════
# harness 级规则
# ════════════════════════════════════════════════════════════

@rule("harness", "bind_to_missing", "error",
      "harness 缺少 bind_to（bind 语句无法生成）")
def _bind_to_missing(harness) -> List[str]:
    if not harness.bind_to:
        return ["harness 'bind_to' (target module) is empty"]
    return []


@rule("harness", "if_empty_connections", "warning",
      "harness interface 条目没有 connections（bind 端口映射为空）")
def _if_empty_connections(harness) -> List[str]:
    return [f"interface '{i.get('name')}' has no connections"
            for i in (harness.interfaces or []) if isinstance(i, dict) and not i.get("connections")]


# ════════════════════════════════════════════════════════════
# constraint 级规则（多端口事务组合场景）
# ════════════════════════════════════════════════════════════

# 内置策略名（env_cons_policies.sv.j2 中有默认 apply 逻辑的分支）
BUILTIN_POLICIES = {
    "precision_consistency", "mem_capacity", "data_dependency", "boundary_overflow",
    "concurrent_access", "power_performance", "compute_mode", "apb_addr_align",
}


@rule("constraint", "txn_dup_name", "error", "constraint transactions 重名")
def _cons_txn_dup(model) -> List[str]:
    names = [t.get("name") for t in (model.transactions or []) if isinstance(t, dict)]
    return [f"transaction '{n}' declared more than once"
            for n in set(names) if names.count(n) > 1]


@rule("constraint", "policy_dup_name", "error", "constraint policies 重名")
def _cons_policy_dup(model) -> List[str]:
    names = [p.get("name") for p in (model.policies or []) if isinstance(p, dict)]
    return [f"policy '{n}' declared more than once"
            for n in set(names) if names.count(n) > 1]


@rule("constraint", "policy_applies_to_unknown", "error",
      "policy.applies_to 引用不存在的 transaction（多端口组合时端口名必须出现在 transactions 表）")
def _cons_applies_to(model) -> List[str]:
    txn = {t.get("name") for t in (model.transactions or []) if isinstance(t, dict)}
    msgs = []
    for p in (model.policies or []):
        if not isinstance(p, dict):
            continue
        for t in (p.get("applies_to") or []):
            if t not in txn:
                msgs.append(f"policy '{p.get('name')}' applies_to unknown transaction '{t}'")
    return msgs


@rule("constraint", "policy_unknown_name", "warning",
      "policy.name 不在内置分支列表（生成空 apply 骨架，需手填协议逻辑）")
def _cons_policy_unknown(model) -> List[str]:
    # **有 `assignments` 的策略不是空骨架**：`build_constraint` 已经把模型里
    # 可驱动维度的取值编译成了 `apply()` 里的真实赋值，模板会渲染那个分支。
    # 只对"既不在内置表、也没有赋值"的策略告警。
    return [f"policy '{p.get('name')}' has no built-in apply body（自定义逻辑需手填）"
            for p in (model.policies or [])
            if isinstance(p, dict) and p.get("name") not in BUILTIN_POLICIES
            and not p.get("assignments")]


# ════════════════════════════════════════════════════════════
# 校验入口
# ════════════════════════════════════════════════════════════

class SemanticValidator:
    """渲染前语义校验。输入 parse_documents 产物，输出 Issue 列表（不抛异常）。"""

    @staticmethod
    def validate(parsed: Dict[str, Any]) -> List[Issue]:
        issues: List[Issue] = []
        for kind, key in (("agent", "interfaces"), ("env", "environments"),
                          ("bench", "benches"), ("harness", "harnesses"),
                          ("constraint", "constraints")):
            for model in parsed.get(key, []) or []:
                target = getattr(model, "name", "?")
                for (rk, rid), (severity, fn) in _RULES.items():
                    if rk != kind:
                        continue
                    for msg in fn(model):
                        issues.append(Issue(severity, rid, target, msg))
        return issues

    @staticmethod
    def rules_doc() -> str:
        return "\n".join(_RULE_DOCS)
