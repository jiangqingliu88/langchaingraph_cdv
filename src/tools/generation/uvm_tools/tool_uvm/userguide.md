# tool_uvm 用户指南（User Guide）

从 YAML 描述符生成完整 UVM SystemVerilog 验证环境。本指南按「场景」组织：
每个场景给出目标、YAML 要点、命令、预期产物。CLI 参数速查见文末表格。

> 依赖：Python 3.10 ~ 3.12、pyyaml、jinja2、jsonschema。
> 完整字段说明见 [readme.md](readme.md)，示例在 `examples/`（APB 全链路）。

## 重要变更

### 本轮（新增，向后兼容）

`environment.tests:` —— 一条 = 一个 UVM_TEST = 一个属性取值，属性经
`uvm_config_db#(int)` 传进环境。**不写它时产物与今天逐字节一致**（不产
`_attr_test.sv`）。见场景 16。

### 本轮（破坏性，旧 YAML 需同步）

| 项 | 旧 | 新 |
|---|---|---|
| `typedefs` | `- { type, name }` 列表 | **list，每项 `{ type_t: 类型, type_name: 新名 }`** |
| `hdl_typedefs` / `hvl_typedefs` | interface 级两个键 | **已下线**，统一走 `typedefs` |
| env `agents[]` / `subenvs[]` 类名 | 由 `interface` + `is_master` 拼 `{iface}_{master\|slave}_agent` | **读 YAML 显式写的 `type`** |
| env 顶层 `virtual_sequencer:` | 一个 `enabled` 开关 | **已下线**（该开关从未被任何模板读取） |
| bench 时钟复位 | `clk_rst:` | **`clk_rst_if:`**（旧名仍兼容） |
| 参数包 / 类型包 | `<name>_parameter_pkg` | **`<name>_parameters_pkg` / `<name>_typedefs_pkg`** |

### 已下线的键（写它会直接报 `unknown_property` 阻断生成）

| 已下线 | 位置 | 替代 / 原因 |
|---|---|---|
| `interface:` | **interface 文档**里（与 `name` 冗余，曾因此漂出 `isnt_disp` 拼写错误） | 删掉即可，自动取 `name` |
| `env_name:` | env / bench / constraint 顶层 | 无（生成前缀一律取 `name`；bench 的 env 名由 `environment` 自动回填，constraint 改用 `env`） |
| `predictors:` | env 顶层 | 无（该机制从未被 env 模板例化，只产出孤立文件） |
| `virtual_sequencer:` | env 顶层 | 无（vsqr 恒定生成，删掉行为不变） |
| `mode:` / `expected_from:` / `actual_from:` / `key_field:` / `item_type:` | env `scoreboards[]` | 无（生成式计分板已下线）；改用 `sb_type` 指向具名类 |
| `hdl_typedefs:` / `hvl_typedefs:` | interface 级 | `typedefs` |
| `is_active` | interface 级（含旧路径 `config.is_active`） | env 级 `agents[].is_active` |
| `custom_code` 等 | interface 级 | `pragma custom` 区域 + `-m` 合并（见场景 9） |

> 注：env 里的 `agents[].interface` **保留但不再参与类名推导** —— 类名一律看显式 `type`。

### 计分板组件族精简（破坏性）

`scb_pkg` 下线了 `multich_in_order_scoreboard` / `multich_out_of_order_scoreboard` /
`typed_scoreboard`（含 `DEFINE_TYPED_SCOREBOARD` 宏）/ `algorithm_scoreboard` 四个分片
——它们无任何模板消费方。现只提供 `comparator` / `default_comparator` /
`in_order_scoreboard` / `out_of_order_scoreboard`。旧代码若引用被下线组件，编译会报
找不到类型；改用保留的两个计分板，或按场景 3 手写子类扩展。

## 0. 校验链（生成流程的执行顺序）

```
YAML 输入
  → Phase 0  schema 语法检查   （键名/类型/必填/枚举/未知键；error 阻断）
  → Phase A  语义校验           （跨字段引用/TLM/覆盖率等；error 阻断，warning 落盘不阻断）
  → 渲染生成（agents/env/bench/cons/utils）
  → 门禁 --gate（可选，编译+仿真）
  → 报告 --report-json（可选，签核证据包）
```

Phase 0 可用 `--skip-schema-check` 关闭；两个校验的报告分别落盘
`schema_report.txt` / `validation_report.txt`。

---

## 1. 快速上手：从示例全链路生成

```bash
# 目录形式输入（递归收集目录下所有 *.yaml/*.yml，多文件自动合并）
python -m src.tools.generation.uvm_tools.tool_uvm.main -i examples/apb/ -d generated/

# .f 清单文件（一行一个 YAML 路径；-f 与 -i 同义）
python -m src.tools.generation.uvm_tools.tool_uvm.main -f examples/apb_yamlist.f -d generated/

# 等价：显式列文件
python -m src.tools.generation.uvm_tools.tool_uvm.main -i examples/apb/apb_interface.yaml \
    examples/apb/apb_env.yaml examples/apb/apb_bench.yaml \
    examples/apb/apb_constraint.yaml examples/apb/apb_util_comp.yaml -d generated/
```

预期输出（AXI-VIP 风格编号分层）：

