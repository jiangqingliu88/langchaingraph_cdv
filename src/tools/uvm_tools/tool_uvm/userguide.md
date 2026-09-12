# tool_uvm 用户指南（User Guide）

从 YAML 描述符生成完整 UVM SystemVerilog 验证环境。本指南按「场景」组织：
每个场景给出目标、YAML 要点、命令、预期产物。CLI 参数速查见文末表格。

> 依赖：Python ≥3.10 <3.13、pyyaml、jinja2、jsonschema。
> 完整字段说明见 [readme.md](readme.md)，示例在 `examples/`（APB 全链路）。

## 重要变更（2026-09）

1. **scb_pkg 结构重组**：`scb_pkg.sv` 现为顶层组装文件，组件分片（`.svh`）通过
   `+incdir` 引用，不再在 filelist 中列出。生成代码编译时只需编译 `scb_pkg.sv`。
2. **algorithm_scoreboard 虚类化**：按 UVM LRM 8.21 规范，算法计分板声明为
   `virtual class`，不可直接实例化，必须子类化后使用。
3. **新增 rtl_sc 功能**：提供监控器（mon_ex）和产生器（prod）模板，用于
   Scoreboard Predictor 机制，生成轻量级寄存器级预测组件。

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
python -m src.tools.uvm_tools.tool_uvm.main -i examples/ -d generated/

# 等价：显式列文件
python -m src.tools.uvm_tools.tool_uvm.main -i examples/apb_interface.yaml \
    examples/apb_env.yaml examples/apb_bench.yaml examples/apb_constraint.yaml \
    examples/apb_util_comp.yaml -d generated/
```

预期输出（AXI-VIP 风格编号分层）：

```
generated/
├── agents/APB_agent/
│   ├── 1_interface/   APB_if.sv / APB_system_if.sv
│   ├── 2_config/      port_config（单类，port_kind 区分 MASTER/SLAVE）
│   ├── 3_transaction_sequencer/  seq_item + sequencer
│   ├── 4_driver_monitor/  driver + port_monitor（单类）
│   ├── 5_agent/       agent + system_config + system_monitor + system_env
│   ├── 7_sequence/    master/slave sequence
│   ├── 8_ral/         reg_adapter
│   ├── APB_pkg.sv / filelist.f / Makefile
│   └── loopback/      自闭环自检（master-drive → slave-monitor）
├── env/     config / env / coverage / pkg / tests / seqs / cons / utils
│   ├── rtl_sc/        # Scoreboard Predictor（监控器 + 产生器 + 环境类）
│   │   ├── APB_env_rtl_sc.sv
│   │   ├── {{point}}_mon_ex.sv
│   │   └── {{point}}_prod.sv
├── bench/   tb_top + harness
├── Makefile  整环境双后端编译/仿真入口（env + agents + bench）
├── schema_report.txt / validation_report.txt / generation_report.json
└── README.md
```

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

`apb_interface.yaml` 要点：

```yaml
interfaces:
  - name: APB                # 类前缀 apb_
    protocol: apb            # 协议名 → 渲染两拍 setup+access 默认时序（可留空=单拍）
    reset_active_low: True
    parameters:              # 渲染进 interface #(...)
      - { type: int, name: ADDR_WIDTH, value: 32 }
    ports:                   # dir: output=master驱动 / input=slave驱动
      - { name: paddr, dir: output, width: ADDR_WIDTH }
      - { name: prdata, dir: input,  width: DATA_WIDTH }
    transaction_vars:        # 事务字段：isrand 驱动 / iscompare 参与自检比对 / is_master 角色
      - { name: paddr, type: "bit [ADDR_WIDTH-1:0]", iscompare: "True", isrand: "True", is_master: "True" }
