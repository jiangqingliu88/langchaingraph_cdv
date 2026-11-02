# Harness 功能设计文档

> 版本: v1.0 | 日期: 2026-08-11 | 状态: 设计阶段

---

## 一、什么是 Harness

在 IC 验证中，**Harness（测试台架）** 是连接 DUT 与 UVM 验证环境的顶层桥梁。它的职责是：

```
┌─────────────────────────────────────────────────────────┐
│                     Harness (tb_top)                     │
│                                                         │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Clock    │    │              │    │              │  │
│  │ Generator │───▶│   DUT        │◀───│  Interface   │  │
│  └──────────┘    │  (RTL)       │    │  Instances   │  │
│                  └──────────────┘    └──────┬───────┘  │
│  ┌──────────┐                               │          │
│  │ Reset    │                               │          │
│  │ Generator │──────────────────────────────┘          │
│  └──────────┘                               │          │
│                                    ┌────────▼────────┐ │
│                                    │  uvm_config_db   │ │
│                                    │  virtual iface   │ │
│                                    └────────┬────────┘ │
│                                             │          │
│  ┌──────────────────────────────────────────▼────────┐ │
│  │              UVM Testbench                        │ │
│  │  (agent.driver → interface → DUT → monitor → sb)  │ │
│  └───────────────────────────────────────────────────┘ │
│                                                         │
│  Controls: timeout, verbosity, wave dump, assertions     │
└─────────────────────────────────────────────────────────┘
```

Harness 决定了一个验证环境能否**正确编译、正确连线、正确仿真**。它是 RTL→UVM 之间的关键胶水层。

---

## 二、现状分析

### 2.1 当前实现 (tb_top.sv.j2)

当前的 harness 由以下组件协作生成：

```
spec/RTl → find_spec_yaml → bench.yaml → tb_top.sv.j2 → {name}_bench_tb_top.sv
                                        → interface.sv.j2 → agent interfaces
                                        → env.yaml → UVM environment
```

**生成链路**：`src/tools/uvm_tools/tool_find_spec_yaml/main.py` 的第 7 步（L404-519）负责：
1. 解析 RTL 模块端口 → 生成 `bench.yaml`
2. 声明 wire → DUT 端口连接
3. 生成 agent interface 连线
4. 输出 `regression.yaml`

**Jinja2 模板**：`src/tools/uvm_tools/tool_uvm/templates/bench_templates/tb_top.sv.j2`

### 2.2 六个关键缺口

| # | 缺口 | 严重度 | 影响 |
|---|------|--------|------|
| 1 | **无 Harness 抽象层** | 🔴 高 | DUT 直接内联在 tb_top 中，无法复用、无法替换（如门级网表替代 RTL） |
| 2 | **无 DUT 连接仿真** | 🔴 高 | `check_loopback` 只跑 agent 自环回，从不仿真 DUT 连接的真实 harness；`check_compile` 只编译不仿真 |
| 3 | **命名不一致** | 🟠 中 | Agent 输出 `{env}_tb_top`，compile.py 期望 `{env}_bench_tb_top`，`bench.yaml` 生成 `{module}_bench` |
| 4 | **Clock/Reset VIP 未使用** | 🟠 中 | `base_pkg/clk_and_rst/` 有完整的 `clk_rst_if`/`clk_driver`/`clk_rst_agent` VIP，但模板硬编码 `always #` |
| 5 | **无 Assertion Binding** | 🟡 低 | `bind_assert.sv.j2` 模板存在但 `BenchModel.include_assertions` 未接入 `tb_top` |
| 6 | **Reset release_delay 硬编码为 0** | 🟡 低 | `bench.yaml` 的 reset `release_delay` 默认 0，无实际复位释放时序 |

### 2.3 命名不一致的根因

```
compile.py:18     top = f"{env_name}_bench_tb_top"     ← 编译目标
gen_uvm.py        bench.name = "{module}_bench"        ← YAML 中的 bench name
tb_top.sv.j2:1    module {{ bench.name }}_tb_top       ← 实际模块名 = {module}_bench_tb_top
agent main.py:135 env.top_module = f"{env_name}_tb_top" ← Agent 上报的名称（少了 _bench）
```

**结论**：模板生成的模块名是 `{module}_bench_tb_top`，与 `compile.py` 一致。Agent 上报的 `_tb_top` 是错的（少了 `_bench` 中缀），但不影响编译。

---

## 三、设计目标

### 3.1 核心目标