```
generated/
├── agents/APB_agent/
│   ├── 1_interface/   APB_if.sv / APB_system_if.sv
│   ├── 2_config/      APB_port_config.sv（单类，port_kind 区分 MASTER/SLAVE）
│   ├── 3_transaction_sequencer/  base_seq_item + master/slave seq_item + sequencer
│   ├── 4_driver_monitor/  master/slave driver + port_monitor（均带 UVM callback 钩子）
│   ├── 5_agent/       master/slave agent + system_config + system_vsqr
│   │                  + system_monitor + system_env
│   ├── 7_sequence/    master/slave sequence
│   ├── 8_ral/         reg_adapter
│   ├── APB_parameters_pkg.sv / APB_typedefs_pkg.sv / APB_pkg.sv
│   ├── filelist.f / Makefile / summary.md
│   └── loopback/      自闭环自检（master-drive → slave-monitor）+ 独立 filelist.f
├── env/     APB_env.sv / _config / _coverage / _parameters_pkg / _pkg
│           / _sim_end / <env>_pkg_filelist.f
│   ├── seqs/  virtual_sequencer + virtual_base_seq + seq_pkg
│   ├── tests/ test_pkg + base_test + direct_test + gen_test
│   ├── cons/  约束策略产物（见场景 5）
│   └── utils/ predictor 等通用组件（见场景 6）
├── bench/   APB_bench_tb_top.sv + apb_harness.sv
├── Makefile  整环境双后端编译/仿真入口（env + agents + bench）
├── Sourceme  定义 $WORK_PATH
├── schema_report.txt / validation_report.txt / generation_report.json
└── README.md
```

### 1.1 路径基准：Sourceme 与 WORK_PATH 环境变量

整环境 filelist（`env/<env>_pkg_filelist.f`）**不写生成时刻的绝对路径**，一律以
`$WORK_PATH` 为根 —— 这样生成目录可以整体搬到别的机器/路径，不必重新生成。

`Sourceme` 与 filelist 一并生成在输出目录根：

```bash
setenv WORK_PATH  `pwd`
```

用法：

```bash
cd generated/          # 或任意 run 输出目录
source Sourceme        # 定义 $WORK_PATH = 当前目录
vlog -sv -f env/APB_env_pkg_filelist.f
```

`$WORK_PATH/..` 指向仓库内的 `base_pkg`；生成目录在仓库内时前缀很短，在仓库外
时 `relpath` 会自动补够 `../`（仍然可解析）。

> agent 级的 `agents/<X>_agent/filelist.f` 与 `loopback/filelist.f` 是**相对于各自
> 目录**的，从该目录直接 `vlog -f filelist.f` 即可，不依赖 `$WORK_PATH`。

### Agent Makefile 双后端（Questa / VCS）

每个 agent 的 `Makefile` 同时支持 QuestaSim 与 VCS，`SIM` 变量切换（缺省 `questa`）：

```bash
cd agents/APB_agent
make                  # Questa 编译（vlib + vlog）
make compile SIM=vcs  # VCS 编译（单步 vcs → simv）
make run              # loopback 自闭环：编译 + 仿真（Questa）
make run SIM=vcs SEED=5
```

后端路径均可覆盖：`QUESTA` / `UVM_HOME` / `UVM_DPI`（Questa），`VCS` / `VCS_HOME`（VCS）。
VCS 走 `-ntb_opts uvm-1.2` 自带 UVM 库，无需额外 UVM 路径配置。

### 整环境 Makefile（生成目录根）

生成目录根的 `Makefile` 一键编译整个环境（base_pkg → agents → harness → env →
tests → seqs → tb_top），同样双后端，`SIM` 切换：

```bash
cd generated
make                              # Questa 编译
make compile SIM=vcs              # VCS 编译
make run TEST=APB_env_base_test   # 编译 + 仿真一个测试
make run SIM=vcs SEED=5 TEST=APB_env_direct_test
make compile DUT=rtl/dut.sv       # 追加 DUT 源码
make run COV=1                    # 覆盖率（Questa +cover/ucdb，VCS -cm/vdb）
```

编译文件清单为相对路径自包含（agent 段按 interface 级目录
`agents/{NAME}_agent` 引用），可在 Windows Questa 与 Linux VCS 之间切换；
`BASE_PKG` 相对路径由生成器渲染，跨机器可覆盖。

---

## 2. 场景：单接口 agent（协议默认驱动/采样）

**目标**：一个接口 → master/slave 两个 agent，含协议正确的默认时序。

```yaml
interfaces:
  - name: APB                # 协议/agent 名（生成类前缀 apb_）
    clock: pclk
    reset: presetn
    protocol: apb            # 协议名 → 渲染两拍 setup+access 默认时序（可留空=单拍）
    reset_active_low: True   # 复位极性（缺省 True = 低有效）
    parameters:              # 渲染进 interface #(...)
      - { type: int, name: ADDR_WIDTH, value: 32 }
    typedefs:                # 类型别名，渲染进 <name>_typedefs_pkg
      - { type_t: "bit [7:0]", type_name: "byte_t" }   # → typedef bit [7:0] byte_t;
    ports:                   # dir: output=master驱动 / input=slave驱动
      - { name: paddr,  dir: output, width: ADDR_WIDTH }
      - { name: prdata, dir: input,  width: DATA_WIDTH }
    transaction_vars:        # 事务字段：isrand 驱动 / iscompare 参与自检比对 / is_master 角色
      - { name: paddr, type: "bit [ADDR_WIDTH-1:0]", iscompare: "True", isrand: "True", is_master: "True" }
```

**`typedefs` 的三个要点**：

- 每项是 `{ type_t: 类型表达式, type_name: 新类型名 }`，渲染成 `typedef <type_t> <type_name>;`
- 你写多长列表就按 YAML 顺序逐条声明，**被引用的 typedef 必须写在前面**（写反了
  Phase A 会报 `typedef_forward_ref` error 并阻断生成）
- 生成的 `<name>_typedefs_pkg` 会 `import <name>_parameters_pkg::*`，所以 `type_t`
  里可以直接引用 `parameters`（如 `bit [ADDR_WIDTH-1:0]`）。**类型名是否在别处有
  定义不做检查** —— 校验器看不到外部包 / 手写包里的类型，查了必然误伤，交编译期兜底