```

> 激活模式（UVM_ACTIVE / UVM_PASSIVE）**不在 interface 级配置**：interface 只描述协议与端口，
> 激活由 env 级 `agents[].is_active` 决定（缺省 UVM_ACTIVE）；loopback 自检套件固定
> master-ACTIVE / slave-PASSIVE。写 interface 级的 `is_active`（含旧路径
> `config.is_active`）会被 schema 判为未知键 / 已下线字段而报错。

```bash
python -m src.tools.uvm_tools.tool_uvm.main -i apb_interface.yaml -d generated/
```

---

## 3. 场景：多 agent 环境（env + scoreboard + predictor + TLM）

**目标**：聚合多个 agent 实例 + 参考模型 + 计分板 + 显式 TLM 连接。

`apb_env.yaml` 要点：

```yaml
environment:
  name: APB_env
  agents:                       # 每项 = 一个 agent 实例（引用 interface 级定义）
    - name: apb_master
      type: "apb_master_agent"
      is_active: True
      is_master: True
      interface: apb
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

多文件输入：`-i apb_interface.yaml apb_env.yaml -d generated/`（跨文件自动关联）。

### scoreboards 的两种接法

| 接法 | YAML 要点 | 产物 |
|------|-----------|------|
| 外部类（UVMF 风格） | `sb_type` + `trans_type` | 不生成文件，env 直接例化 `sb_type` 指定的类（VIP 自带或用户自建） |
| 生成式 | `mode` + `expected_from` / `actual_from` | `env/scb/{name}.sv` 自包含计分板（imp/FIFO/比对/check 裁决齐全） |

```yaml
scoreboards:
  # 外部类：sb_type 须为工厂可注册的具名类（有 uvm_component_utils）
  - name: apb_scb
    sb_type: uvmf_in_order_scoreboard
    trans_type: apb_master_seq_item
  # 生成式：按端口表达式自动推断 item_type，产物 env/scb/apb_scb_gen.sv
  - name: apb_scb_gen
    mode: inorder            # inorder | outoforder
    expected_from: apb_pred  # 预期侧来源（predictor / agent 名）
    actual_from: apb_slave   # 实际侧来源（monitor 所在 agent 名）
    key_field: req_id        # outoforder 的 ID 关联字段
```

### 内置计分板组件族（base_pkg/scb → scb_pkg）

整环境编译链自动包含 `base_pkg/` 两个基础包（filelist/Makefile 只编译包文件，
分片经 `+incdir` 解析，与 `clk_and_rst_pkg` 同构）：`clk_and_rst_pkg`（时钟复位
VIP）与 `scb_pkg`（计分板组件族）。`scb_pkg` 是自定义计分板的开发基座：

**重要**：`scb_pkg.sv` 是顶层组装文件，只编译一个文件；各组件分片（`.svh`）通过
`+incdir` 引用，无需在 filelist 中列出所有分片。

| 组件 | 参数 | 用途 |
|------|------|------|
| `comparator` / `default_comparator` | `#(T)` | 比较器虚接口 + 默认实现（可注入自定义比较器） |
| `in_order_scoreboard` | `#(REQ_T, RSP_T, CMP_T)` | 顺序计分板基座：expected/actual 双 imp，严格/非严格比对 |
| `out_of_order_scoreboard` | `#(T, ID_T, CMP_T)` | 乱序计分板：按事务 ID 关联匹配（重载 `get_id()`） |
| `multi_channel_scoreboard` | `#(T, CMP_T, N)` | 多通道顺序：通道 0 = 预期，1..N-1 = 实际 |
| `multi_channel_out_of_order_scoreboard` | `#(T, ID_T, CMP_T, N)` | 多通道乱序（ID 关联） |
| `typed_scoreboard` | `#(T)` | 单类型便捷类（REQ_T = RSP_T = T） |
| `algorithm_scoreboard` | `#(REQ_T, RESP_T)` | 算法计分板（**虚类**）：实现 `predict()` 即内嵌参考模型 |

全部组件自带统计与 `check_phase` 裁决（mismatch / missing / extra > 0 →
`uvm_error`，仿真判 FAIL）。

**消费方式**：参数化类不能直接当 `sb_type` 用（无工厂注册），先特化出具名类——
放在自有 VIP 包或生成代码的手改区域均可（缺省不覆盖已存在文件，见场景 7/8）：

