#!/usr/bin/env python3
"""gen_uvm.py
Generate UVM SystemVerilog from YAML interface and environment descriptions.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: PyYAML is required. Install with: pip install pyyaml"
    ) from exc

try:
    from jinja2 import Environment, FileSystemLoader, pass_context
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: Jinja2 is required. Install with: pip install jinja2"
    ) from exc

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

INTERFACE_TEMPLATES = [
    ("interface_templates/interface.sv.j2", "{agent_name}_interface.sv"),
    ("interface_templates/interface_structure.j2", "{agent_name}_interface_structure.sv"),
    ("interface_templates/transaction.sv.j2", "{agent_name}_transaction.sv"),
    ("interface_templates/sequencer.sv.j2", "{agent_name}_sequencer.sv"),
    ("interface_templates/monitor.sv.j2", "{agent_name}_monitor.sv"),
    ("interface_templates/driver.sv.j2", "{agent_name}_driver.sv"),
    ("interface_templates/config.sv.j2", "{agent_name}_config.sv"),
    ("interface_templates/agent.sv.j2", "{agent_name}_agent.sv"),
    ("interface_templates/agent_pkg.sv.j2", "{agent_name}_pkg.sv"),
    ("interface_templates/agent_sequence_base.sv.j2", "{agent_name}_base_seq.sv"),
    ("interface_templates/agent_cov.sv.j2", "{agent_name}_coverage_collector.sv"),
]

# Agent 自闭环测试套件（独立编译运行的 LB test）
AGENT_LOOPBACK_TEMPLATES = [
    ("interface_templates/agent_loopback_env.sv.j2",  "{agent_name}_loopback_env.sv"),
    ("interface_templates/agent_loopback_scb.sv.j2",  "{agent_name}_loopback_scb.sv"),
    ("interface_templates/agent_loopback_test.sv.j2", "{agent_name}_loopback_test.sv"),
    ("interface_templates/agent_loopback_tb.sv.j2",  "{agent_name}_loopback_tb.sv"),
]

ENVIRONMENT_ROOT_TEMPLATES = [
    ("environment_templates/env_config.sv.j2", "{env_name}_config.sv"),
    ("environment_templates/environment.sv.j2", "{env_name}.sv"),
    ("environment_templates/env_pkg.sv.j2", "{env_name}_pkg.sv"),
]

ENVIRONMENT_TEST_TEMPLATES = [
    ("environment_templates/test_templates/test_pkg.sv.j2", "{env_name}_test_pkg.sv"),
    ("environment_templates/test_templates/test_base.sv.j2", "{env_name}_base_test.sv"),
    ("environment_templates/test_templates/test_directed.sv.j2", "{env_name}_direct_test.sv"),
    ("environment_templates/test_templates/test_random.sv.j2", "{env_name}_random_test.sv"),
]

ENVIRONMENT_SEQ_TEMPLATES = [
    ("environment_templates/virtual_sequencer.sv.j2", "{env_name}_virtual_sequencer.sv"),
    ("environment_templates/seq_templates/virtual_sequence_base.sv.j2", "{env_name}_virtual_base_seq.sv"),
    ("environment_templates/seq_templates/seq_pkg.sv.j2", "{env_name}_seq_pkg.sv"),
]

ENV_CONSTRAINT_TEMPLATES = [
    (
        "environment_templates/env_cons_coordinated_sequence.j2",
        "{project_name}_coordinated_sequence.sv",
    ),
    (
        "environment_templates/env_cons_policy_base.sv.j2",
        "{env_name}_constraint_policy.sv",
    ),
    (
        "environment_templates/env_cons_policies.sv.j2",
        "{project_name}_constraint_policies.sv",
    ),
    (
        "environment_templates/env_cons_policy_combinator.j2",
        "{project_name}_policy_combinator.sv",
    ),
    (
        "environment_templates/env_cons_policy_factory.j2",
        "{project_name}_policy_factory.sv",
    ),
]

BENCH_TEMPLATES = [
    ("bench_templates/tb_top.sv.j2", "{bench_name}_tb_top.sv"),
]

CMODEL_TEMPLATES = [
    ("environment_templates/cmodel_predictor.sv.j2", "{module_name}_cmodel_predictor.sv"),
    ("environment_templates/cmodel_dpi.cpp.j2", "{module_name}_dpi_wrapper.cpp"),
]

CALLBACK_FILES = [
    ("{agent_name}_callback_base.sv", """// Callback Base: {agent_name}_callback_base