**`protocol: apb` 的额外约束**：缺 `psel` / `penable` / `pready` / `paddr` /
`pwrite` / `pwdata` / `prdata` 任一端口，Phase A 会报 `protocol_apb_ports_missing`。

> 激活模式（UVM_ACTIVE / UVM_PASSIVE）**不在 interface 级配置**：interface 只描述协议与端口，
> 激活由 env 级 `agents[].is_active` 决定（缺省 UVM_ACTIVE）；loopback 自检套件固定
> master-ACTIVE / slave-PASSIVE。写 interface 级的 `is_active`（含旧路径
> `config.is_active`）会被 schema 判为未知键 / 已下线字段而报错。

```bash
python -m src.tools.generation.uvm_tools.tool_uvm.main -i apb_interface.yaml -d generated/
```

---

## 3. 场景：多 agent 环境（env + scoreboard + predictor + TLM）

**目标**：聚合多个 agent 实例 + 参考模型 + 计分板 + 显式 TLM 连接。

```yaml
environment:
  name: APB_env
  agents:                       # 每项 = 一个 agent 实例
    - name: apb_master          # 实例名
      type: apb_master_agent    # agent 类名，显式写（不由 interface 拼接）
      is_active: True
      is_master: True
    - name: apb_slave
      type: apb_slave_agent
      is_active: False
      is_master: False
  subenvs:                      # 子环境
    - name: apb_sys_env
      type: apb_system_env      # 环境类名（缺省 = name）
  scoreboards:
    - name: apb_scb
      sb_type: uvmf_in_order_scoreboard
      trans_type: apb_master_seq_item
  analysis_components:          # predictor 等
    - name: apb_pred
      type: apb_predictor
  tlm_connections:              # driver/receiver 显式连接
    - driver: apb_pred.out_port
      receiver: apb_scb.expected_analysis_export
  harness_connect:
    path: "APB_bench_tb_top.u_dut.harness"
```

> `agents[].type` 里要写**完整的 agent 类名**（`apb_master_agent`），不是 interface 名。
> `name` 与 `type` 至少写一个：只写 `type` 时 `name` 取 `type` 去掉 `_agent` 后缀。

多文件输入：`-i apb_interface.yaml apb_env.yaml -d generated/`（跨文件自动关联）。

### scoreboards 的接法

**本工具不生成计分板文件** —— `sb_type` 指向一个工厂可注册的类
（VIP 自带、`base_pkg/scb` 的组件、或你手写的），env 直接例化它。

```yaml
scoreboards:
  # 具名类：直接用
  - name: apb_scb
    sb_type: uvmf_in_order_scoreboard
    trans_type: apb_master_seq_item

  # 参数化类：给 params 传实参
  - name: apb_scb_param
    sb_type: in_order_scoreboard
    trans_type: apb_master_seq_item
    params: [apb_master_seq_item, apb_master_seq_item]
```

**参数化类必须给 `params`。** `in_order_scoreboard apb_scb;` 这种写法在 SV 里
编译不过（参数化类不能裸用），给了 `params` 后模板会先生成特化别名再声明句柄：

```systemverilog
typedef in_order_scoreboard#(apb_master_seq_item, apb_master_seq_item) apb_scb_param_t;
apb_scb_param_t apb_scb_param;
...
apb_scb_param = apb_scb_param_t::type_id::create("apb_scb_param", this);
```

不给 `params` 时按具名类处理，句柄类型 = `sb_type` 本身（用于 `uvmf_in_order_scoreboard`
这类已注册的具名类）。

> 生成式计分板（`mode` + `expected_from` / `actual_from`，产物 `env/scb/{name}.sv`）
> **已下线**。要自包含计分板，用 `base_pkg/scb` 的 `in_order_scoreboard` /
> `out_of_order_scoreboard`（配 `params`，或手写具名子类），再用 `sb_type` 指过去。

### 内置计分板组件族（base_pkg/scb → scb_pkg）

整环境编译链自动包含 `base_pkg/` 两个基础包（filelist/Makefile 只编译包文件，
分片经 `+incdir` 解析）：`clk_and_rst_pkg`（时钟复位 VIP）与 `scb_pkg`（计分板组件族）。
另外 `base_pkg/common_typedefs/common_typedefs_pkg.sv` 提供公共类型
（`port_kind_enum` 的 `MASTER`/`SLAVE`、`response_mode_e`、`resp_type_e` 等），
每个 agent 的 `_pkg.sv` 都会 `import common_typedefs_pkg::*`。

`scb_pkg.sv` 是顶层组装文件，只编译一个文件；各组件分片（`.svh`）通过
`+incdir` 引用，无需在 filelist 中列出所有分片。

| 组件 | 参数 | 用途 |
|------|------|------|
| `comparator` / `default_comparator` | `#(T)` | 比较器虚接口 + 默认实现（可注入自定义比较器） |
| `in_order_scoreboard` | `#(REQ_T, RSP_T, CMP_T)` | 顺序计分板基座：expected/actual 双 imp，严格/非严格比对 |
| `out_of_order_scoreboard` | `#(T, ID_T, CMP_T)` | 乱序计分板：按事务 ID 关联匹配（重载 `get_id()`） |

全部组件自带统计与 `check_phase` 裁决（mismatch / missing / extra > 0 →
`uvm_error`，仿真判 FAIL）。

**消费方式**：这些组件都是参数化类，**不能裸当 `sb_type` 用**
（`in_order_scoreboard apb_scb;` 编译不过）。两条路：

**方式 1（推荐）：YAML 里给 `params`**，模板自动 typedef 特化：