| 目标 | 描述 | 优先级 |
|------|------|--------|
| **Harness 作为独立 Tool** | 新增 `tool_harness`，专门生成/验证/仿真 harness | P0 |
| **DUT 连接仿真** | 新增 `check_harness` 工具，编译+仿真 DUT 连接的真实 harness | P0 |
| **配置化 Harness** | 通过 `harness.yaml` 控制所有 harness 行为 | P0 |
| **Clock/Reset VIP 集成** | 可选使用 VIP 替代 `always #` | P1 |
| **命名修正** | 统一所有地方的模块命名规则 | P1 |
| **Assertion Binding** | 自动 bind SVA 模块到 DUT | P2 |
| **Multi-Harness 支持** | 支持 RTL harness / Gate harness / Power harness 切换 | P2 |

### 3.2 非目标

- 不做 GUI 配置界面（CLI only）
- 不做 SystemC harness（仅 SV/UVM）
- 不做 Formal harness（仅仿真 harness）

---

## 四、架构设计

### 4.1 整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                     Pipeline 流程                             │
│                                                              │
│  spec → design → model → rtl → [HARNESS] → UVM → test → ... │
│                                   ↑ 新增                      │
│                                                              │
│  Harness 阶段包含三个子步骤：                                   │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 1. tool_harness_gen    → 生成 harness YAML + tb_top.sv  │ │
│  │ 2. tool_harness_compile → vlog 编译 DUT + harness       │ │
│  │ 3. tool_harness_smoke   → vsim 烟雾测试 (DUT 连接仿真)    │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 目录结构

```
src/tools/harness_tools/                  # 新增 harness 工具集
├── __init__.py
├── tool_harness_gen/
│   ├── __init__.py
│   ├── main.py                           # harness 生成入口
│   ├── harvester.py                      # DUT 端口收割器（从 RTL 提取端口信息）
│   ├── wire_planner.py                   # Wire 规划器（类型/宽度/方向 → wire 声明）
│   ├── harness_yaml.py                   # harness YAML schema + 生成
│   └── schemas/
│       └── harness_schema.yaml           # harness 配置 schema 定义
├── tool_harness_compile/
│   ├── __init__.py
│   └── main.py                           # harness 编译检查
├── tool_harness_smoke/
│   ├── __init__.py
│   └── main.py                           # harness 烟雾仿真
├── tool_harness_bind/
│   ├── __init__.py
│   └── main.py                           # assertion binding 工具
└── templates/
    ├── harness_tb_top.sv.j2              # 增强版 tb_top 模板
    ├── harness_dut_wrapper.sv.j2         # DUT wrapper（可选，支持多 DUT）
    ├── harness_clk_rst.sv.j2             # Clock/Reset 生成模块模板
    └── harness_bind.sv.j2                # Assertion bind 模板
```

### 4.3 数据流

```
                    ┌─────────────┐
                    │  RTL .sv    │  (rtl/*.sv, DUT 模块端口)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  harvester  │  解析 DUT module header
                    │  (端口收割)  │  → ports[], params[], iface_signals[]
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ wire_planner│  规划 wire 声明
                    │  (连线规划)  │  → wire_decls[], clk_rst_spec
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
     ┌────────▼───┐ ┌─────▼──────┐ ┌───▼──────────┐
     │ agent YAMLs │ │ bench YAML │ │ harness YAML │  ← 所有 YAML 汇聚
     │ (已有)      │ │ (已有)     │ │ (新增)       │
     └────────┬───┘ └─────┬──────┘ └───┬──────────┘
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────▼──────┐
                    │ Jinja2      │
                    │ Renderer    │  → harness_tb_top.sv
                    │             │  → harness_dut_wrapper.sv
                    │             │  → harness_bind.sv
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
     ┌────────▼───┐ ┌─────▼──────┐ ┌───▼──────────┐
     │ compile    │ │ smoke sim  │ │ bind check   │
     │ (vlog)     │ │ (vsim)     │ │ (formal)     │
     └────────────┘ └────────────┘ └──────────────┘
```

---

## 五、Harness YAML Schema

### 5.1 `harness.yaml` 完整 schema

