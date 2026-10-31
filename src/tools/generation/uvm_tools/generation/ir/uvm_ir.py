"""UVM IR 契约 + 校验。

只做三件事：把 `EnvSpec` 的已有字段映射成稳定形状、做结构校验、给出可序列化
视图。**不生成代码**（渲染仍在 `render/` / `gen_uvm.py`），因此引入它不会改变
现有产物字节。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

SCHEMA = "uvm_ir_v1"


@dataclass
class UVMPortIR:
    name: str
    direction: str = ""            # input | output | inout
    width: Any = 1
    protocol: str = ""
    clock: str = ""
    reset: str = ""


@dataclass
class UVMAgentIR:
    name: str
    agent_type: str = "UVM_ACTIVE"
    interface: str = ""
    ports: List[UVMPortIR] = field(default_factory=list)
    sequence_item: str = ""
    driver: str = ""
    monitor: str = ""


@dataclass
class UVMSequenceIR:
    name: str
    agent: str = ""
    item: str = ""
    steps: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class UVMTestIR:
    name: str
    sequence: str = ""
    agents: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    plusargs: List[str] = field(default_factory=list)


@dataclass
class UVMConnectionIR:
    source_agent: str
    source_port: str
    target_agent: str
    target_port: str


@dataclass
class UVMEnvIR:
    name: str
    agents: List[str] = field(default_factory=list)
    scoreboard: str = ""
    coverage: str = ""


@dataclass
class UVMIR:
    module: str
    env: UVMEnvIR
    agents: List[UVMAgentIR] = field(default_factory=list)
    tests: List[UVMTestIR] = field(default_factory=list)
    sequences: List[UVMSequenceIR] = field(default_factory=list)
    connections: List[UVMConnectionIR] = field(default_factory=list)
    schema: str = SCHEMA

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def agent(self, name: str) -> Optional[UVMAgentIR]:
        return next((a for a in self.agents if a.name == name), None)


def _agent_dict(item: Any) -> Dict[str, Any]:
    """`find_spec_yaml` 的 agents 可能是 dict，也可能是 (agent, meta) 元组。"""
    if isinstance(item, dict):
        return item
    if isinstance(item, (tuple, list)) and item and isinstance(item[0], dict):
        return item[0]
    return {}


def _ports(raw: Any) -> List[UVMPortIR]:
    out: List[UVMPortIR] = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        out.append(UVMPortIR(
            name=str(p.get("name") or ""),
            direction=str(p.get("direction") or ""),
            width=p.get("width", 1),
            protocol=str(p.get("protocol") or p.get("proto") or ""),
            clock=str(p.get("clock") or ""),
            reset=str(p.get("reset") or ""),
        ))
    return out


def _build_agents(raw_agents: Iterable[Any]) -> List[UVMAgentIR]:
    agents: List[UVMAgentIR] = []
    for item in raw_agents:
        doc = _agent_dict(item)
        if not doc.get("name"):
            continue
        agents.append(UVMAgentIR(
            name=str(doc["name"]),
            agent_type=str(doc.get("type") or doc.get("agent_type") or "UVM_ACTIVE"),
            interface=str(doc.get("interface") or doc.get("iface") or ""),
            ports=_ports(doc.get("ports")),
            sequence_item=str(doc.get("sequence_item") or ""),
            driver=str(doc.get("driver") or ""),
            monitor=str(doc.get("monitor") or ""),
        ))
    return agents


def _as_names(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    return [str(v) for v in (value or [])]


def _build_tests(raw_tests: Iterable[Any]) -> List[UVMTestIR]:
    tests: List[UVMTestIR] = []
    for t in raw_tests:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        tests.append(UVMTestIR(
            name=str(t["name"]),
            sequence=str(t.get("sequence") or t.get("seq") or ""),
            agents=_as_names(t.get("agents") or t.get("agent") or []),
            tags=_as_names(t.get("tags") or []),
            plusargs=_as_names(t.get("plusargs") or []),
        ))
    return tests


def build_uvm_ir(env_spec: Any) -> UVMIR:
    """`EnvSpec`（或同形状 dict）→ UVMIR。**不做解析，只做映射**。"""
    module = str(getattr(env_spec, "module", "") or "")
    agents = _build_agents(getattr(env_spec, "agents", []) or [])
    tests = _build_tests(getattr(env_spec, "tests", []) or [])
    env = UVMEnvIR(name=f"{module}_env" if module else "env",
                   agents=[a.name for a in agents])
    return UVMIR(module=module, env=env, agents=agents, tests=tests)


def validate_ir(ir: UVMIR) -> List[Dict[str, str]]:
    """结构校验 —— 只报确定性错误，不猜协议/不补端口。"""
    issues: List[Dict[str, str]] = []

    def _add(code: str, message: str) -> None:
        issues.append({"code": code, "message": message})

    if not ir.module:
        _add("module_missing", "UVMIR.module 为空")
    names = [a.name for a in ir.agents]
    if not names:
        _add("agent_missing", "环境没有任何 agent")
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        _add("agent_duplicate", f"agent 重名: {sorted(dup)}")
    for agent in ir.agents:
        if not agent.ports:
            _add("agent_ports_missing", f"agent {agent.name!r} 没有端口")
        for port in agent.ports:
            if not port.name:
                _add("port_name_missing", f"agent {agent.name!r} 有空端口名")
            if port.direction not in ("input", "output", "inout", ""):
                _add("port_direction_invalid",
                     f"agent {agent.name!r} 端口 {port.name!r} 方向 "
                     f"{port.direction!r} 非法")
    known = set(names)
    for test in ir.tests:
        missing = [a for a in test.agents if a not in known]
        if missing:
            _add("test_agent_unknown",
                 f"test {test.name!r} 引用了不存在的 agent {missing}")
    for conn in ir.connections:
        for side, agent, port in (
                ("source", conn.source_agent, conn.source_port),
                ("target", conn.target_agent, conn.target_port)):
            if agent not in known:
                _add("connection_agent_unknown",
                     f"connection {side} agent {agent!r} 不存在")
                continue
            a = ir.agent(agent)
            if a and port and port not in {p.name for p in a.ports}:
                _add("connection_port_unknown",
                     f"connection {side} 端口 {port!r} 不在 agent {agent!r} 上")
    return issues