```yaml
scoreboards:
  - name: apb_scb
    sb_type: in_order_scoreboard
    trans_type: apb_master_seq_item
    params: [apb_master_seq_item, apb_master_seq_item]
```

**方式 2：手写具名子类**（要额外行为、重载 `get_id()` 等时用），放在自有 VIP 包
或生成代码的手改区域均可：

```systemverilog
import scb_pkg::*;

// 具名特化：子类带 uvm_component_utils 注册后，YAML 即可 sb_type: apb_in_order_scb
class apb_in_order_scb extends in_order_scoreboard#(
    apb_master_seq_item, apb_master_seq_item,
    default_comparator#(apb_master_seq_item));
  `uvm_component_utils(apb_in_order_scb)
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
endclass
```

**连接约定**（`tlm_connections` 的 `driver` / `receiver` 路径）：

| 组件 | 预期侧端口 | 实际侧端口 |
|------|-----------|-----------|
| in_order / out_of_order | `expected_export` | `actual_export` |

**实例级配置**（`uvm_config_db`，作用于 scb 实例）：

| 字段 | 缺省 | 含义 |
|------|------|------|
| `enable_prediction` | 1 | 是否接收预期侧事务 |
| `strict_ordering` | 1 | 严格比对（队首一对一）；0 = 任意位置匹配（乱序容忍） |
| `max_queue_depth` | 1024 | 队列上限，溢出刷最旧并计 missing / extra |

---

## 3.5 场景：rtl_sc（Scoreboard Predictor，监控器 + 产生器 + 计分板预测）

**目标**：生成监控器（mon_ex）和产生器（prod），自动配置 Scoreboard Predictor 机制，
用于实时监控与预测寄存器级别的状态。

生成目录会包含 `env/utils/{{name}}_sc_pred_env.sv`、`{{point}}_mon_ex.sv`、
`{{point}}_prod.sv`。在环境 YAML 中添加 `rtl_sc_components` 字段：

```yaml
environment:
  name: APB_env
  rtl_sc_components:
    - name: apb_rtl_sc
      check_points:                  # 检查点：需要监控的输出端口
        - { point_name: apb_data, channel_num: 2, width: 32 }
      prod_points:                   # 产生点：需要产生信号的端口（可选）
        - { point_name: apb_addr, channel_num: 2, width: 32 }
      config:
        ut_id: 1
        has_prod: 1
```

| 组件 | 类名 | 功能 |
|------|------|------|
| 环境类 | `{{name}}_sc_pred_env` | 管理 mon_ex 和 prod 数组，配置连接 |
| 监控器 | `{{point}}_mon_ex` | 采样接口信号，输出到 analysis_port |
| 产生器 | `{{point}}_prod` | 产生预测信号，输入到 Scoreboard Predictor |

工作流程：

```
DUT 信号
  → vif（虚拟接口）
    → {{point}}_mon_ex（采样） → mon_ex_port（analysis_port）
      → sc_pred_env（注册检查点） → rtl_sc_register（状态追踪）
    → {{point}}_prod（产生预测） → prod_port（analysis_port）
      → sc_pred_env（注册产生点） → rtl_sc_predict（预测逻辑）
        → Scoreboard Predictor（比较预期/实际）
```

| 配置项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | string | 必填 | 环境类前缀 |
| `check_points` | array | 必填 | 检查点列表（监控点） |
| `prod_points` | array | 空 | 产生点列表（可选） |
| `channel_num` | int | 1 | 通道数量（多路监控） |
| `width` | int | 必填 | 位宽（匹配 DUT 端口） |
| `ut_id` | int | 0 | 用户 ID（用于区分实例） |
| `has_prod` | bit | 1 | 是否启用产生器 |

---

## 3.6 场景：base_transaction（master/slave 共用基类）

**目标**：把两侧都有的字段与约束收进一个基类，避免在 master/slave 里各写一遍。

```yaml
interfaces:
  - name: APB
    base_transaction_vars:          # 两侧共用 → 渲染进 APB_base_seq_item
      - { name: addr, type: "bit [ADDR_WIDTH-1:0]", iscompare: "True", isrand: "True" }
      - { name: data, type: "bit [ADDR_WIDTH-1:0]", iscompare: "True", isrand: "True" }
    base_transaction_constraints:
      - { name: c_addr_align, value: "{ addr[1:0] == 2'b00; }" }
    transaction_vars:               # 按 is_master 划分给各侧
      - { name: paddr, ..., is_master: "True"  }   # → master_seq_item
      - { name: prdata, ..., is_master: "False" }  # → slave_seq_item
    transaction_constraints:
      master:
        - { name: c_paddr_align, value: "{ paddr[1:0] == 2'b00; }" }
```

产物结构：

```
APB_base_seq_item        ← extends uvm_sequence_item
  ├─ typedef enum {READ, WRITE} xact_type_e;   ← 两侧共用的方向
  ├─ rand xact_type_e xact_type;
  ├─ addr / data                               ← base_transaction_vars
  └─ c_addr_align                              ← base_transaction_constraints
       ▲                                        ▲
APB_master_seq_item ──┘   APB_slave_seq_item ──┘   （extends APB_base_seq_item）
  paddr / pwrite / pwdata      prdata / pslverr + 响应控制