```yaml
# harness.yaml — Harness 配置 (新增)
# 路径: output/inputs/yaml/harness/harness.yaml

harness:
  # ── 基本信息 ──
  name: "alu_harness"                    # harness 实例名
  type: "rtl"                            # rtl | gate | power | hybrid
  top_module: "alu_bench_tb_top"         # 顶层模块名（修正命名）

  # ── DUT 配置 ──
  dut:
    module: "alu"                        # DUT module 名
    instance: "u_alu"                    # 例化名
    source: "rtl"                        # rtl | gate_netlist | vpd_model
    parameters:                          # DUT 参数覆盖
      - { name: "DATA_WIDTH", value: "32" }
      - { name: "PIPE_STAGES", value: "3" }
    ports:                               # 端口连接 (port → wire)
      - { name: "clk",      connection: "clk" }
      - { name: "rst_n",    connection: "rst_n" }
      - { name: "op_a",     connection: "op_a" }
      - { name: "op_b",     connection: "op_b" }
      - { name: "result",   connection: "result" }

  # ── 多 DUT 支持 (SoC 场景) ──
  # duts:
  #   - { module: "cpu_core",  instance: "u_core",  ... }
  #   - { module: "cache_l2",  instance: "u_cache", ... }

  # ── Clock 生成配置 ──
  clocks:
    - name: "clk"
      period: "10ns"                     # 支持 ns/ps/Hz
      duty_cycle: 50                     # 占空比 %
      init: 0                            # 初始值
      source: "generated"                # generated | external | vip
      # vip 模式下使用 clk_rst_agent
      vip_config: null                   # null = always block; {agent: clk_rst_agent} = VIP

  # ── Reset 生成配置 ──
  resets:
    - name: "rst_n"
      active: "low"                      # low | high
      init: 0                            # 初始值
      release_delay: "100ns"             # 复位释放延迟
      source: "generated"                # generated | external | vip

  # ── Wire 声明 ──
  wires:
    - { name: "op_a",     width: 32 }
    - { name: "op_b",     width: 32 }
    - { name: "result",   width: 32 }

  # ── Interface 实例化 ──
  interfaces:
    - agent: "alu_in"
      interface: "alu_in_interface"
      instance: "alu_in_if"
      clock: "clk"
      reset: "rst_n"
      config_db_path: "*.env.alu_in_agent"
      connections:                       # interface.port → wire
        - { port: "clk",   wire: "clk" }
        - { port: "rst_n", wire: "rst_n" }
        - { port: "data",  wire: "op_a" }
        - { port: "valid", wire: "valid_in" }

  # ── UVM 配置 ──
  uvm_config:
    verbosity: "UVM_MEDIUM"              # UVM_NONE | UVM_LOW | UVM_MEDIUM | UVM_HIGH | UVM_FULL
    timeout: "10ms"                      # 全局超时
    stop_on_fatal: true                  # fatal 时自动停止

  # ── 波形 dump ──
  wave_dump:
    enabled: true
    format: "FST"                        # FST | VCD | FSDB
    plusargs: "DUMP_WAVES"              # +define+ 控制
    levels: 0                            # 0 = 全部层级
    file_name: "alu_tb_top.fst"

  # ── 仿真控制 ──
  simulation:
    max_runtime: "100ms"                 # 最大运行时间
    stop_on_fatal: true
    seed: 12345                          # 随机种子

  # ── Assertion Binding ──
  assertions:
    enabled: true
    bind_target: "u_alu"                 # bind 目标 DUT 实例
    modules:                             # bind 哪些 SVA 模块
      - "alu_protocol_assertions"
      - "alu_interface_assertions"
    source_dir: "agents/asserts/sva"     # SVA 源文件目录

  # ── Backdoor 访问 ──
  backdoor:
    enabled: false
    paths:                               # UVM HDL path 映射
      - { name: "reg_file",  path: "u_alu.reg_file_mem" }
      - { name: "fifo_mem",  path: "u_alu.fifo.buffer" }
```

### 5.2 与现有 YAML 的关系

```
bench.yaml (已有)    → bench 级别配置 (DUT 例化 + agent 线网)
  ↓ 被替代为
harness.yaml (新增)  → 更完整、更结构化的 harness 配置
  ↓ 向下兼容
bench.yaml 仍可生成，harness.yaml 是超集
```

**迁移策略**：`tool_harness_gen` 可以读取 `bench.yaml` 并升级为 `harness.yaml`，也可以在 `bench.yaml` 不存在时从零生成 `harness.yaml`。

---

## 六、核心组件设计

### 6.1 Harvester — DUT 端口收割器