class {agent_name}_callback_base extends {agent_name}_agent_callback;
  `uvm_object_utils({agent_name}_callback_base)

  function new(string name = "{agent_name}_callback_base");
    super.new(name);
  endfunction

  // 用户可以在此覆盖基础回调方法
endclass : {agent_name}_callback_base
"""),
    ("{agent_name}_callback_example.sv", """// Callback Example: {agent_name}_callback_example
class {agent_name}_callback_example extends {agent_name}_callback_base;
  `uvm_object_utils({agent_name}_callback_example)

  function new(string name = "{agent_name}_callback_example");
    super.new(name);
  endfunction

  // 示例：覆盖 Agent 连接回调
  virtual function void on_agent_connected({agent_name}_agent agent);
    `uvm_info(get_name(), $sformatf("{agent_name} connected: %s", agent.get_full_name()), UVM_LOW)
  endfunction
endclass : {agent_name}_callback_example
"""),
]


@dataclass
class AgentModel:
    name: str
    agent_name: str
    interface: str
    interface_name: str
    clock: Optional[str] = None
    reset: Optional[str] = None
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    hdl_typedefs: List[Dict[str, Any]] = field(default_factory=list)
    hvl_typedefs: List[Dict[str, Any]] = field(default_factory=list)
    ports: List[Dict[str, Any]] = field(default_factory=list)
    transaction_vars: List[Dict[str, Any]] = field(default_factory=list)
    transaction_constraints: List[Dict[str, Any]] = field(default_factory=list)
    config_vars: List[Dict[str, Any]] = field(default_factory=list)
    config_constraints: List[Dict[str, Any]] = field(default_factory=list)
    response_info: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=lambda: {"is_active": "UVM_ACTIVE"})
    # LLM-generated protocol-specific timing logic placeholders
    custom_drive_logic: str = ""   # Injected into driver.sv.j2 {{ custom_drive_logic }}
    custom_sample_logic: str = ""  # Injected into monitor.sv.j2 {{ custom_sample_logic }}

    def __post_init__(self) -> None:
        if not self.interface:
            self.interface = self.name
        # Normalize: strip _interface suffix (may come from env/bench YAML)
        if self.interface.endswith("_interface"):
            self.interface = self.interface[:-len("_interface")]
        if not self.reset:
            self.reset = "rst"
        for var in self.transaction_vars:
            var.setdefault("iscompare", "False")
            var.setdefault("isrand", "False")

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


class AgentCollection(list):
    def items(self):
        return [(agent.name, agent) for agent in self]


@dataclass
class EnvironmentModel:
    name: str
    env_name: str
    agents: AgentCollection = field(default_factory=AgentCollection)
    scoreboards: List[Dict[str, Any]] = field(default_factory=list)
    virtual_sequencer: Dict[str, Any] = field(default_factory=lambda: {"enabled": False})
    clk_rst_vip: Dict[str, Any] = field(default_factory=dict)
    config_vars: List[Dict[str, Any]] = field(default_factory=list)
    config_constraints: List[Dict[str, Any]] = field(default_factory=list)
    tlm_connections: List[Dict[str, Any]] = field(default_factory=list)
    bench: Dict[str, Any] = field(default_factory=dict)

    def to_context(self) -> Dict[str, Any]:
        context = asdict(self)
        context["agents"] = self.agents
        return context

@dataclass
class ConstraintModel:
    name: str
    env_name: str
    transactions: List[Dict[str, Any]] = field(default_factory=list)
    policies: List[Dict[str, Any]] = field(default_factory=list)
    combinator: Dict[str, Any] = field(
        default_factory=lambda: {
            "default_mode": "APPLY_ALL",
            "modes": [
                "APPLY_ALL",
                "APPLY_WEIGHTED",
                "APPLY_FIRST_MATCH",
                "APPLY_SEQUENTIAL",
                "APPLY_CHAIN",
            ],
        }
    )

    def __post_init__(self) -> None:
        self.project = {"name": self.name, "env_name": self.env_name}

    def to_context(self) -> Dict[str, Any]:
        return {
            "project": self.project,
            "transactions": self.transactions,
            "policies": self.policies,
            "combinator": self.combinator,
        }

@dataclass
class WireDecl:
    """Wire declaration in the testbench top."""
    name: str
    width: int = 1

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Assignment:
    """Continuous assignment in the testbench top."""
    lhs: str
    rhs: str

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DutPort:
    """DUT port-to-wire connection."""
    name: str
    connection: str

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DutModel:
    """DUT instantiation information."""
    module: str
    instance: str = ""
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    ports: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.instance:
            self.instance = f"u_{self.module}"

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClkSpec:
    """Clock specification."""
    name: str
    period: str = "10ns"
    init: int = 0

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RstSpec:
    """Reset specification."""
    name: str
    init: int = 0
    release_delay: int = 100

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentConnection:
    """Maps an interface port to a physical wire."""
    port: str
    wire: str

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BenchAgentEntry:
    """Per-agent entry in the bench context — lean, connection-focused."""
    name: str
    interface: str
    clock: str = "clk"
    reset: str = "rst_n"
    instance: str = ""
    config_db_path: str = ""
    connections: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.instance:
            self.instance = f"{self.interface}_if"
        if not self.config_db_path:
            self.config_db_path = f"*{self.name}_agent_h*"

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BenchModel:
    name: str
    env_name: str
    timeout: str = "10ms"
    include_assertions: bool = False
    clk_rst: Dict[str, Any] = field(default_factory=dict)
    wire_decls: List[Dict[str, Any]] = field(default_factory=list)
    assignments: List[Dict[str, Any]] = field(default_factory=list)
    agents: Dict[str, BenchAgentEntry] = field(default_factory=dict)
    dut: Optional[Dict[str, Any]] = None
    uvm_config: Dict[str, Any] = field(default_factory=dict)
    wave_dump: Dict[str, Any] = field(default_factory=dict)
    simulation: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalize agents: convert dict entries to BenchAgentEntry
        if isinstance(self.agents, dict):
            typed: Dict[str, BenchAgentEntry] = {}
            for k, v in self.agents.items():
                if isinstance(v, BenchAgentEntry):
                    typed[k] = v
                elif isinstance(v, dict):
                    typed[k] = BenchAgentEntry(
                        name=v.get("name", k),
                        interface=v.get("interface", k),
                        clock=v.get("clock", "clk"),
                        reset=v.get("reset", "rst_n"),
                        instance=v.get("instance", ""),
                        config_db_path=v.get("config_db_path", ""),
                        connections=v.get("connections", []),
                    )
            self.agents = typed

        # Normalize DUT
        if self.dut is None:
            self.dut = {}
        if isinstance(self.dut, dict) and "instance" not in self.dut:
            self.dut["instance"] = f"u_{self.dut.get('module', 'dut')}"

        # Normalize clk_rst: old-style string lists → dict lists
        clocks = self.clk_rst.get("clocks", [])
        resets = self.clk_rst.get("resets", [])
        self.clk_rst["clocks"] = [
            c if isinstance(c, dict) else {"name": c, "period": "10ns", "init": 0}
            for c in clocks
        ]
        self.clk_rst["resets"] = [
            r if isinstance(r, dict) else {"name": r, "init": 0, "release_delay": 100}
            for r in resets
        ]

    def to_context(self) -> Dict[str, Any]:
        ctx = asdict(self)
        # Convert BenchAgentEntry objects to dicts for Jinja2
        if "agents" in ctx and isinstance(self.agents, dict):
            ctx["agents"] = {
                k: (v.to_context() if isinstance(v, BenchAgentEntry) else v)
                for k, v in self.agents.items()
            }
        return ctx

    def get_agent(self, name: str) -> Optional[BenchAgentEntry]:
        return self.agents.get(name)

    def __repr__(self) -> str:
        return f"BenchModel(name={self.name!r}, env_name={self.env_name!r}, agents={list(self.agents.keys())!r})"

class JinjaRenderer:
    def __init__(self, templates_dir: Path) -> None:
        self.environment = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            keep_trailing_newline=True,
            autoescape=False,
        )
        self.environment.filters["nl2br"] = lambda value: str(value).replace("\n", "\\n")
        self.environment.globals["get_clock_index"] = lambda name, clocks: clocks.index(name) if name in clocks else 0
        self.environment.globals["get_reset_index"] = lambda name, resets: resets.index(name) if name in resets else 0
        self.environment.globals["get_transaction_type"] = self._get_transaction_type

    @staticmethod
    @pass_context
    def _get_transaction_type(context, transaction_name: str) -> str:
        transactions = context.get("transactions", [])
        for transaction in transactions:
            if transaction.get("name") == transaction_name:
                return transaction.get("type", f"{transaction_name}_transaction")
        return f"{transaction_name}_transaction"

    def render(self, template_path: str, context: Dict[str, Any]) -> str:
        template = self.environment.get_template(template_path)
        return template.render(**context)


class RenderTask:
    def __init__(self, renderer: JinjaRenderer, output_dir: Path) -> None:
        self.renderer = renderer
        self.output_dir = output_dir

    def render_file(self, template_path: str, target_path: Path, context: Dict[str, Any]) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = self.renderer.render(template_path, context)
        target_path.write_text(content, encoding="utf-8")
        return target_path


class AgentRenderTask(RenderTask):
    def generate(self, agent: AgentModel) -> List[Path]:
        rendered: List[Path] = []
        base_dir = self.output_dir / "agents" / agent.name
        context = {"agent": agent, **agent.to_context()}
        for template_path, target_pattern in INTERFACE_TEMPLATES:
            target_name = target_pattern.format(agent_name=agent.name)
            target_path = base_dir / target_name
            rendered.append(self.render_file(template_path, target_path, context))

        # Agent 自闭环测试套件
        lb_dir = base_dir / "loopback"
        for template_path, target_pattern in AGENT_LOOPBACK_TEMPLATES:
            target_name = target_pattern.format(agent_name=agent.name)
            target_path = lb_dir / target_name
            rendered.append(self.render_file(template_path, target_path, context))

        for file_name_pattern, template_text in CALLBACK_FILES:
            target_name = file_name_pattern.format(agent_name=agent.name)
            target_path = base_dir / target_name
            if not target_path.exists():
                target_path.write_text(template_text.format(agent_name=agent.name), encoding="utf-8")
                rendered.append(target_path)

        # ── Generate human-readable markdown summary ──
        md_path = _generate_agent_markdown(agent, base_dir)
        rendered.append(md_path)

        return rendered


# ────────────────────────────────────────────────────────────
# Markdown Summary Generation — human-readable agent docs
# ────────────────────────────────────────────────────────────

def _generate_agent_markdown(agent: "AgentModel", base_dir: Path) -> Path:
    """Generate a human-readable summary.md for a single UVM agent."""
    md_path = base_dir / "summary.md"
    lines: List[str] = []

    name = agent.name
    iface = agent.interface_name or agent.interface or name
    clk = agent.clock or "clk"
    rst = agent.reset or "rst"
    is_active = agent.config.get("is_active", "UVM_ACTIVE") if isinstance(agent.config, dict) else str(agent.config)
    mode = "🟢 ACTIVE" if "ACTIVE" in str(is_active) else "🔵 PASSIVE"

    lines.append(f"# Agent: `{name}`")
    lines.append("")
    lines.append("| Property | Value |")
    lines.append("|----------|-------|")
    lines.append(f"| Interface | `{iface}` |")
    lines.append(f"| Clock | `{clk}` |")
    lines.append(f"| Reset | `{rst}` |")
    lines.append(f"| Mode | {mode} |")
    lines.append("")

    # ── Interface Ports ──
    ports = agent.ports
    if ports:
        lines.append("## 📌 Interface Ports")
        lines.append("")
        lines.append("| Dir | Name | Width | Description |")
        lines.append("|-----|------|-------|-------------|")
        for p in ports:
            d = str(p.get("dir", "?"))
            n = str(p.get("name", "?"))
            w_raw = p.get("width", 1)
            if isinstance(w_raw, str):
                w = f"`{w_raw}`"
            elif isinstance(w_raw, int) and w_raw > 1:
                w = f"[{w_raw-1}:0]"
            else:
                w = "1"
            desc = str(p.get("desc", "-"))
            lines.append(f"| {d} | `{n}` | {w} | {desc} |")
        lines.append("")

    # ── Parameters ──
    params = agent.parameters
    if params:
        lines.append("## ⚙️ Parameters")
        lines.append("")
        lines.append("| Parameter | Type | Default |")
        lines.append("|-----------|------|---------|")
        for p in params:
            pn = str(p.get("name", "?"))
            pt = str(p.get("type", "?"))
            pv = str(p.get("value", "-"))
            lines.append(f"| `{pn}` | `{pt}` | `{pv}` |")
        lines.append("")

    # ── HDL Typedefs ──
    hdl_typedefs = agent.hdl_typedefs
    if hdl_typedefs:
        lines.append("## 🏷️ HDL Type Definitions")
        lines.append("")
        for td in hdl_typedefs:
            tn = td.get("name", "?")
            tv = td.get("value", td.get("type", "?"))
            lines.append(f"- `{tn}` = `{tv}`")
        lines.append("")

    # ── HVL Typedefs ──
    hvl_typedefs = agent.hvl_typedefs
    if hvl_typedefs:
        lines.append("## 🏷️ HVL Type Definitions")
        lines.append("")
        for td in hvl_typedefs:
            tn = td.get("name", "?")
            tv = td.get("value", td.get("type", "?"))
            lines.append(f"- `{tn}` = `{tv}`")
        lines.append("")

    # ── Transaction Fields ──
    txn_vars = agent.transaction_vars
    if txn_vars:
        lines.append("## 📦 Transaction (`{name}_seq_item`)".format(name=name))
        lines.append("")
        lines.append("| Field | Type | Compare | Random |")
        lines.append("|-------|------|---------|--------|")
        for v in txn_vars:
            vn = str(v.get("name", "?"))
            vt = str(v.get("type", "?"))
            vc = "✓" if str(v.get("iscompare", "False")).lower() in ("true", "1") else "-"
            vr = "✓" if str(v.get("isrand", "False")).lower() in ("true", "1") else "-"
            lines.append(f"| `{vn}` | `{vt}` | {vc} | {vr} |")
        lines.append("")

    # ── Transaction Constraints ──
    txn_cons = agent.transaction_constraints
    if txn_cons:
        lines.append("### Constraints")
        lines.append("")
        for c in txn_cons:
            cn = c.get("name", "?")
            cv = c.get("value", "?")
            lines.append(f"- **`{cn}`**: `{cv}`")
        lines.append("")

    # ── Configuration Variables ──
    cfg_vars = agent.config_vars
    if cfg_vars:
        lines.append("## 🔧 Configuration (`{name}_config`)".format(name=name))
        lines.append("")
        lines.append("| Variable | Default | Description |")
        lines.append("|----------|---------|-------------|")
        for v in cfg_vars:
            vn = str(v.get("name", "?"))
            vd = str(v.get("default", "-"))
            vdesc = str(v.get("desc", v.get("description", "-")))
            lines.append(f"| `{vn}` | `{vd}` | {vdesc} |")
        lines.append("")

    # ── Response Info ──
    rsp = agent.response_info
    if rsp:
        lines.append("## 📬 Response Info")
        lines.append("")
        for k, val in rsp.items():
            lines.append(f"- **{k}**: `{val}`")
        lines.append("")

    # ── Generated File Inventory ──
    lines.append("## 📁 Generated File Inventory")
    lines.append("")
    lines.append("| # | File | Role |")
    lines.append("|---|------|------|")
    file_entries = [
        (f"{name}_interface.sv", "Physical interface: ports, clocking block, modport"),
        (f"{name}_interface_structure.sv", "Interface structure / typedef definitions"),
        (f"{name}_transaction.sv", "Transaction (sequence item): fields + constraints"),
        (f"{name}_config.sv", "Configuration object"),
        (f"{name}_sequencer.sv", "Sequencer: controls stimulus flow"),
        (f"{name}_driver.sv", "Driver: drives signals on the bus"),
        (f"{name}_monitor.sv", "Monitor: samples signals, collects coverage"),
        (f"{name}_agent.sv", "Top-level agent: instantiates driver/monitor/sequencer"),
        (f"{name}_pkg.sv", "Package: imports all components"),
        (f"{name}_base_seq.sv", "Base sequence template"),
        (f"{name}_coverage_collector.sv", "Functional coverage collector"),
        (f"{name}_callback_base.sv", "Base callback class (extensible)"),
        (f"{name}_callback_example.sv", "Example callback implementation"),
    ]
    for i, (fname, desc) in enumerate(file_entries, 1):
        lines.append(f"| {i} | `{fname}` | {desc} |")
    lines.append("")

    # ── Loopback Self-Test ──
    lines.append("## 🔁 Loopback Self-Test")
    lines.append("")
    lines.append("Self-contained testbench (no DUT required): driver → monitor closed loop.")
    lines.append("")
    lines.append("| File | Role |")
    lines.append("|------|------|")
    lines.append(f"| `loopback/{name}_loopback_env.sv` | Loopback environment: connects driver → scoreboard → monitor |")
    lines.append(f"| `loopback/{name}_loopback_scb.sv` | Scoreboard: compares expected vs actual transactions |")
    lines.append(f"| `loopback/{name}_loopback_test.sv` | Test case: starts sequence, checks results |")
    lines.append(f"| `loopback/{name}_loopback_tb.sv` | Testbench top: instantiates interface + env, generates clock/reset |")
    lines.append("")

    # ── Compile / Sim Quick Reference ──
    lines.append("## 🚀 Quick Start")
    lines.append("")
    lines.append("```bash")
    lines.append(f"# Compile (single agent loopback)")
    lines.append(f"vlog -f inputs/filelists/filelist_{name}_lb.f")
    lines.append("")
    lines.append(f"# Simulate")
    lines.append(f"vsim -c {name}_loopback_tb +UVM_TESTNAME={name}_loopback_test -do 'run -all; quit -f'")
    lines.append("```")
    lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def _generate_output_readme(output_dir: Path, agents: List["AgentModel"],
                            environments: List["EnvironmentModel"] = None,
                            benches: List["BenchModel"] = None) -> Path:
    """Generate an overall README.md at the output root indexing all agents."""
    readme_path = output_dir / "README.md"
    lines: List[str] = []

    lines.append("# UVM Verification Environment — Generated Output")
    lines.append("")
    lines.append(f"**Generated**: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Directory Structure ──
    lines.append("## 📂 Directory Structure")
    lines.append("")
    lines.append("```")
    lines.append("output/")
    lines.append("├── README.md              ← this file")
    if agents:
        lines.append("├── agents/")
        for a in agents:
            lines.append(f"│   ├── {a.name}/")
            lines.append(f"│   │   ├── summary.md     ← agent design summary")
            lines.append(f"│   │   ├── {a.name}_*.sv  ← UVM components")
            lines.append(f"│   │   └── loopback/      ← self-test testbench")
    lines.append("├── env/                    ← environment + tests + sequences")
    lines.append("├── bench/                  ← top-level testbench")
    lines.append("├── inputs/                 ← tool input files")
    lines.append("│   ├── yaml/")
    lines.append("│   │   ├── uvm/            ← UVM agent/env/bench YAML")
    lines.append("│   │   ├── agent_test/     ← agent loopback test YAML")
    lines.append("│   │   └── dut_test/       ← DUT regression test YAML")
    lines.append("│   └── filelists/          ← compile filelists")
    lines.append("├── docs/                   ← pipeline documentation")
    lines.append("├── build/                  ← compiled work library + test work areas")
    lines.append("├── sim/                    ← simulation artifacts")
    lines.append("│   ├── agent/              ← agent loopback logs + waves")
    lines.append("│   └── dut/                ← DUT regression logs + waves")
    lines.append("├── quality_report.json     ← quality check results")
    lines.append("└── sim_*.log / wave_*.wlf  ← simulation artifacts")
    lines.append("```")
    lines.append("")

    # ── Agent Summary Table ──
    if agents:
        lines.append("## 🤖 Agents")
        lines.append("")
        lines.append("| Agent | Interface | Mode | Ports | Transaction Fields | Constraints |")
        lines.append("|-------|-----------|------|-------|--------------------|-------------|")
        for a in agents:
            iface = a.interface_name or a.interface or a.name
            mode = "ACTIVE" if "ACTIVE" in str(a.config.get("is_active", "")) else "PASSIVE"
            n_ports = len(a.ports) if a.ports else 0
            n_txn = len(a.transaction_vars) if a.transaction_vars else 0
            n_cons = len(a.transaction_constraints) if a.transaction_constraints else 0
            lines.append(f"| [{a.name}](agents/{a.name}/summary.md) | `{iface}` | {mode} | {n_ports} | {n_txn} | {n_cons} |")
        lines.append("")

    # ── Per-Agent Detail ──
    if agents:
        lines.append("## 📋 Agent Details")
        lines.append("")
        for a in agents:
            lines.append(f"### [{a.name}](agents/{a.name}/summary.md)")
            lines.append("")
            lines.append(f"- **Interface**: `{a.interface_name or a.interface or a.name}`")
            lines.append(f"- **Clock**: `{a.clock or 'clk'}`  |  **Reset**: `{a.reset or 'rst'}`")
            lines.append(f"- **Mode**: `{a.config.get('is_active', 'UVM_ACTIVE')}`")

            if a.ports:
                port_list = ", ".join(
                    f"`{p.get('name','?')}`({p.get('dir','?')})"
                    for p in a.ports[:8])
                if len(a.ports) > 8:
                    port_list += f" +{len(a.ports) - 8} more"
                lines.append(f"- **Ports**: {port_list}")

            if a.transaction_vars:
                txn_list = ", ".join(
                    f"`{v.get('name','?')}`"
                    for v in a.transaction_vars[:6])
                if len(a.transaction_vars) > 6:
                    txn_list += f" +{len(a.transaction_vars) - 6} more"
                lines.append(f"- **Transaction fields**: {txn_list}")

            if a.transaction_constraints:
                cons_list = ", ".join(
                    f"`{c.get('name','?')}`"
                    for c in a.transaction_constraints[:4])
                lines.append(f"- **Constraints**: {cons_list}")

            lines.append(f"- **Files**: `agents/{a.name}/` (13 .sv + loopback)")
            lines.append("")

    # ── Environment ──
    if environments:
        lines.append("## 🌐 Environment")
        lines.append("")
        for env in environments:
            lines.append(f"- **{env.env_name}** — {len(env.agents) if env.agents else 0} agents")
            if env.scoreboards:
                lines.append(f"  - Scoreboards: {len(env.scoreboards)}")
            if env.tlm_connections:
                lines.append(f"  - TLM connections: {len(env.tlm_connections)}")
            lines.append(f"  - Files: `env/{env.env_name}*.sv`")
        lines.append("")

    # ── Bench ──
    if benches:
        lines.append("## 🔌 Testbench Top")
        lines.append("")
        for b in benches:
            lines.append(f"- **{b.name}** — env: `{b.env_name}`, timeout: `{b.timeout}`")
            if b.dut:
                lines.append(f"  - DUT: `{b.dut.get('module', '?')}` (instance: `{b.dut.get('instance', '?')}`)")
            agents_list = list(b.agents.keys()) if isinstance(b.agents, dict) else []
            if agents_list:
                lines.append(f"  - Agents: {', '.join(agents_list)}")
            lines.append(f"  - File: `bench/{b.name}_tb_top.sv`")
        lines.append("")

    # ── Quality ──
    lines.append("## ✅ Quality Checks")
    lines.append("")
    lines.append("See [`quality_report.json`](quality_report.json) for detailed results:")
    lines.append("")
    lines.append("| Check | What | Pass Criteria |")
    lines.append("|-------|------|---------------|")
    lines.append("| Static | All expected files exist | 0 missing files |")
    lines.append("| Compile | `vlog` passes for agent loopback TB | 0 errors |")
    lines.append("| Loopback | Driver→Monitor closed-loop simulation | matched > 0, 0 UVM_ERROR |")
    lines.append("")

    lines.append("---")
    lines.append("*Generated by SignOffAI UVM Generator*")
    lines.append("")

    readme_path.write_text("\n".join(lines), encoding="utf-8")
    return readme_path


class EnvironmentRenderTask(RenderTask):
    def generate(self, environment: EnvironmentModel) -> List[Path]:
        rendered: List[Path] = []
        env_dir = self.output_dir / "env"
        context = {"environment": environment, **environment.to_context()}

        for template_path, target_pattern in ENVIRONMENT_ROOT_TEMPLATES:
            target_name = target_pattern.format(env_name=environment.env_name)
            target_path = env_dir / target_name
            rendered.append(self.render_file(template_path, target_path, context))

        tests_dir = env_dir / "tests"
        for template_path, target_pattern in ENVIRONMENT_TEST_TEMPLATES:
            target_name = target_pattern.format(env_name=environment.env_name)
            target_path = tests_dir / target_name
            rendered.append(self.render_file(template_path, target_path, context))

        seqs_dir = env_dir / "seqs"
        for template_path, target_pattern in ENVIRONMENT_SEQ_TEMPLATES:
            target_name = target_pattern.format(env_name=environment.env_name)
            target_path = seqs_dir / target_name
            rendered.append(self.render_file(template_path, target_path, context))

        return rendered


class ConstraintRenderTask(RenderTask):
    def generate(self, constraint: ConstraintModel) -> List[Path]:
        rendered: List[Path] = []
        cons_dir = self.output_dir / "env" / "cons"
        context = constraint.to_context()
        for template_path, target_pattern in ENV_CONSTRAINT_TEMPLATES:
            target_name = target_pattern.format(
                project_name=constraint.name,
                env_name=constraint.env_name,
            )
            target_path = cons_dir / target_name
            rendered.append(self.render_file(template_path, target_path, context))
        return rendered


class BenchRenderTask(RenderTask):
    def generate(self, bench: BenchModel) -> Path:
        bench_dir = self.output_dir / "bench"
        target_path = bench_dir / f"{bench.name}_tb_top.sv"
        ctx = {"bench": bench.to_context()}
        # Add agents as a list for easy template iteration
        ctx["agents"] = [
            v.to_context() if isinstance(v, BenchAgentEntry) else v
            for v in bench.agents.values()
        ]
        return self.render_file(BENCH_TEMPLATES[0][0], target_path, ctx)


class RenderTaskFactory:
    @staticmethod
    def create(task_type: str, renderer: JinjaRenderer, output_dir: Path) -> RenderTask:
        if task_type == "agent":
            return AgentRenderTask(renderer, output_dir)
        if task_type == "environment":
            return EnvironmentRenderTask(renderer, output_dir)
        if task_type == "constraint":
            return ConstraintRenderTask(renderer, output_dir)
        if task_type == "bench":
            return BenchRenderTask(renderer, output_dir)
        raise ValueError(f"Unknown task type: {task_type}")


class YAMLLoader:
    SUPPORTED_SUFFIXES = {".yml", ".yaml"}

    @staticmethod
    def collect_paths(inputs: Iterable[Path]) -> List[Path]:
        files: List[Path] = []
        for input_path in inputs:
            if input_path.is_dir():
                for path in sorted(input_path.rglob("*")):
                    if path.suffix.lower() in YAMLLoader.SUPPORTED_SUFFIXES and path.is_file():
                        files.append(path)
            elif input_path.is_file() and input_path.suffix.lower() in YAMLLoader.SUPPORTED_SUFFIXES:
                files.append(input_path)
        return files

    @staticmethod
    def parse_agent_model(data: Dict[str, Any]) -> Optional[AgentModel]:
        if not isinstance(data, dict):
            return None
        name = data.get("name") or data.get("agent_name")
        if not name:
            return None

        return AgentModel(
            name=name,
            agent_name=name,
            interface=data.get("interface", ""),
            interface_name=data.get("interface_name", data.get("interface", "")),
            clock=data.get("clock") or data.get("clk"),
            reset=data.get("reset"),
            parameters=data.get("parameters", []),
            hdl_typedefs=data.get("hdl_typedefs", []),
            hvl_typedefs=data.get("hvl_typedefs", []),
            ports=data.get("ports", []),
            transaction_vars=data.get("transaction_vars", []),
            transaction_constraints=data.get("transaction_constraints", []),
            config_vars=data.get("config_vars", []),
            config_constraints=data.get("config_constraints", []),
            response_info=data.get("response_info", {}),
            config=data.get("config", {"is_active": "UVM_ACTIVE"}),
        )

    @staticmethod
    def parse_environment_model(data: Dict[str, Any]) -> EnvironmentModel:
        name = data.get("name") or data.get("env_name")
        env_name = data.get("env_name") or name
        agents = AgentCollection()
        for agent_name, agent_config in (data.get("agents") or {}).items():
            if not isinstance(agent_config, dict):
                continue
            agent = AgentModel(
                name=agent_name,
                agent_name=agent_name,
                interface=agent_config.get("interface", ""),
                interface_name=agent_config.get("interface", ""),
                clock=agent_config.get("clock"),
                reset=agent_config.get("reset"),
            )
            agents.append(agent)

        clk_rst_vip = data.get("clk_rst_vip") or {}
        if not clk_rst_vip and data.get("clk_rst"):
            clk_rst_vip = {
                "enabled": True,
                "clocks": data["clk_rst"].get("clocks", []),
                "resets": data["clk_rst"].get("resets", []),
            }

        return EnvironmentModel(
            name=name,
            env_name=env_name,
            agents=agents,
            scoreboards=data.get("scoreboards", []),
            virtual_sequencer=data.get("virtual_sequencer", {"enabled": False}),
            clk_rst_vip=clk_rst_vip,
            config_vars=data.get("config_vars", []),
            config_constraints=data.get("config_constraints", []),
            tlm_connections=data.get("tlm_connections", []),
            bench=data.get("bench", {}),
        )

    @staticmethod
    def parse_bench_model(data: Dict[str, Any]) -> BenchModel:
        agents: Dict[str, BenchAgentEntry] = {}
        for name, agent_config in (data.get("agents") or {}).items():
            if not isinstance(agent_config, dict):
                continue
            agents[name] = BenchAgentEntry(
                name=name,
                interface=agent_config.get("interface", ""),
                clock=agent_config.get("clock", "clk"),
                reset=agent_config.get("reset", "rst_n"),
                instance=agent_config.get("instance", ""),
                config_db_path=agent_config.get("config_db_path", ""),
                connections=agent_config.get("connections", []),
            )
        return BenchModel(
            name=data.get("name") or data.get("bench_name", "bench"),
            env_name=data.get("env_name", ""),
            timeout=data.get("timeout", "10ms"),
            include_assertions=data.get("include_assertions", False),
            clk_rst=data.get("clk_rst", {}),
            wire_decls=data.get("wire_decls", []),
            assignments=data.get("assignments", []),
            agents=agents,
            dut=data.get("dut", {}),
            uvm_config=data.get("uvm_config", {}),
            wave_dump=data.get("wave_dump", {}),
            simulation=data.get("simulation", {}),
        )

    @staticmethod
    def parse_constraint_model(data: Dict[str, Any]) -> ConstraintModel:
        project = data.get("constraint") or {}
        name = project.get("name") or project.get("constraint_name") or "constraint"
        env_name = project.get("env_name") or project.get("env") or ""
        return ConstraintModel(
            name=name,
            env_name=env_name,
            transactions=data.get("transactions", []),
            policies=data.get("policies", []),
            combinator=data.get(
                "combinator",
                {
                    "default_mode": "APPLY_ALL",
                    "modes": [
                        "APPLY_ALL",
                        "APPLY_WEIGHTED",
                        "APPLY_FIRST_MATCH",
                        "APPLY_SEQUENTIAL",
                        "APPLY_CHAIN",
                    ],
                },
            ),
        )

    @staticmethod
    def parse_documents(paths: Iterable[Path]) -> Dict[str, Any]:
        interfaces = AgentCollection()
        environments: List[EnvironmentModel] = []
        benches: List[BenchModel] = []
        constraints: List[ConstraintModel] = []
        utils: List[Dict[str, Any]] = []

        for path in paths:
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)

            if not isinstance(data, dict):
                continue

            if "util_components" in data:
                payload = data["util_components"]
                if isinstance(payload, list):
                    utils.extend(payload)
                elif isinstance(payload, dict):
                    utils.append(payload)

            if "interfaces" in data:
                payload = data["interfaces"]
                if isinstance(payload, list):
                    for item in payload:
                        agent = YAMLLoader.parse_agent_model(item)
                        if agent:
                            interfaces.append(agent)
                elif isinstance(payload, dict):
                    agent = YAMLLoader.parse_agent_model(payload)
                    if agent:
                        interfaces.append(agent)

            if "interface" in data:
                payload = data["interface"]
                if isinstance(payload, list):
                    for item in payload:
                        agent = YAMLLoader.parse_agent_model(item)
                        if agent:
                            interfaces.append(agent)
                elif isinstance(payload, dict):
                    agent = YAMLLoader.parse_agent_model(payload)
                    if agent:
                        interfaces.append(agent)

            if "environment" in data:
                payload = data["environment"]
                if isinstance(payload, dict):
                    environments.append(YAMLLoader.parse_environment_model(payload))

            if "bench" in data:
                payload = data["bench"]
                if isinstance(payload, dict):
                    benches.append(YAMLLoader.parse_bench_model(payload))

            if "constraint" in data:
                constraints.append(YAMLLoader.parse_constraint_model(data))

        return {
            "interfaces": interfaces,
            "environments": environments,
            "benches": benches,
            "constraints": constraints,
            "utils": utils,
        }