```

**两条必须遵守的规则**（`base_*` 渲染进基类，不是派生类）：

| 规则 | 原因 |
|---|---|
| `base_transaction_constraints` **只能引用 `base_transaction_vars` 里的字段** | 基类看不到派生类成员。写 `paddr` 会**编译不过**（`paddr` 只在 master_seq_item 里） |
| 约束名**不要**与 `transaction_constraints` 重名 | 派生类同名约束会覆盖基类那份，看代码时极易看走眼 |

> `xact_type` / `xact_type_e` 已上移到基类 —— master/slave 里**不再重复声明**，
> 派生类只注册自己的字段（基类字段由基类的 `uvm_object_utils_begin/end` 注册，
> UVM 的 `do_*` 会沿继承链调 `super`，不会漏）。

## 3.7 场景：系统级虚拟 sequencer（`_system_vsqr`）

**目标**：给**同一协议下的多个实例**（`num_masters` / `num_slaves` 决定）一个统一的
协调入口 —— 在虚拟序列里跨端口发激励。

与 env 级 `<env>_virtual_sequencer` 的分工：那个跨**不同协议**（apb/uart/intr…），
句柄是具名成员；这个跨**同协议多实例**，实例数编译期未知，故句柄用动态数组。

产物（每个 interface 一份，自动生成并接进 `system_env`）：

```systemverilog
APB_system_vsqr
  ├─ APB_master_sequencer master_sqr[];   // 由 system_env.connect_phase 赋值
  ├─ APB_slave_sequencer  slave_sqr[];
  ├─ get_master_sqr(i) / get_slave_sqr(i) // 越界 uvm_fatal
  ├─ num_masters() / num_slaves() / is_bound()
  ├─ wait_bound(timeout_ns)               // 发 sequence 前先等绑定完成
  └─ broadcast_master_cfg(cfg) / broadcast_slave_cfg(cfg)
```

用法（虚拟序列里）：

```systemverilog
class my_vseq extends uvm_sequence;
  `uvm_declare_p_sequencer(APB_env_virtual_sequencer)
  APB_system_vsqr sys_vsqr;
  task body();
    APB_master_sequence seq;
    seq = APB_master_sequence::type_id::create("seq");
    seq.start(sys_vsqr.get_master_sqr(1));   // 只对第 1 号 master 发激励
  endtask
endclass
```

---

## 4. 场景：bench + harness（bind 式自连接）

**目标**：tb_top 例化 clk_rst_if + DUT，harness 以 bind 方式把 interface 连到 DUT。

```yaml
bench:
  name: apb_bench
  include_assertions: false        # env 名自动取本次解析出的 environment.name
  clk_rst_if:                       # 时钟复位（旧名 clk_rst 仍兼容）
    clocks: [{ name: pclk }]        # 也可裸字符串 ["pclk"]
    resets: [{ name: presetn }]
  dut_instance: u_dut               # DUT 实例名（tb_top 按 harness.bind_to 例化）
  harness:
    name: apb_harness
    bind_to: apb_slave_dut          # bind 目标 module（所有实例生效）
    interfaces:
      - name: apb_if
        type: apb_interface
        agent_path: "apb_master_agent_h"
        connections: { pclk: pclk, paddr: paddr }
```

`clk_rst_if` 里的 `pclk` / `presetn` 会渲染成 tb_top 的
`clk_rst_if pclk_vif();` + DUT 端口 `.pclk(pclk_vif.clk[0])` / `.presetn(pclk_vif.rst_n[0])`。

测试侧通过 `harness_connect.path` 调 `<path>.set_vifs()`。

### 仿真自动结束（env 级 `{env}_sim_end` 组件）

tb_top 不内嵌仿真控制块，由 env 自动例化的 `{env}_sim_end` 组件负责：

- **自动结束**：run_phase 全部 objection 清零 → 报告阶段完成后 `$finish`
  （仿真跑完自动退出，不会悬挂；`+SIM_NO_AUTO_FINISH` 关闭）
- **看门狗**：`+SIM_WATCHDOG_NS=1000000` 指定超时（ns），超时 `UVM_FATAL` 强制退出；
  缺省关闭

```bash
# 回归常用组合：10ms 看门狗 + 自动结束
vsim -c -do "run -all; quit -f" tb +SIM_WATCHDOG_NS=10000000
```

---

## 5. 场景：多端口约束策略（cons）

**目标**：多端口事务组合场景——策略 + 组合器 + 协调序列（5 个文件到 `env/cons/`）。

```yaml
constraint:
  name: apb_cons
  env: apb_env                   # 可选：env 名（缺省取本次解析出的 environment）
transactions:                    # 每端口一项，name 与 env agents 名一致
  - { name: apb_master, type: APB_master_seq_item }
policies:
  - name: apb_addr_align         # 自定义名 → 空 apply 骨架（手填协议逻辑）
    priority: 10
    params: [{ name: align, type: int, default: 4 }]
    applies_to: [apb_master]     # 多端口 = 列出多个
combinator:
  default_mode: APPLY_ALL        # APPLY_ALL/WEIGHTED/FIRST_MATCH/SEQUENTIAL/CHAIN
```

内置策略名（有默认 apply 逻辑）：precision_consistency / mem_capacity /
data_dependency / boundary_overflow / concurrent_access / power_performance /
compute_mode / apb_addr_align。

---

## 6. 场景：工具组件（util_components）

**目标**：YAML 配置生成 predictor 等通用组件（analysis 端口自动生成 imp/port），
输出到 `env/utils/`。

```yaml
util_components:
  - name: apb_predictor
    type: uvm_component
    analysis_exports: [{ name: in_export, type: apb_master_seq_item }]
    analysis_ports:   [{ name: out_port, type: apb_master_seq_item }]
```

---

## 7. 场景：增量开发（跳过已存在 / 覆盖 / 指定组件）

```bash
# 默认跳过已存在文件（UVMF 风格）——重复生成不会覆盖手改代码
python -m src.tools.generation.uvm_tools.tool_uvm.main -i examples/apb/ -d generated/

# 强制覆盖（改了 YAML 后重跑用这个）
python -m src.tools.generation.uvm_tools.tool_uvm.main -i examples/apb/ -d generated/ -o

# 只生成指定组件（按 name 过滤）
python -m src.tools.generation.uvm_tools.tool_uvm.main -i examples/apb/ -d generated/ -g APB

# 静默（CI 用）
python -m src.tools.generation.uvm_tools.tool_uvm.main -i examples/apb/ -d generated/ -q
```