```python
# src/tools/harness_tools/tool_harness_gen/harvester.py

@dataclass
class DutPort:
    name: str
    direction: str          # input | output | inout
    width: int              # bit width (1 for scalar)
    signed: bool = False
    port_type: str = "data" # data | clock | reset | control | config

@dataclass  
class DutParameter:
    name: str
    value: str              # 保留为字符串 (可能是表达式)
    type: str = "int"

@dataclass
class DutModuleInfo:
    module_name: str
    file_path: str
    ports: List[DutPort]
    parameters: List[DutParameter]
    submodules: List[str]   # 子模块例化名


class Harvester:
    """从 RTL 源码收割 DUT 模块信息"""

    def harvest(self, rtl_dir: Path) -> DutModuleInfo:
        """扫描 rtl/*.sv，返回顶层 DUT 的完整端口/参数信息"""
        ...

    def harvest_all(self, rtl_dir: Path) -> List[DutModuleInfo]:
        """扫描所有模块（用于多 DUT harness）"""
        ...

    @staticmethod
    def classify_port(name: str) -> str:
        """端口分类: clock | reset | data | control"""
        ...
```

**改进**（相比 `find_spec_yaml._parse_rtl_module`）：
- 支持 `logic signed` 类型
- 支持多维数组端口 `[0:7][31:0]`
- 支持 `interface` 类型端口（SystemVerilog interface port）
- 支持 parameter `type` 类型
- 正确解析 parameter 默认值表达式

### 6.2 Wire Planner — 连线规划器

```python
# src/tools/harness_tools/tool_harness_gen/wire_planner.py

@dataclass
class WireDecl:
    name: str
    width: int
    signed: bool = False
    wire_type: str = "wire"    # wire | logic | tri

@dataclass
class Connection:
    """interface port → wire 或 DUT port → wire 的映射"""
    port_name: str
    wire_name: str
    direction: str             # input | output | inout


class WirePlanner:
    """根据 DUT 端口 + agent 接口, 规划所有 wire 声明和连线"""

    def plan(self, dut: DutModuleInfo,
             agents: List[AgentSpec]) -> WirePlan:
        """
        返回:
          - wires: 所有需要声明的 wire
          - dut_connections: DUT.{port} → wire 映射
          - agent_connections: interface.{port} → wire 映射
          - shared_wires: 多 agent 共享的 wire
        """
        ...
```

### 6.3 Harness YAML Generator

```python
# src/tools/harness_tools/tool_harness_gen/harness_yaml.py

class HarnessYamlGenerator:
    """生成完整的 harness.yaml"""

    def generate(self,
                 dut: DutModuleInfo,
                 agents: List[AgentSpec],
                 wire_plan: WirePlan,
                 options: HarnessOptions) -> str:
        """返回 harness YAML 字符串"""
        ...

    def upgrade_from_bench(self, bench_yaml_path: Path) -> str:
        """从旧 bench.yaml 升级为 harness.yaml"""
        ...

    def validate(self, yaml_path: Path) -> Tuple[bool, List[str]]:
        """校验 harness.yaml 的 schema 正确性"""
        ...
```

### 6.4 增强版 tb_top.sv.j2