```systemverilog
import scb_pkg::*;

// 方式 1：一行宏特化（typedef + 子类工厂注册），之后 YAML 可 sb_type: apb_in_order_scb
`DEFINE_TYPED_SCOREBOARD(apb_in_order_scb, apb_master_seq_item,
                         apb_master_seq_item, default_comparator#(apb_master_seq_item))

// 方式 2：算法计分板——实现纯虚 predict()（请求 → 期望即时计算）
// 注意：algorithm_scoreboard 必须声明为 virtual class（按 LRM 8.21 规范）
class alu_algorithm_scb extends algorithm_scoreboard#(alu_seq_item, alu_seq_item);
  `uvm_component_utils(alu_algorithm_scb)
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
  virtual function alu_seq_item predict(alu_seq_item req);
    alu_seq_item exp = alu_seq_item::type_id::create("exp");
    exp.copy(req);
    exp.result = req.a + req.b;
    return exp;
  endfunction
endclass
```

**连接约定**（`tlm_connections` 的 `driver` / `receiver` 路径）：

| 组件 | 预期侧端口 | 实际侧端口 |
|------|-----------|-----------|
| in_order / typed / out_of_order | `expected_export` | `actual_export` |
| algorithm | `req_export`（请求侧） | `resp_export`（响应侧） |
| multi_channel* | `channel_export[0]` | `channel_export[1..N-1]` |

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

`rtl_sc` 是一种轻量级的计分板预测机制，通过模板生成监控器、产生器和集成环境类。

### 3.5.1 模板文件

生成目录会包含：
- `env/utils/{{name}}_sc_pred_env.sv` — 环境类，管理监控器和产生器
- `env/utils/{{point}}_mon_ex.sv` — 监控器模板（每个检查点）
- `env/utils/{{point}}_prod.sv` — 产生器模板（每个产生点）

### 3.5.2 使用方式

在环境 YAML 中添加 `rtl_sc_components` 字段：

```yaml
environment:
  name: APB_env
  rtl_sc_components:
    - name: apb_rtl_sc
      # 检查点：需要监控的输出端口
      check_points:
        - { point_name: apb_data, channel_num: 2, width: 32 }
      # 产生点：需要产生信号的端口（可选）
      prod_points:
        - { point_name: apb_addr, channel_num: 2, width: 32 }
      # 环境配置
      config:
        ut_id: 1
        has_prod: 1
```

### 3.5.3 生成流程

1. 生成监控器和产生器类模板
2. 生成环境包装类（包含生产者和消费者数组）
3. 自动配置 `reg_{{point}}_t`（寄存器抽象层）
4. 在 `build_phase` 中实例化并连接组件

### 3.5.4 组件说明

| 组件 | 类名 | 功能 |
|------|------|------|
| 环境类 | `{{name}}_sc_pred_env` | 管理 mon_ex 和 prod 数组，配置连接 |
| 监控器 | `{{point}}_mon_ex` | 采样接口信号，输出到 analysis_port |
| 产生器 | `{{point}}_prod` | 产生预测信号，输入到 Scoreboard Predictor |

### 3.5.5 工作流程

```
DUT 信号
  → vif（虚拟接口）
    → {{point}}_mon_ex（采样） → mon_ex_port（analysis_port）
      → sc_pred_env（注册检查点） → rtl_sc_register（状态追踪）
    → {{point}}_prod（产生预测） → prod_port（analysis_port）
      → sc_pred_env（注册产生点） → rtl_sc_predict（预测逻辑）
        → Scoreboard Predictor（比较预期/实际）
```

### 3.5.6 配置项

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | string | 必填 | 环境类前缀 |
| `check_points` | array | 必填 | 检查点列表（监控点） |
| `prod_points` | array | 空 | 产生点列表（可选） |
| `channel_num` | int | 1 | 通道数量（多路监控） |
| `width` | int | 必填 | 位宽（匹配 DUT 端口） |
| `ut_id` | int | 0 | 用户 ID（用于区分实例） |
| `has_prod` | bit | 1 | 是否启用产生器 |

---

## 4. 场景：bench + harness（bind 式自连接）

**目标**：tb_top 例化 clk_rst + DUT，harness 以 bind 方式把 interface 连到 DUT。

```bash
python -m src.tools.uvm_tools.tool_uvm.main -i apb_bench.yaml -d generated/
```

`apb_bench.yaml` 要点（harness 推荐写在 bench 内，存在时 tb_top 自动跳过接口实例化）：

```yaml
bench:
  name: APB_bench
  timeout: 10ms
  clk_rst:
    clocks: [{ name: pclk }]        # 也可裸字符串 ["pclk"]
    resets: [{ name: presetn }]
  harness:
    name: apb_harness
    bind_to: apb_slave_dut          # bind 目标 module（所有实例生效）
    interfaces:
      - name: apb_if
        type: apb_interface
        agent_path: "apb_master_agent_h"
        connections: { pclk: pclk, paddr: paddr }   # 端口 → DUT 信号
```

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

`apb_constraint.yaml` 要点：

```yaml
constraint:
  name: apb_cons
  env_name: APB_env
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
python -m src.tools.uvm_tools.tool_uvm.main -i examples/ -d generated/

# 强制覆盖
python -m src.tools.uvm_tools.tool_uvm.main -i examples/ -d generated/ -o

# 只生成指定组件（按 name 过滤）
python -m src.tools.uvm_tools.tool_uvm.main -i examples/ -d generated/ -g APB

# 静默（CI 用）
python -m src.tools.uvm_tools.tool_uvm.main -i examples/ -d generated/ -q
```

---

## 8. 场景：手改代码合并（auto-merge）

**目标**：模板升级后，把旧生成代码里手改的 pragma custom 区域合并进新生成代码。

```bash
# 从 hand_edited_src/ 提取手改区域合并（自动备份 <目录>_backup_<时间戳>）
python -m src.tools.uvm_tools.tool_uvm.main -i apb_env.yaml -d generated/ -m hand_edited_src/

# 旧源有无法映射的块时继续（默认报错中止）
python -m src.tools.uvm_tools.tool_uvm.main -i apb_env.yaml -d generated/ -m hand_edited_src/ -s

# 不备份 / 输出未合并中间产物（调试）
python -m src.tools.uvm_tools.tool_uvm.main -i apb_env.yaml -d generated/ -m hand_edited_src/ \
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
python -m src.tools.uvm_tools.tool_uvm.main -i my.yaml -d generated/
#  → Schema validation failed: 2 error(s), 0 warning(s) — see .../schema_report.txt
#  → [ERROR] unknown_property @ my.yaml::interfaces[0].reset_active_loww: 未知键 ...

# 逃生舱：旧 YAML 触发 schema error 又需继续生成时跳过 Phase 0
python -m src.tools.uvm_tools.tool_uvm.main -i my.yaml -d generated/ --skip-schema-check
```

### 10.2 独立检查命令（不生成，纯校验）

```bash
# 单文件 / 目录 / 多个文件（位置参数或 -i）
python -m src.tools.uvm_tools.tool_uvm.schema_check my.yaml
python -m src.tools.uvm_tools.tool_uvm.schema_check -i examples/ -q

# 报告落盘 / 自定义 schema 文件
python -m src.tools.uvm_tools.tool_uvm.schema_check -i examples/ --report /tmp/schema_report.txt
python -m src.tools.uvm_tools.tool_uvm.schema_check -i examples/ --schema my_schema.json
```

- 严重度：**全部违规 → `error`**，包括未知键/多余字段（`unknown_property`）——
  拼错的键会被 normalizer 静默吞掉，故不做「仅警告」放行
- 退出码：有 error → 1；无 error → 0（CI 可直接用）
- 报错定位到路径：`my.yaml::interfaces[0].ports[0].dir` 形式
- schema 契约文件：`schema/uvm_config.schema.json`（Draft 2020-12，含全部旧键名别名，
  可被编辑器/IDE 直接复用做实时校验）

---

## 11. 场景：语义校验与报告

**目标**：拦截「生成合法但行为错误」的跨字段问题（端口↔事务字段、TLM 引用、
覆盖率 cross 字段等）。

- error → 阻断生成；warning → 不阻断，继续生成
- 报告落盘 `generated/validation_report.txt`，规则清单可用 `SemanticValidator.rules_doc()` 导出
- 无需额外参数，生成时自动执行（Phase A）

---

## 12. 场景：编译仿真门禁（--gate）

**目标**：生成后对每个 agent 的 loopback 自检跑编译 + 仿真，快速确认生成代码可编译。

```bash
python -m src.tools.uvm_tools.tool_uvm.main -i examples/ -d generated/ --gate
#  [PASS] APB_agent (sim=0)     ← 检测到 vlog/vsim 或 vcs
#  [SKIP] APB_agent — no UVM simulator (vlog/vcs) found   ← 无仿真器仅跳过，不阻断
```

---

## 13. 场景：签核证据包（--report-json）

**目标**：结构化生成报告供 Agent 决策 / 签核证据包引用（`generation_report.json`）。

```bash
python -m src.tools.uvm_tools.tool_uvm.main -i examples/ -d generated/ --report-json --gate
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
python -m src.tools.uvm_tools.tool_uvm.main -c -d generated/

# 列出支持的模板集
python -m src.tools.uvm_tools.tool_uvm.main --list-templates

# 版本
python -m src.tools.uvm_tools.tool_uvm.main --version
python -m src.tools.uvm_tools.tool_uvm.schema_check --version
```

---

## CLI 参数速查

### gen_uvm（生成命令）

| 参数 | 说明 |
|------|------|
| `-i/--input PATH...` | 输入 YAML 文件或目录（缺省 `.`）；`-f/--file` 同义 |
| `-d/--dest_dir DIR` | 输出目录（缺省 `generated`） |
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
| `[ERROR] unknown_property ... 'xxx'` | 键名拼错或字段已下线（如 interface 级 `is_active`）；删掉或改成正确键名 |
| `[ERROR] removed_field ... interfaces[N].config` | 旧路径 `config.is_active` 已下线；激活改由 env 级 `agents[].is_active` 配置 |
| 生成文件没有更新 | 缺省跳过已存在文件；用 `-o` 覆盖，或确认文件带生成签名（手改文件不会被覆盖） |
| `[SKIP] ... no UVM simulator` | 未装 vlog/vcs；门禁仅报告不阻断 |
| 想看去哪看校验报告 | `generated/schema_report.txt`（schema）与 `generated/validation_report.txt`（语义） |
| `sb_type` 填参数化类（如 `in_order_scoreboard`）编译报错 | 参数化类无工厂注册；先用 `DEFINE_TYPED_SCOREBOARD` 特化或手写子类成具名类（见场景 3） |
| `algorithm_scoreboard` 实例化报错 "instantiation of abstract class" | algorithm_scoreboard 必须声明为 virtual class（按 LRM 8.21），不能直接实例化；必须子类化后实例化（见场景 3） |
| `scb_pkg.sv` 未找到或编译错误 | 检查 filelist.f 或 Makefile 中是否正确引用 `$(BASE_PKG)/scb/scb_pkg.sv`；`scb_pkg` 是顶层组装文件，不包含分片 |

---

## 相关文档

- [readme.md](readme.md) — 功能清单 / 字段全解 / 模板结构 / 输出说明
- [examples/](examples/) — APB 全链路示例（5 个 YAML + 测试点 xlsx）
- `base_pkg/` — 内置基础包：`clk_and_rst`（时钟复位 VIP）+ `scb`（计分板组件族 `scb_pkg`）
- [schema/uvm_config.schema.json](schema/uvm_config.schema.json) — YAML 配置契约（JSON Schema）
- `prompt.md` — Agent 集成说明
- `templates/sc_pred_templates/` — rtl_sc 监控器/产生器模板（监控器模板 mon_ex、产生器模板 prod、环境类模板 sc_pred_env）