---

## 8. 场景：手改代码合并（auto-merge）

**目标**：模板升级后，把旧生成代码里手改的 pragma custom 区域合并进新生成代码。

```bash
# 从 hand_edited_src/ 提取手改区域合并（自动备份 <目录>_backup_<时间戳>）
python -m src.tools.generation.uvm_tools.tool_uvm.main -i apb_env.yaml -d generated/ -m hand_edited_src/

# 旧源有无法映射的块时继续（默认报错中止）
python -m src.tools.generation.uvm_tools.tool_uvm.main -i apb_env.yaml -d generated/ -m hand_edited_src/ -s

# 不备份 / 输出未合并中间产物（调试）
python -m src.tools.generation.uvm_tools.tool_uvm.main -i apb_env.yaml -d generated/ -m hand_edited_src/ \
    --merge_no_backup --merge_debug --merge_verbose
```

回填优先级：merge 源手改内容 > 模板默认。

---

## 9. 场景：pragma custom 区域（协议时序自定义）

**目标**：在生成文件的 `pragma custom` 区域内手写自定义逻辑，重新生成时用
`-m/--merge_source` 带过来。

```systemverilog
    // pragma custom drive_logic begin
    // 自定义协议驱动时序
    repeat (2) @(vif.master_cb);
    vif.master_cb.penable <= 1'b1;
    // pragma custom drive_logic end
```

常用槽位：`field_decl` / `build_logic` / `connect_logic` / `drive_logic` /
`collect_logic` / `seq_body` / `run_logic`（详见 readme）。

YAML 注入已下线：`custom_code`（以及更早的标量字段 `custom_drive_logic` /
`custom_sample_logic` / `custom_collect_logic`）不再被 schema 接受，写了会报未知键。

---

## 10. 场景：YAML schema 语法检查

**目标**：在生成前拦截「键名拼错 / 类型写错 / 必填缺失 / 非法枚举」——这类错误
会被解析器静默吞掉（如缺 name/type 的 harness interface 条目被直接丢弃）。

### 10.1 生成流程内置（Phase 0，缺省开启）

```bash
# 任意 schema 违规（含拼错键 / 多余字段）→ 阻断生成，报告落盘 schema_report.txt
python -m src.tools.generation.uvm_tools.tool_uvm.main -i my.yaml -d generated/
#  → Schema validation failed: 2 error(s), 0 warning(s) — see .../schema_report.txt
#  → [ERROR] unknown_property @ my.yaml::interfaces[0].reset_active_loww: 未知键 ...

# 逃生舱：旧 YAML 触发 schema error 又需继续生成时跳过 Phase 0
python -m src.tools.generation.uvm_tools.tool_uvm.main -i my.yaml -d generated/ --skip-schema-check
```

### 10.2 独立检查命令（不生成，纯校验）

```bash
# 单文件 / 目录 / 多个文件（位置参数或 -i）
python -m src.tools.generation.uvm_tools.tool_uvm.schema_check my.yaml
python -m src.tools.generation.uvm_tools.tool_uvm.schema_check -i examples/apb/ -q

# 报告落盘 / 自定义 schema 文件
python -m src.tools.generation.uvm_tools.tool_uvm.schema_check -i examples/apb/ --report /tmp/schema_report.txt
python -m src.tools.generation.uvm_tools.tool_uvm.schema_check -i examples/apb/ --schema my_schema.json
```

- 严重度：**全部违规 → `error`**，包括未知键/多余字段（`unknown_property`）——
  拼错的键会被 normalizer 静默吞掉，故不做「仅警告」放行
- 退出码：有 error → 1；无 error → 0（CI 可直接用）
- 报错定位到路径：`my.yaml::interfaces[0].ports[0].dir` 形式
- schema 契约文件：`schema/uvm_config.schema.json`（Draft 2020-12，可被编辑器/IDE
  直接复用做实时校验）

---

## 11. 场景：语义校验与报告

**目标**：拦截「生成合法但行为错误」的跨字段问题（端口↔事务字段、TLM 引用、
覆盖率 cross 字段等）。

- error → 阻断生成；warning → 不阻断，继续生成
- 报告落盘 `generated/validation_report.txt`，规则清单可用
  `SemanticValidator.rules_doc()` 导出
- 无需额外参数，生成时自动执行（Phase A）

当前规则（error 阻断 / warning 仅提示）：

| 规则 | 级别 | 检查 |
|---|---|---|
| `param_width_undefined` | error | 端口 width 引用的参数未在 parameters 中定义 |
| `port_dup_name` | error | 端口重名 |
| `txn_var_dup_name` | error | 事务字段重名 |
| `typedef_forward_ref` | error | typedef 引用了同一列表里后面才声明的名字 |
| `typedef_self_ref` | error | typedef 的类型引用了它自己 |
| `protocol_apb_ports_missing` | error | protocol=apb 时缺必需的协议端口 |
| `txn_var_port_mismatch` | warning | 事务字段没有同名端口（该字段不被驱动/采样） |
| `port_not_in_txn` | warning | 端口没有对应事务字段（控制类端口属正常） |

env/bench/constraint 级另有 `analysis_port_dup_name` / `tlm_connection_unknown_ref` /
`register_model_bus_unmatched` / `harness_connect_path_missing` / `coverage_cross_unknown` /
`agent_wire_undefined` / `bind_to_missing` / `if_empty_connections` / `txn_dup_name` /
`policy_dup_name` / `policy_applies_to_unknown` / `policy_unknown_name` 等。

---

