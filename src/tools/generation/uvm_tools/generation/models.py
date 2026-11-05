"""生成层的内部数据形状 —— 不读文件、不依赖 Jinja。

拆分层之后，`parsing` 负责把 YAML/spec 变成这些 dataclass，`generators`
只编排它们，`render` 只接收 ctx。这样测试可以分别断言：
    YAML → dataclass（parsing）
    dataclass → ctx（generators）
    ctx → 字符串（render）
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Artifact:
    """一个待落盘产物。"""
    name: str
    section: str                 # inputs / env / coverage / regression / verdict
    path: str                    # 相对 run 目录
    required_keys: List[str] = field(default_factory=list)


@dataclass
class RegressionCase:
    name: str
    test: str = ""
    build: str = ""
    seeds_base: int = 0
    seeds_count: int = 1
    modes: List[str] = field(default_factory=list)
    plusargs: List[str] = field(default_factory=list)
    backend_args: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    stage: str = ""


@dataclass
class CoveragePlanSpec:
    module: str
    coverpoints: List[Dict[str, Any]] = field(default_factory=list)
    crosses: List[Dict[str, Any]] = field(default_factory=list)
    batches: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class ConstraintSpec:
    module: str
    policies: List[Dict[str, Any]] = field(default_factory=list)
    transactions: List[Dict[str, str]] = field(default_factory=list)
    backing: Optional[Dict[str, Any]] = None


@dataclass
class EnvSpec:
    module: str
    agents: List[Dict[str, Any]] = field(default_factory=list)
    tests: List[Dict[str, Any]] = field(default_factory=list)
    batches: List[Dict[str, Any]] = field(default_factory=list)
    util_components: List[Dict[str, Any]] = field(default_factory=list)
    output_root: Optional[Path] = None

    def to_uvm_ir(self):
        """映射到统一 UVM IR（不渲染、不写文件；见 `generation/ir/`）。"""
        from .ir.uvm_ir import build_uvm_ir
        return build_uvm_ir(self)


# ── UVM 生成器的输入/输出数据形状（自 tool_uvm/gen_uvm.py 原样搬入）──
@dataclass
class AgentModel:
    name: str
    agent_name: str
    interface: str
    interface_name: str
    clock: Optional[str] = None
    reset: Optional[str] = None
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    # typedefs: 名字 → 类型（如 byte_t: "bit [7:0]"），渲染进 <name>_typedefs_pkg。
    # 用映射而非 list[{name,type}]：类型定义天然是「一个名字对一个类型」。
    typedefs: Dict[str, str] = field(default_factory=dict)
    ports: List[Dict[str, Any]] = field(default_factory=list)
    # master/slave 共用的事务字段/约束 → 渲染进 <name>_base_seq_item，两侧 seq_item 继承它。
    # 与 transaction_vars 的分工：这里放「两侧都有」的（如 addr/data），
    # transaction_vars 放按 is_master 划分给各侧的（如 paddr/prdata）。
    base_transaction_vars: List[Dict[str, Any]] = field(default_factory=list)
    base_transaction_constraints: List[Dict[str, Any]] = field(default_factory=list)
    transaction_vars: List[Dict[str, Any]] = field(default_factory=list)
    transaction_constraints: List[Dict[str, Any]] = field(default_factory=list)
    config_vars: List[Dict[str, Any]] = field(default_factory=list)
    config_constraints: List[Dict[str, Any]] = field(default_factory=list)
    response_info: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    agent_type: str = ""   # 从 YAML "type" 映射（如 "mem"）
    # 协议名（如 "apb"）→ 模板渲染协议正确的默认驱动/采样时序；空 = 通用单拍
    protocol: str = ""
    # 复位极性（P0-2 复位门控用）：True = 低有效（如 presetn），缺省 True
    reset_active_low: bool = True
    # env 级 agents 列表项的角色标记（interface 级不用）：
    is_master: Optional[bool] = None  # True=master 实例 / False=slave 实例 / None=未指定
    active: Optional[bool] = None     # 该实例 is_active（None → 模板走缺省 ACTIVE）
    # 注：pragma custom 区域不再从 YAML 回填（custom_code 已下线）——
    # 区域留空由模板默认值兜底，手改内容用 -m/--merge_source 保留。

    def __post_init__(self) -> None:
        # 注：interface 级不再提供 is_active —— 激活模式由 env 级 agents[].is_active
        # （→ AgentModel.active，见 _normalize_agents_list）决定；loopback 套件固定拓扑。
        if not self.interface:
            self.interface = self.name
        # Normalize: strip _interface suffix (may come from env/bench YAML)
        if self.interface.endswith("_interface"):
            self.interface = self.interface[:-len("_interface")]
        if not self.reset:
            self.reset = "rst"
        # agent_type：YAML "type" 映射为 agent 类名（如 "apb_master_agent"），
        # 缺省 = "{name}_agent"（兼容旧 dict 格式）
        if not self.agent_type:
            self.agent_type = f"{self.name}_agent"
        for var in self.transaction_vars:
            var.setdefault("iscompare", "False")
            var.setdefault("isrand", "False")
            # is_master: "True" → master 字段（master 驱动/生成）；
            #            "False" → slave 字段（slave 响应/生成）
            var.setdefault("is_master", "True")
        # base_transaction_vars 是两侧共用的，不参与 master/slave 划分（is_master 无意义），
        # 只补齐 iscompare/isrand 两个 flag 供 field_macros 统一处理。
        for var in self.base_transaction_vars:
            var.setdefault("iscompare", "False")
            var.setdefault("isrand", "False")
        # transaction_constraints 归一化为 dict：{master: [...], slave: [...]}
        # 兼容旧 list 格式（全部归入 master）
        if isinstance(self.transaction_constraints, list):
            self.transaction_constraints = {"master": self.transaction_constraints, "slave": []}
        elif not isinstance(self.transaction_constraints, dict):
            self.transaction_constraints = {"master": [], "slave": []}
        self.transaction_constraints.setdefault("master", [])
        self.transaction_constraints.setdefault("slave", [])

    def to_context(self) -> Dict[str, Any]:
        # pragma custom 区域内容不再来自 YAML（custom_code 已下线）；asdict 即完整上下文
        return asdict(self)

    def to_uvm_ir(self):
        """映射到统一 UVM IR 的单 agent 形状（渲染前结构校验用）。"""
        from .ir.uvm_ir import build_agent_ir
        return build_agent_ir(self)

    # ── 派生类型名（env 层用）：从 agent_type（类名）推导 seq_item/config 类型 ──
    # 例：agent_type="apb_master_agent" → base="apb_master" →
    #     seq_item_type="apb_master_seq_item" / config_type="apb_master_config"
    @property
    def base_name(self) -> str:
        t = self.agent_type or self.name
        return t[:-len("_agent")] if t.endswith("_agent") else t

    @property
    def seq_item_type(self) -> str:
        return f"{self.base_name}_seq_item"

    @property
    def config_type(self) -> str:
        # 单类 port_config：env 级 agent 在 parse_documents 后处理中
        # 关联到 interface 级 agent 时覆盖为 "<interface_agent>_port_config"
        override = getattr(self, "_config_type_override", "")
        if override:
            return override
        return f"{self.base_name}_config"

    @property
    def sequence_type(self) -> str:
        return f"{self.base_name}_sequence"


class AgentCollection(list):
    def items(self):
        return [(agent.name, agent) for agent in self]


@dataclass
class EnvironmentModel:
    name: str
    env_name: str
    agents: AgentCollection = field(default_factory=AgentCollection)
    subenvs: List[Dict[str, Any]] = field(default_factory=list)
    vipenvs: List[Dict[str, Any]] = field(default_factory=list)
    scoreboards: List[Dict[str, Any]] = field(default_factory=list)
    analysis_components: List[Dict[str, Any]] = field(default_factory=list)
    analysis_exports: List[Dict[str, Any]] = field(default_factory=list)
    analysis_ports: List[Dict[str, Any]] = field(default_factory=list)
    clk_rst_vip: Dict[str, Any] = field(default_factory=dict)
    register_model: Dict[str, Any] = field(default_factory=dict)
    # 可选：测试侧 harness 连接 {path: 层级路径, env_suffix: ".sub_env0"}
    harness_connect: Dict[str, str] = field(default_factory=dict)
    # 语义 cross（P1-2）：[[字段A, 字段B], ...] → env_cov 生成 cross coverpoint
    coverage_crosses: List[List[str]] = field(default_factory=list)
    config_vars: List[Dict[str, Any]] = field(default_factory=list)
    config_constraints: List[Dict[str, Any]] = field(default_factory=list)
    tlm_connections: List[Dict[str, Any]] = field(default_factory=list)
    bench: Dict[str, Any] = field(default_factory=dict)
    #: 工具组件（predictor 等）。它们是**裸 class**，env_pkg 只能 `include`
    #: 进来（import 不了不在包里的东西）—— 而 env / env_config 里会声明
    #: 这些类型的成员，所以 include 要排在它们之前。
    utils: List[Dict[str, Any]] = field(default_factory=list)
    # 属性测试：**一条 = 一个 UVM_TEST = 一个属性取值**（维度×取值）。
    # 内容由 YAML environment.tests 归一化而来（_normalize_tests）；
    # 渲染在 test_attr.sv.j2，为空时不产那个文件。
    tests: List[Dict[str, Any]] = field(default_factory=list)
    # 批次测试：**一条 = 一个 UVM_TEST = 一个批次/专题**。
    # 内容由 YAML environment.batches 归一化而来（_normalize_batches）；
    # 渲染在 test_batch.sv.j2，为空时不产那个文件。
    #
    # 与 `tests` 是**两条平行的路**：那边一条一个属性取值，这边一条一个批次。
    batches: List[Dict[str, Any]] = field(default_factory=list)
    #: **本次运行有没有约束模型** —— 决定 env_pkg 是否 include `cons/*`、
    #: 以及 `gen_test` 是否在 `batch_policy` 非空时启动协调序列。
    #:
    #: 以前 `env/cons/*` **生成了但从未被 include**：约束层是一整包孤立的
    #: SV 文件，连编译都没进过，"策略空壳"之外还有一半是"根本没人执行"。
    #: 这个标记把两件事接上；由 `UVMGenerator.run()` 在渲染环境**之前**回填
    #: （约束 yaml 的 env 名也是那时才知道的）。
    has_constraints: bool = False

    def to_context(self) -> Dict[str, Any]:
        context = asdict(self)
        context["agents"] = self.agents
        return context

    def to_uvm_ir(self):
        """映射到统一 UVM IR（不渲染、不写文件；见 `generation/ir/`）。"""
        from .ir.uvm_ir import build_uvm_ir
        return build_uvm_ir(self)


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
class ScPredPoint:
    """Sc_pred 检查点或产生点"""
    point_name: str
    width: int
    channel_num: int
    ports: List[Dict[str, Any]] = field(default_factory=list)

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScPredModel:
    """Scoreboard Predictor（监控器 + 产生器 + 环境类）"""
    name: str
    id: str = "0"
    prod_points: List[ScPredPoint] = field(default_factory=list)
    chck_points: List[ScPredPoint] = field(default_factory=list)

    def to_context(self) -> Dict[str, Any]:
        ctx = {
            "sc_pred": {
                "name": self.name,
                "id": self.id,
                "prod_points": [p.to_context() for p in self.prod_points],
                "chck_points": [p.to_context() for p in self.chck_points],
            }
        }
        return ctx


@dataclass
class HarnessModel:
    """bind 式 UVM harness（dummy interface + set_vifs + bind 到 DUT module）。

    各 interface 分别 bind 到目标 module（按 module 名，所有实例生效）；
    set_vifs 用向上查找（{{ bind_to }}.{{ source_path }}.{{ name }}）。
    """
    name: str                       # dummy interface 名（如 math_coprocessor_harness）
    bind_to: str = ""               # bind 目标 module 名（所有实例生效）
    parameter: str = ""             # 可选：harness 参数化（值取 module 同名 parameter）
    interfaces: List[Dict[str, Any]] = field(default_factory=list)
    sub_harnesses: List[Dict[str, Any]] = field(default_factory=list)
    connect_path: str = ""          # 可选：测试侧调用路径（如 "harness.U_X.harness"）

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


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
    agent_type: str = ""   # 从 YAML "type" 映射（如 "mem"）

    def __post_init__(self) -> None:
        if not self.instance:
            self.instance = f"{self.interface}_if"
        if not self.config_db_path:
            self.config_db_path = f"*{self.name}_agent_h*"
        if not self.agent_type:
            self.agent_type = f"{self.name}_agent"

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
    # 可选：bind 式 harness（存在时 tb_top 跳过接口实例化与 config_db set，
    # 由 harness.set_vifs() 在测试侧接管 vif 配置；DUT 实例化由 harness.bind_to 推导）
    harness: Dict[str, Any] = field(default_factory=dict)
    dut_instance: str = "u_dut"     # DUT **实例名**
    #: DUT **模块名**（tb_top 例化用）。
    #:
    #: 与 `dut_instance` 是两回事：一个是 `apb_slave_dut`，一个是 `u_dut`。
    #: 以前模块名只存在于 `harness.bind_to` 里 —— harness 一撤就没地方放了，
    #: 于是 tb_top 例化不出 DUT。现在它是 bench 自己的一等字段。
    dut_module: str = ""
    #: 要例化进 tb_top 的接口实例（替代 harness 的 bind 式自连接）。
    #: 每项：{name, type_name, clock, reset, agent_path, ports}
    #: tb_top 据此例化接口、按**同名端口**直连 DUT、再把 vif set 到 agent 路径。
    interfaces: List[Dict[str, Any]] = field(default_factory=list)
    #: DUT / 寄存器模型的源文件 —— 编译清单要收它们
    dut_filelist: List[str] = field(default_factory=list)
    ral_filelist: List[str] = field(default_factory=list)
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