class UVMGenerator:
    def __init__(self, renderer: JinjaRenderer, output_root: Path) -> None:
        self.renderer = renderer
        self.output_root = output_root

    def generate_agents(self, agents: Iterable[AgentModel]) -> List[Path]:
        task = RenderTaskFactory.create("agent", self.renderer, self.output_root)
        generated: List[Path] = []
        for agent in agents:
            generated.extend(task.generate(agent))
        return generated

    def generate_environments(self, environments: Iterable[EnvironmentModel]) -> List[Path]:
        task = RenderTaskFactory.create("environment", self.renderer, self.output_root)
        generated: List[Path] = []
        for environment in environments:
            generated.extend(task.generate(environment))
        return generated

    def generate_constraints(self, constraints: Iterable[ConstraintModel]) -> List[Path]:
        task = RenderTaskFactory.create("constraint", self.renderer, self.output_root)
        generated: List[Path] = []
        for constraint in constraints:
            generated.extend(task.generate(constraint))
        return generated

    def generate_benches(self, benches: Iterable[BenchModel]) -> List[Path]:
        task = RenderTaskFactory.create("bench", self.renderer, self.output_root)
        generated: List[Path] = []
        for bench in benches:
            generated.extend([task.generate(bench)])
        return generated

    def generate_utils(self, utils: Iterable[Dict[str, Any]]) -> List[Path]:
        """生成工具组件（Predictor 等）"""
        generated: List[Path] = []
        util_dir = self.output_root / "env" / "utils"
        _util_templates = [
            ("environment_templates/util_comp.sv.j2", "{name}_util.sv"),
        ]
        for comp in utils:
            if not isinstance(comp, dict):
                continue
            name = comp.get("name", "util")
            ctx = {
                "name": name,
                "type": comp.get("type", "uvm_component"),
                "description": comp.get("description", ""),
                "analysis_exports": comp.get("analysis_exports", []),
                "analysis_ports": comp.get("analysis_ports", []),
            }
            for tpl_path, target_pattern in _util_templates:
                target_name = target_pattern.format(name=name)
                target_path = util_dir / target_name
                target_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    content = self.renderer.render(tpl_path, ctx)
                    target_path.write_text(content, encoding="utf-8")
                    generated.append(target_path)
                except Exception as e:
                    pass
        return generated

    def run(self, inputs: Iterable[Path]) -> List[Path]:
        yaml_files = YAMLLoader.collect_paths(inputs)
        if not yaml_files:
            raise SystemExit("No YAML files were found in the input paths.")

        data = YAMLLoader.parse_documents(yaml_files)
        interfaces = data["interfaces"]
        environments = data["environments"]
        benches = data["benches"]
        constraints = data["constraints"]
        utils = data["utils"]

        if not interfaces and not environments and not benches and not constraints and not utils:
            raise SystemExit("No supported YAML definitions were found.")

        generated_files: List[Path] = []
        if interfaces:
            generated_files.extend(self.generate_agents(interfaces))
        if environments:
            generated_files.extend(self.generate_environments(environments))
        if benches:
            generated_files.extend(self.generate_benches(benches))
        if constraints:
            generated_files.extend(self.generate_constraints(constraints))
        if utils:
            generated_files.extend(self.generate_utils(utils))

        # ── Generate overall README.md at output root ──
        try:
            readme_path = _generate_output_readme(
                self.output_root,
                list(interfaces) if interfaces else [],
                list(environments) if environments else [],
                list(benches) if benches else [],
            )
            generated_files.append(readme_path)
        except Exception:
            pass  # README is optional, don't fail generation

        return generated_files