## 12. 场景：编译仿真门禁（--gate）

**目标**：生成后对每个 agent 的 loopback 自检跑编译 + 仿真，快速确认生成代码可编译。

```bash
python -m src.tools.generation.uvm_tools.tool_uvm.main -i examples/apb/ -d generated/ --gate
#  [PASS] APB_agent (sim=0)     ← 检测到 vlog/vsim 或 vcs
#  [SKIP] APB_agent — no UVM simulator (vlog/vcs) found   ← 无仿真器仅跳过，不阻断
```

只认 `vlog`/`vcs`（iverilog/verilator 不支持 UVM 类，不参与门禁）。

---

## 12.5 场景：driver / monitor 的 UVM callback

**目标**：在不改动生成代码的前提下，于驱动前后、采样后插入测试自己的行为
（改激励、注入错误、时序记录、协议检查）。

各组件提供一对钩子：

| 组件 | 钩子 | 时机 |
|---|---|---|
| `<name>_master_driver` | `pre_drive` / `post_drive` | 驱动一笔 transaction 前 / 后 |
| `<name>_slave_driver`  | `pre_drive` / `post_drive` | 响应一笔 transaction 前 / 后 |
| `<name>_port_monitor`  | `post_sample` / `post_sample_slave` | master / slave 侧采样完成后 |

派生 + 注册：

```systemverilog
class my_err_cb extends APB_master_driver_cb;
  `uvm_object_utils(my_err_cb)
  function new(string name = "my_err_cb"); super.new(name); endfunction

  virtual task pre_drive(APB_master_driver drv, APB_master_seq_item req);
    if ($urandom_range(0, 9) == 0) req.paddr = '1;   // 5% 概率打错误地址
  endtask
endclass

// test 的 build_phase：
my_err_cb cb = my_err_cb::type_id::create("cb");
uvm_callbacks#(APB_master_driver, APB_master_driver_cb)::add(drv_h, cb);
```

实现要点（若你要改模板）：callback 类必须定义在**同一个 .sv 文件、driver/monitor
之前**，并用 `typedef class <driver>;` 前置声明 —— 钩子的方法签名要传 driver 句柄，
而 driver 定义在下方，SystemVerilog 要求先声明后使用。

> monitor 只提供 `post_sample`：两条 collect 路径都是「等到一次完整访问 → 逐字段采样」，
> 在「等到」之前 transaction 尚不存在，没有有意义的 pre 点。

## 13. 场景：签核证据包（--report-json）

**目标**：结构化生成报告供 Agent 决策 / 签核证据包引用（`generation_report.json`）。

```bash
python -m src.tools.generation.uvm_tools.tool_uvm.main -i examples/apb/ -d generated/ --report-json --gate
#  → Report: generated/generation_report.json
```

报告包含：`schema`（Phase 0 结果）/ `validation`（语义校验）/ `merge`（合并明细）/
`gate`（门禁结果）/ 输入文件清单——完整证据链落盘。

---

## 14. 场景：文件头定制（meta）

**目标**：所有生成文件统一文件头（公司/权利声明/作者/邮箱/时间）。

```yaml
meta:
  company: "SignOffAI（功能签核）"
  author: "张三"
  email: "zhangsan@example.com"
  created: "2026-09-01"     # 固定创建时间（缺省 = 生成时刻）
```

`meta:` 可写在任意输入 YAML 顶层；多个文件后读覆盖同名键。

---

## 15. 场景：清理与维护

```bash
# 清理带生成签名的文件（只删生成文件，手改文件安全）
python -m src.tools.generation.uvm_tools.tool_uvm.main -c -d generated/

# 列出支持的模板集
python -m src.tools.generation.uvm_tools.tool_uvm.main --list-templates

# 版本
python -m src.tools.generation.uvm_tools.tool_uvm.main --version
python -m src.tools.generation.uvm_tools.tool_uvm.schema_check --version
```

---

## 16. 场景：属性测试（`environment.tests`）

**目标**：让「case 由哪些属性组成」这件事直接落到 UVM —— **一条 `tests:` 条目
= 一个 UVM_TEST = 一个属性取值**（维度 × 取值）。属性经 `uvm_config_db` 传进
环境，消费方（env / sequence / driver）读出来按自己的语义解释。

### 清单里怎么写

在 `environment:` 下加一段 `tests:`（`dimension` / `value` 必填）：

```yaml
environment:
  name: FC_env
  agents: [ ... ]

  # 一条 = 一个 UVM_TEST = 一个属性取值
  tests:
    - {dimension: D_ratio, value: "0",   key: fc_ratio, int_value: 0}
    - {dimension: D_ratio, value: "50",  key: fc_ratio, int_value: 50}
    - {dimension: D_ratio, value: "100", key: fc_ratio, int_value: 100}
```

`key` / `int_value` / `base` 可选：`base` 缺省 `{env_name}_gen_test`。

### 生成的产物

`tests:` 非空时才产 `<env>_attr_test.sv`（并条件 `include` 进 `<env>_test_pkg.sv`）：

```systemverilog
// ── 属性 test 2：D_ratio = 50 ──
`GEN_ATTR_TC(FC_env_d_ratio_p50_test, FC_env_gen_test, "fc_ratio", 50)
```

类名 = `{env}_<维度slug>_p<取值>_test`，**全 ASCII**。

### 两条设计取舍

- **机器通道是 `int`（键 `<key>_int`），不做中文字符串字面量**。维度 id 是 ASCII
  但取值 token 常是中文；把非 ASCII 塞进会被比较、被打印的 SV 字面量是 locale
  隐患。所以取值投影成 int（数字本身，非数字用下标），中文值只留注释。
  **`tool_uvm` 不知道 `0/10/50/100` 分别代表什么** —— 那是消费方的语义，
  和它不该知道 casemodel 的语义是同一个道理。模板里附了精确的 `::get` 示例注释。