```jinja2
{#
  harness_tb_top.sv.j2 — 增强版 Testbench Top 模板

  相比 tb_top.sv.j2 的改进:
  1. 支持 clock/reset VIP 模式和 always block 模式切换
  2. 支持独立的 DUT wrapper 例化（可选）
  3. 支持 bind assertion
  4. 支持 backdoor path 定义
  5. 支持多 DUT 例化（SoC）
  6. 统一的命名规范
#}

// ==========================================================================
// Harness: {{ harness.name }}
// Generated by: tool_harness_gen
// DUT: {{ harness.dut.module }} | Agents: {{ harness.interfaces | length }}
// ==========================================================================

`timescale 1ns/1ps
module {{ harness.top_module }};
  import uvm_pkg::*;
  import {{ harness.env_name }}_test_pkg::*;

  // ═══════════════════════════════════════════════════════
  // Clock & Reset Generation
  // ═══════════════════════════════════════════════════════
{%- if harness.use_clk_rst_vip %}
  // ── VIP 模式: 使用 clk_rst_agent ──
  clk_rst_if clk_rst_vif();
  clk_rst_agent #(.CLK_PERIOD_PS({{ harness.clocks[0].period_ps }})) u_clk_rst_agent (
    .vif(clk_rst_vif)
  );
{%- else %}
  // ── 简单模式: always block 生成 ──
{%-   for clk in harness.clocks %}
  reg {{ clk.name }} = {{ clk.init | default(0) }};
{%-   endfor %}
{%-   for rst in harness.resets %}
  reg {{ rst.name }} = {{ rst.init | default(0) }};
{%-   endfor %}
{%-   for clk in harness.clocks %}
  always #{{ clk.half_period }} {{ clk.name }} = ~{{ clk.name }};
{%-   endfor %}
{%- endif %}

  // ═══════════════════════════════════════════════════════
  // Wire Declarations
  // ═══════════════════════════════════════════════════════
{%- for wire in harness.wires %}
{%-   if wire.width > 1 %}
  wire {% if wire.signed %}signed {% endif %}[{{ wire.width - 1 }}:0] {{ wire.name }};
{%-   else %}
  wire {{ wire.name }};
{%-   endif %}
{%- endfor %}

  // ═══════════════════════════════════════════════════════
  // Interface Instances (per UVM agent)
  // ═══════════════════════════════════════════════════════
{%- for iface in harness.interfaces %}
  {{ iface.interface }} {{ iface.instance }} (
{%-   for conn in iface.connections %}
    .{{ conn.port }}({{ conn.wire }}){% if not loop.last %},{% endif %}
{%-   endfor %}
  );
{%- endfor %}

  // ═══════════════════════════════════════════════════════
  // DUT Instantiation
  // ═══════════════════════════════════════════════════════
{%- if harness.dut_wrapper.enabled %}
  // ── 通过 DUT Wrapper 例化 (支持 wrapper 内 bind) ──
  {{ harness.dut_wrapper.module }} #(
{%-   for param in harness.dut.parameters %}
    .{{ param.name }}({{ param.value }}){% if not loop.last %},{% endif %}
{%-   endfor %}
  ) {{ harness.dut.instance }} (
{%-   for port in harness.dut.ports %}
    .{{ port.name }}({{ port.connection }}){% if not loop.last %},{% endif %}
{%-   endfor %}
  );
{%- else %}
  // ── 直接例化 DUT ──
  {{ harness.dut.module }}
{%-   if harness.dut.parameters %}
  #(
{%-     for param in harness.dut.parameters %}
    .{{ param.name }}({{ param.value }}){% if not loop.last %},{% endif %}
{%-     endfor %}
  )
{%-   endif %}
  {{ harness.dut.instance }} (
{%-   for port in harness.dut.ports %}
    .{{ port.name }}({{ port.connection }}){% if not loop.last %},{% endif %}
{%-   endfor %}
  );
{%- endif %}

  // ═══════════════════════════════════════════════════════
  // Assertion Binding
  // ═══════════════════════════════════════════════════════
{%- if harness.assertions.enabled %}
{%-   for sva_mod in harness.assertions.modules %}
  bind {{ harness.assertions.bind_target }} {{ sva_mod }} u_{{ sva_mod }} (.*);
{%-   endfor %}
{%- endif %}

  // ═══════════════════════════════════════════════════════
  // UVM Configuration & Test Launch
  // ═══════════════════════════════════════════════════════
  initial begin
{%- if not harness.use_clk_rst_vip %}
{%-   for rst in harness.resets %}
{%-     set delay_ns = rst.release_delay_ns | default(0) | int %}
{%-     if delay_ns > 0 %}
    #{{ delay_ns }}ns {{ rst.name }} = {{ rst.active_value }};
{%-     else %}
    {{ rst.name }} = {{ rst.active_value }};
{%-     endif %}
{%-   endfor %}
{%- endif %}

    // ── Virtual Interface 注入 ──
{%- for iface in harness.interfaces %}
    uvm_config_db #(virtual {{ iface.interface }})::set(
        null, "{{ iface.config_db_path }}", "vif", {{ iface.instance }}
    );
{%- endfor %}

{%- if harness.backdoor.enabled %}
    // ── Backdoor HDL Path ──
{%-   for bd in harness.backdoor.paths %}
    uvm_config_db #(string)::set(null, "*", "{{ bd.name }}_path", "{{ bd.path }}");
{%-   endfor %}
{%- endif %}