# ============================================================
#  Parameterized entry point for LangChain / programmatic use
# ============================================================

SUPPORTED_TOOL_TYPES = ("agent", "env", "bench", "constraint", "util")


def generate_uvm(tool_type: str, yaml_spec: str) -> str:
    """
    参数化 UVM 代码生成器 —— 根据 tool_type 和 YAML 输入生成 SystemVerilog。

    参数:
        tool_type:  类型 —— "agent" | "env" | "bench" | "constraint" | "util"
        yaml_spec:  YAML 规格字符串

    返回:
        生成的文件列表与代码摘要
    """
    if tool_type not in SUPPORTED_TOOL_TYPES:
        return (
            f"// Error: unsupported tool_type '{tool_type}'. "
            f"Supported: {', '.join(SUPPORTED_TOOL_TYPES)}"
        )

    try:
        data = yaml.safe_load(yaml_spec)
    except yaml.YAMLError as e:
        return f"// Error parsing YAML: {e}"

    if not isinstance(data, dict):
        return "// Error: YAML must be a dictionary"

    renderer = JinjaRenderer(TEMPLATES_DIR)

    # ── Agent ──────────────────────────────────────────────
    if tool_type == "agent":
        payload = data.get("interfaces") or data.get("interface")
        if payload is None:
            return "// Error: YAML must contain 'interfaces' or 'interface' key"
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            return "// Error: 'interfaces' must be a list or dict"

        results = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("agent_name")
            if not name:
                continue
            agent = AgentModel(
                name=name, agent_name=name,
                interface=item.get("interface", ""),
                interface_name=item.get("interface_name", item.get("interface", "")),
                clock=item.get("clock") or item.get("clk"),
                reset=item.get("reset"),
                parameters=item.get("parameters", []),
                hdl_typedefs=item.get("hdl_typedefs", []),
                hvl_typedefs=item.get("hvl_typedefs", []),
                ports=item.get("ports", []),
                transaction_vars=item.get("transaction_vars", []),
                transaction_constraints=item.get("transaction_constraints", []),
                config_vars=item.get("config_vars", []),
                config_constraints=item.get("config_constraints", []),
                response_info=item.get("response_info", {}),
                config=item.get("config", {"is_active": "UVM_ACTIVE"}),
            )
            ctx = {"agent": agent, **agent.to_context()}
            files = []
            for tpl, pat in INTERFACE_TEMPLATES:
                try:
                    c = renderer.render(tpl, ctx)
                    files.append(f"  {pat.format(agent_name=name)}: {len(c)} chars")
                except Exception as e:
                    files.append(f"  {pat.format(agent_name=name)}: ERR - {e}")
            results.append(f"Agent: {name}\n" + "\n".join(files))
        return "\n\n".join(results)

    # ── Environment ────────────────────────────────────────
    if tool_type == "env":
        payload = data.get("environment")
        if payload is None or not isinstance(payload, dict):
            return "// Error: YAML must contain 'environment' dict"
        name = payload.get("name") or payload.get("env_name", "env")
        env_name = payload.get("env_name") or name
        agents = AgentCollection()
        for aname, acfg in (payload.get("agents") or {}).items():
            if isinstance(acfg, dict):
                agents.append(AgentModel(
                    name=aname, agent_name=aname,
                    interface=acfg.get("interface", ""),
                    interface_name=acfg.get("interface", ""),
                    clock=acfg.get("clock"), reset=acfg.get("reset"),
                ))
        clk_rst_vip = payload.get("clk_rst_vip") or {}
        if not clk_rst_vip and payload.get("clk_rst"):
            clk_rst_vip = {
                "enabled": True,
                "clocks": payload["clk_rst"].get("clocks", []),
                "resets": payload["clk_rst"].get("resets", []),
            }
        env = EnvironmentModel(
            name=name, env_name=env_name, agents=agents,
            scoreboards=payload.get("scoreboards", []),
            virtual_sequencer=payload.get("virtual_sequencer", {"enabled": False}),
            clk_rst_vip=clk_rst_vip,
            config_vars=payload.get("config_vars", []),
            config_constraints=payload.get("config_constraints", []),
            tlm_connections=payload.get("tlm_connections", []),
            bench=payload.get("bench", {}),
        )
        ctx = {"environment": env, **env.to_context()}
        files = []
        for tpl, pat in (ENVIRONMENT_ROOT_TEMPLATES + ENVIRONMENT_TEST_TEMPLATES + ENVIRONMENT_SEQ_TEMPLATES):
            try:
                c = renderer.render(tpl, ctx)
                files.append(f"  {pat.format(env_name=env_name)}: {len(c)} chars")
            except Exception as e:
                files.append(f"  {pat.format(env_name=env_name)}: ERR - {e}")
        return f"Environment: {env_name}\n" + "\n".join(files)

    # ── Bench ──────────────────────────────────────────────
    if tool_type == "bench":
        payload = data.get("bench")
        if payload is None or not isinstance(payload, dict):
            return "// Error: YAML must contain 'bench' dict"
        agents_b: dict = {}
        for aname, acfg in (payload.get("agents") or {}).items():
            if isinstance(acfg, dict):
                agents_b[aname] = BenchAgentEntry(
                    name=aname,
                    interface=acfg.get("interface", ""),
                    clock=acfg.get("clock", "clk"),
                    reset=acfg.get("reset", "rst_n"),
                    instance=acfg.get("instance", ""),
                    config_db_path=acfg.get("config_db_path", ""),
                    connections=acfg.get("connections", []),
                )
        bench = BenchModel(
            name=payload.get("name") or payload.get("bench_name", "bench"),
            env_name=payload.get("env_name", ""),
            timeout=payload.get("timeout", "10ms"),
            include_assertions=payload.get("include_assertions", False),
            clk_rst=payload.get("clk_rst", {}),
            wire_decls=payload.get("wire_decls", []),
            assignments=payload.get("assignments", []),
            agents=agents_b,
            dut=payload.get("dut", {}),
            uvm_config=payload.get("uvm_config", {}),
            wave_dump=payload.get("wave_dump", {}),
            simulation=payload.get("simulation", {}),
        )
        ctx = {"bench": bench.to_context()}
        tpl = BENCH_TEMPLATES[0][0]
        c = renderer.render(tpl, ctx)
        return f"Bench: {bench.name}\n  {bench.name}_tb_top.sv: {len(c)} chars"

    # ── Constraint ─────────────────────────────────────────
    if tool_type == "constraint":
        proj = data.get("constraint") or {}
        cname = proj.get("name") or proj.get("constraint_name") or "constraint"
        cenv = proj.get("env_name") or proj.get("env") or ""
        constraint = ConstraintModel(
            name=cname, env_name=cenv,
            transactions=data.get("transactions", []),
            policies=data.get("policies", []),
            combinator=data.get("combinator", {
                "default_mode": "APPLY_ALL",
                "modes": ["APPLY_ALL", "APPLY_WEIGHTED", "APPLY_FIRST_MATCH",
                          "APPLY_SEQUENTIAL", "APPLY_CHAIN"],
            }),
        )
        ctx = constraint.to_context()
        files = []
        for tpl, pat in ENV_CONSTRAINT_TEMPLATES:
            try:
                c = renderer.render(tpl, ctx)
                files.append(f"  {pat.format(project_name=cname, env_name=cenv)}: {len(c)} chars")
            except Exception as e:
                files.append(f"  {pat.format(project_name=cname, env_name=cenv)}: ERR - {e}")
        return f"Constraint: {cname}\n" + "\n".join(files)

    # ── Util ───────────────────────────────────────────────
    if tool_type == "util":
        components = data.get("util_components")
        if components is None or not isinstance(components, list):
            return "// Error: YAML must contain 'util_components' list"
        results = []
        _util_templates = [
            ("environment_templates/util_comp.sv.j2", "{name}_util.sv"),
        ]
        for comp in components:
            if not isinstance(comp, dict):
                continue
            uname = comp.get("name", "util")
            ctx = {
                "name": uname,
                "type": comp.get("type", "uvm_component"),
                "description": comp.get("description", ""),
                "analysis_exports": comp.get("analysis_exports", []),
                "analysis_ports": comp.get("analysis_ports", []),
            }
            files = []
            for tpl, pat in _util_templates:
                try:
                    c = renderer.render(tpl, ctx)
                    files.append(f"  {pat.format(name=uname)}: {len(c)} chars")
                except Exception as e:
                    files.append(f"  {pat.format(name=uname)}: ERR - {e}")
            results.append(f"Util: {uname}\n" + "\n".join(files))
        return "\n\n".join(results)

    return f"// Error: unknown tool_type '{tool_type}'"