- **`tool_uvm` 不截断**：`tests:` 写几条就渲染几条，静默丢 test 是不可接受的。
  条数上限由上游（`casemodel_tools` 的 `--max-tests`）管，且截断会记账。

### 清单从哪来

属性取值来自 `casemodel_tools`，**粘过来**即可（两个工具之间只有文件格式契约，
互不 import）：

```bash
python -m src.layers.l3_decision.casemodel.cli uvm-tests model.yaml -d D_ratio
# → 4 条 tests: 片段，贴进上面 environment: 下
```

---

## CLI 参数速查

### gen_uvm（生成命令）

| 参数 | 说明 |
|------|------|
| `-i/--input PATH...` | 输入 YAML 文件或目录（缺省 `.`）；`-f/--file` 同义；也可传 **`.f` 清单文件**（一行一个路径，`#`/`//` 注释，`+incdir+` 等选项行忽略） |
| `-d/--dest_dir DIR` | 输出目录（缺省 `generated`）；`--output` 同义 |
| `-o/--overwrite` | 覆盖已存在文件（缺省跳过） |
| `-g/--generate NAME` | 只生成指定组件 |
| `-t/--template_dir DIR` | 覆盖模板目录 |
| `-q/--quiet` | 静默 |
| `-m/--merge_source DIR` | 合并手改 pragma custom 区域 |
| `-s/--merge_skip_missing_blocks` | 旧源无法映射的块跳过（缺省报错） |
| `--merge_no_backup` / `--merge_debug` / `--merge_verbose` | 合并流程控制 |
| `--gate` | 生成后跑 loopback 编译+仿真门禁（无仿真器跳过） |
| `--report-json` | 输出 `generation_report.json` |
| `--skip-schema-check` | 跳过 Phase 0 schema 检查 |
| `--list-templates` / `--version` / `-c/--clean` | 模板清单 / 版本 / 清理生成文件 |

### schema_check（独立检查命令）

| 参数 | 说明 |
|------|------|
| `INPUT...`（位置参数） | YAML 文件或目录（同 `-i`） |
| `-q/--quiet` | 只输出摘要行 |
| `--report PATH` | 报告落盘 |
| `--schema PATH` | 覆盖 schema 文件 |
| `--version` | 版本 |

---

## 常见问题排查（FAQ）

| 现象 | 原因与处理 |
|------|-----------|
| `No YAML files were found in the input paths.` | 输入路径下没有 `*.yaml/*.yml`；检查 `-i` 路径 |
| `No supported YAML definitions were found.` | YAML 解析后没有任何有效组件（如缺 name 被静默丢弃）；先跑 schema_check 定位 |
| `Schema validation failed: N error(s) ...` | YAML 违反 schema（必填/类型/枚举/未知键）；按报告修 YAML，或 `--skip-schema-check` 临时绕过 |
| `Schema check skipped (jsonschema not available)` | 缺依赖：`pip install jsonschema` |
| `[ERROR] unknown_property ... 'xxx'` | 键名拼错，或写了已下线的键（见「已下线的键」表）；删掉或改成正确键名 |
| `[ERROR] unknown_property ... 'type'`（env agents） | 说明 schema 版本旧；当前 `agents[].type` 是**合法且推荐**的写法 |
| `[ERROR] typedef_forward_ref ... declared later` | typedefs 里引用了后面才声明的类型名；把被引用者挪到前面 |
| `[ERROR] typedef_self_ref` | typedef 的类型写成了它自己（无限递归） |
| 生成文件没有更新 | 缺省跳过已存在文件；用 `-o` 覆盖，或确认文件带生成签名（手改文件不会被覆盖） |
| `[SKIP] ... no UVM simulator` | 未装 vlog/vcs；门禁仅报告不阻断 |
| 想看去哪看校验报告 | `generated/schema_report.txt`（schema）与 `generated/validation_report.txt`（语义） |
| `sb_type` 填参数化类（如 `in_order_scoreboard`）编译报错 | 参数化类无工厂注册；手写子类特化成具名类（见场景 3） |
| 代码里用了 `algorithm_scoreboard` / `typed_scoreboard` / `multich_*` 编译报错 | 这些分片已从 `scb_pkg` 下线；改用 `in_order_scoreboard` / `out_of_order_scoreboard`，或手写子类扩展 |
| `scb_pkg.sv` 未找到或编译错误 | 检查 filelist.f 或 Makefile 中是否正确引用 `$(BASE_PKG)/scb/scb_pkg.sv`；`scb_pkg` 是顶层组装文件，不包含分片 |
| `_typedefs_pkg.sv` 找不到 | 检查 filelist：`common_typedefs_pkg.sv` → `<name>_parameters_pkg.sv` → `<name>_typedefs_pkg.sv` 顺序必须成立（typedefs pkg 会 import 参数包） |

---

## 相关文档

- [readme.md](readme.md) — 功能清单 / 字段全解 / 模板结构 / 输出说明
- [examples/](examples/) — APB 全链路示例（5 个 YAML + 测试点 xlsx）
- `base_pkg/` — 内置基础包：`clk_and_rst`（时钟复位 VIP）+ `scb`（计分板组件族 `scb_pkg`）
  + `common_typedefs`（公共类型 `common_typedefs_pkg`）
- [schema/uvm_config.schema.json](schema/uvm_config.schema.json) — YAML 配置契约（JSON Schema）
- `prompt.md` — Agent 集成说明
- `templates/sc_pred_templates/` — rtl_sc 监控器/产生器模板（mon_ex、prod、sc_pred_env）

以上路径均相对于 tool_uvm 目录（本文件所在目录）。