{%- if harness.uvm_config.verbosity %}
    uvm_root::get().set_report_verbosity_level_hier({{ harness.uvm_config.verbosity }});
{%- endif %}
    uvm_root::get().set_timeout({{ harness.uvm_config.timeout_ns }}ns);
    run_test();
  end

  // ═══════════════════════════════════════════════════════
  // Waveform Dump
  // ═══════════════════════════════════════════════════════
{%- if harness.wave_dump.enabled %}
  initial begin
    if ($test$plusargs("{{ harness.wave_dump.plusargs }}")) begin
{%-   if harness.wave_dump.format == 'FSDB' %}
      $fsdbDumpfile("{{ harness.wave_dump.file_name }}");
      $fsdbDumpvars({{ harness.wave_dump.levels }}, {{ harness.top_module }});
{%-   elif harness.wave_dump.format == 'VCD' %}
      $dumpfile("{{ harness.wave_dump.file_name }}");
      $dumpvars({{ harness.wave_dump.levels }}, {{ harness.top_module }});
{%-   else %}
      $dumpfile("{{ harness.wave_dump.file_name }}");
      $dumpvars({{ harness.wave_dump.levels }}, {{ harness.top_module }});
{%-   endif %}
    end
  end
{%- endif %}

  // ═══════════════════════════════════════════════════════
  // Simulation Control
  // ═══════════════════════════════════════════════════════
{%- if harness.simulation.max_runtime %}
  initial begin
    #{{ harness.simulation.max_runtime_ns }}ns;
    $display("[HARNESS] SIM_TIMEOUT after {{ harness.simulation.max_runtime }}");
    $finish;
  end
{%- endif %}
{%- if harness.simulation.stop_on_fatal %}
  initial begin
    forever begin
      @(uvm_report_fatal);
      #100ns;
      $display("[HARNESS] Stopping on UVM_FATAL");
      $finish;
    end
  end
{%- endif %}

endmodule : {{ harness.top_module }}
```

---

## 七、Pipeline 集成

### 7.1 新增 Harness Phase

在 `execution.py` 的 `FULL_PHASES` 中，`rtl` 和 `UVM` 之间插入 `harness`：

```python
# execution.py FULL_PHASES 修改

FULL_PHASES = [
    # 前端设计
    ("spec",    "spec",          "spec",        False),
    ("design",  "design",         "design_arch", False),
    ("model",   "model",          "model",       False),
    ("rtl",     "rtl",            "rtl",         False),
    # → 新增 harness 阶段 ←
    ("harness", "harness",        "harness",     False),  # ← NEW
    ("ifspec",  None,             None,          True),
    ("rtlsign", None,             None,          True),
    # 功能验证
    ("vplan",   None,             None,          True),
    ("tpoint",  None,             None,          True),
    ("rtm",     None,             None,          True),
    ("UVM",     "uvm",            "env",         False),
    ...
]
```

### 7.2 Harness 工具注册

```python
# src/agents/harness/main.py — Harness Agent (新增)

from src.core.base import BaseAgent
from src.core.registry import register_agent

@register_agent("harness")
class HarnessAgent(BaseAgent):
    """Harness 生成 Agent — 确定性为主，LLM 仅做配置审查"""

    role = "harness"
    display_name = "Harness 生成器"
    task_type = "code_generation"
    consumes = ["rtl", "design_arch"]       # 依赖 RTL + 设计架构
    produces = "harness"                     # 产出 harness 配置
    min_score = 70
    max_retries = 1

    async def initialize(self):
        # 注册三个确定性 tool
        self.tools = [
            "tool_harness_gen",        # 生成 harness
            "tool_harness_compile",    # 编译检查
            "tool_harness_smoke",      # 烟雾仿真
        ]
        await super().initialize()

    # execute_task 直接调用 tool_harness_gen 确定性生成
    # LLM 仅在质量检查阶段介入（审查连线正确性）