# ============================================================
#  CLI entry point
# ============================================================

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate UVM SystemVerilog from YAML descriptors."
    )
    parser.add_argument(
        "-i",
        "--input",
        nargs="+",
        default=["."],
        help="Input YAML file(s) or directories containing YAML files.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="generated",
        help="Output root directory for generated UVM files.",
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List the supported Jinja2 templates and exit.",
    )
    args = parser.parse_args(argv)

    if args.list_templates:
        print("Supported template sets:")
        print("  interface_templates:")
        for tpl, _ in INTERFACE_TEMPLATES:
            print(f"    {tpl}")
        print("  environment_root_templates:")
        for tpl, _ in ENVIRONMENT_ROOT_TEMPLATES:
            print(f"    {tpl}")
        print("  environment_test_templates:")
        for tpl, _ in ENVIRONMENT_TEST_TEMPLATES:
            print(f"    {tpl}")
        print("  environment_seq_templates:")
        for tpl, _ in ENVIRONMENT_SEQ_TEMPLATES:
            print(f"    {tpl}")
        print("  env_constraint_templates:")
        for tpl, _ in ENV_CONSTRAINT_TEMPLATES:
            print(f"    {tpl}")
        print("  bench_templates:")
        for tpl, _ in BENCH_TEMPLATES:
            print(f"    {tpl}")
        return 0

    input_paths = [Path(x).expanduser() for x in args.input]
    output_root = Path(args.output).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    renderer = JinjaRenderer(TEMPLATES_DIR)
    generator = UVMGenerator(renderer, output_root)

    generated_files = generator.run(input_paths)

    print(f"Generated {len(generated_files)} file(s) into: {output_root}")
    for path in generated_files:
        print(f"  {path.relative_to(output_root)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