```

### 7.3 执行流程

```
rtl phase 完成 → rtl/*.sv 存在
  ↓
harness phase:
  1. Tool: tool_harness_gen
     - Harvester 收割 DUT 端口
     - WirePlanner 规划连线
     - 生成 harness.yaml + harness_tb_top.sv
  2. Tool: tool_harness_compile (vlog)
     - 编译 DUT + interfaces + harness_tb_top
     - 返回 PASS/FAIL + 编译日志
  3. Tool: tool_harness_smoke (vsim)
     - 用 base_test 跑一次烟雾仿真
     - 检查 DUT 是否正确连线 (信号不悬空、interface 握手正常)
  4. LLM 审查 (可选, refine 模式)
     - 读取 harness.yaml + 编译/sim log
     - 确认连线配置无遗漏
  ↓
harness phase 完成 → harness.yaml + harness_tb_top.sv + compile/smoke PASS
  ↓
UVM phase 开始 (env 生成)
```

---

## 八、CLI 命令设计

```bash
# ===== Harness 生成 =====
vagent harness generate [--from-rtl <dir>] [--output <dir>]
  --from-rtl       RTL 源码目录 (默认 output/rtl/)
  --output         输出目录 (默认自动)
  --dut <name>     指定顶层 DUT 模块名 (默认自动检测)
  --type <type>    rtl | gate | power (默认 rtl)
  --use-vip        使用 clock/reset VIP 替代 always block
  --bind-assert    自动绑定断言模块

# ===== Harness 编译检查 =====
vagent harness compile [--config <harness.yaml>]
  --config         harness YAML 路径
  --simulator      questa | vcs | xcelium (默认 questa)
  --verbose        显示完整编译输出

# ===== Harness 烟雾仿真 =====
vagent harness smoke [--config <harness.yaml>] [--test <test_name>]
  --config         harness YAML 路径
  --test           UVM test 名称 (默认 base_test)
  --timeout        超时时间 (默认 100ms)
  --waves          开启波形 dump

# ===== Harness 验证 (compile + smoke 一键) =====
vagent harness validate [--config <harness.yaml>]
  # 等价于: harness compile && harness smoke

# ===== Harness 断言绑定 =====
vagent harness bind [--config <harness.yaml>] [--sva-dir <dir>]
  --config         harness YAML 路径
  --sva-dir        SVA 源文件目录 (默认 agents/asserts/sva/)
  --list           列出可用的 SVA 模块
```

---

## 九、命名规范统一

### 9.1 命名规则

```
Module naming convention (全局统一):

  DUT module:           {design_name}                e.g. alu
  DUT instance:         u_{design_name}              e.g. u_alu
  DUT wrapper:          {design_name}_wrapper        e.g. alu_wrapper   (可选)
  Interface:            {agent_name}_interface       e.g. alu_in_interface
  Env name:             {design_name}_env            e.g. alu_env
  Bench name:           {design_name}_bench          e.g. alu_bench
  Harness top module:   {design_name}_bench_tb_top   e.g. alu_bench_tb_top  ← 统一这个

修正点:
  旧: agent 上报 env.top_module = f"{env_name}_tb_top"  →  "..._bench_tb_top"
  旧: YAML bench.name = "{module}_bench"               →  不变，正确
  旧: compile.py top = f"{env_name}_bench_tb_top"      →  不变，正确
```

### 9.2 向后兼容

```python
# 兼容映射: 查找 tb_top 时同时尝试新旧命名
TOP_MODULE_CANDIDATES = [
    f"{design_name}_bench_tb_top",   # 新规范
    f"{env_name}_tb_top",            # 旧格式 (agent 上报)
    f"{env_name}_bench_tb_top",      # compile.py 格式
]
```

---

## 十、实施路线图

### Phase 1: 核心 Harness 工具 (P0, 预计 3-5 天)

```
□ Week 1
  ├── tool_harness_gen/main.py        # harness YAML + tb_top 生成
  ├── tool_harness_gen/harvester.py   # DUT 端口收割器
  ├── tool_harness_gen/wire_planner.py # Wire 规划器
  ├── tool_harness_gen/harness_yaml.py # Harness YAML 生成器
  ├── templates/harness_tb_top.sv.j2  # 增强版模板
  └── tool_harness_compile/main.py    # harness 编译检查

□ Week 2
  ├── tool_harness_smoke/main.py      # harness 烟雾仿真
  ├── Harness 工具注册 + Agent 集成
  ├── Pipeline 集成 (harness phase)
  └── CLI 命令 (vagent harness *)
```

### Phase 2: 质量增强 (P1, 预计 2-3 天)

```
□ Week 3
  ├── Clock/Reset VIP 集成
  ├── 命名规范统一 (全链路)
  ├── check_compile 接入 harness smoke
  └── regression.yaml 接入 harness top
```

### Phase 3: 高级特性 (P2, 预计 3-5 天)

```
□ Week 4-5
  ├── tool_harness_bind/main.py       # Assertion binding
  ├── templates/harness_dut_wrapper.sv.j2  # DUT Wrapper
  ├── Multi-DUT harness 支持
  ├── Gate-level harness 支持
  └── harness.yaml → bench.yaml 降级兼容
```

---

## 十一、与现有代码的改动清单

### 11.1 新增文件

```
src/tools/harness_tools/               # 全新目录
src/tools/harness_tools/__init__.py
src/tools/harness_tools/tool_harness_gen/__init__.py
src/tools/harness_tools/tool_harness_gen/main.py
src/tools/harness_tools/tool_harness_gen/harvester.py
src/tools/harness_tools/tool_harness_gen/wire_planner.py
src/tools/harness_tools/tool_harness_gen/harness_yaml.py
src/tools/harness_tools/tool_harness_gen/schemas/harness_schema.yaml
src/tools/harness_tools/tool_harness_compile/__init__.py
src/tools/harness_tools/tool_harness_compile/main.py
src/tools/harness_tools/tool_harness_smoke/__init__.py
src/tools/harness_tools/tool_harness_smoke/main.py
src/tools/harness_tools/tool_harness_bind/__init__.py
src/tools/harness_tools/tool_harness_bind/main.py
src/tools/harness_tools/templates/harness_tb_top.sv.j2
src/tools/harness_tools/templates/harness_dut_wrapper.sv.j2
src/tools/harness_tools/templates/harness_clk_rst.sv.j2
src/tools/harness_tools/templates/harness_bind.sv.j2
src/agents/harness/__init__.py        # 新增 harness agent
src/agents/harness/main.py
```

### 11.2 修改文件

```
src/core/execution.py                  # FULL_PHASES 插入 harness phase
src/tools/lib/compile.py               # 统一 top module 命名逻辑
src/tools/lib/filelist.py              # 支持 harness 文件列表
src/tools/lib/loopback.py              # 新增 harness smoke 检查
src/tools/uvm_tools/agent_tools.py     # 注册 harness 工具
src/agents/uvm/main.py                 # 修正 top_module 命名
src/cli/commands.py                    # 新增 vagent harness 命令组
config/agent_config.yaml               # 添加 harness agent 配置
```

### 11.3 不改动文件

```
src/tools/uvm_tools/tool_uvm/templates/bench_templates/tb_top.sv.j2
  → 保留旧模板作为 fallback，新 harness 模板独立存在

src/tools/uvm_tools/tool_find_spec_yaml/main.py
  → 保留 bench YAML 生成逻辑，harness 工具作为增强替代
```

---

## 十二、成功标准

| # | 标准 | 验证方式 |
|---|------|----------|
| 1 | `vagent harness generate` 能对任何 RTL 模块生成可编译的 harness | 用 3 个不同复杂度的 DUT 测试 |
| 2 | `vagent harness compile` 返回 PASS，编译日志 0 error | CI 集成 |
| 3 | `vagent harness smoke` 能跑完一次 base_test 仿真，DUT 信号不悬空 | vsim log 检查 |
| 4 | pipeline 中 `harness` phase 在 `rtl` 之后 `UVM` 之前正确执行 | 端到端测试 |
| 5 | 命名统一：agent、compile、regression 三处 top module 名一致 | grep 检查 |
| 6 | 旧 `tb_top.sv.j2` 模板仍然可用（向后兼容） | 回归测试 |

---

## 附录 A：Harness 与其他工具的对比

| 工具 | 类型 | Harness 能力 | 与本设计的差异 |
|------|------|-------------|---------------|
| **Synopsys VCS** | 商业 | `vcs -gen_harness` 自动生成 | 黑盒，不可定制；不支持多 simulator |
| **Cadence Xcelium** | 商业 | `xrun -harness` | 同上 |
| **Verilator** | 开源 | `verilator --harness` 生成 C++ harness | 仅 C++/SC，不做 UVM harness |
| **SignOffAI (本设计)** | 开源/个人 | `vagent harness generate` | 白盒、可定制、支持 UVM、支持多 simulator |

## 附录 B：术语表

| 术语 | 含义 |
|------|------|
| **Harness** | 测试台架，连接 DUT 与验证环境的顶层模块 |
| **tb_top** | Testbench Top，UVM 验证环境的最顶层 SystemVerilog module |
| **DUT Wrapper** | DUT 封装层，在 DUT 外层包裹一级，方便 bind/force/replace |
| **VIP** | Verification IP，可复用的验证组件（此处指 clock/reset VIP） |
| **bind** | SystemVerilog bind 语句，将 assertion 模块绑定到 DUT 层级 |
| **config_db** | UVM 配置数据库，用于传递 virtual interface 等共享资源 |
| **烟雾测试 (Smoke Test)** | 最小化的基础测试，验证环境能正确启动和运行 |
| **Wire Plan** | 线网规划，确定所有 wire 的声明和连接关系 |
