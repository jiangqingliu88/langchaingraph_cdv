# UVM 环境代码生成工具 (tool_uvm)

从 YAML 描述符自动生成完整的 UVM SystemVerilog 验证环境代码。

## Features
- 基于 Jinja2 模板的代码生成
- 支持 interface agent, environment, bench 三层
- Agent 回环测试环境自动生成
- 约束策略与序列生成
- 编译文件列表 (filelist) 生成
- **pragma custom 自定义代码区域**：细粒度语义槽（field_decl / build_logic / connect_logic /
  drive_logic / collect_logic / seq_body），slot 文件内唯一，回填优先级
  YAML `custom_code` > merge 源手改内容 > 模板默认
- **auto-merge 流程**（`-m/--merge_source`）：从指定目录提取手改区域合并进新生成代码，
  备份 / 缺失块报错（`-s` 跳过）/ 未合并调试输出 / 详细报告
- **bind 式 UVM Harness**（`harness:` YAML）：dummy interface + `set_vifs()` +
  `bind` 到 DUT module（按 module 名 bind，所有实例生效）；bind/inside 两种风格、
  interface 数组 + virtual interface foreach、参数化 scalable harness、virtual harness 子连接
- **统一文件头**（`templates/base_templates/base_template.sv.j2`，全部 53 个模板继承）：
  公司商标/权利声明、作者、创建时间、修改时间、联系邮箱、描述；
  YAML 顶层 `meta:` 可覆盖默认值；Makefile 自动用 `#` 注释前缀
- **语义校验层**（`semantic_check.py`）：渲染前拦截（error 阻断 / warning 落盘
  `validation_report.txt`），`@rule` 注册表 + 每规则一条测试（Phase B 约定）
- UVMF 风格 CLI：默认跳过已存在文件（`-o` 覆盖）、`-c` 清理、`-q` 静默、
  `-g` 指定组件、`-t` 模板目录、`--version`

## Key Classes
- `UVMGenerator`: 主生成器（Phase A 语义校验 → 渲染 → filelist → 报告）
- `JinjaRenderer`: 模板渲染引擎（`base_template` 文件头 + 商标/版权元数据）
- `YAMLLoader`: YAML 配置加载器
- `AgentModel`, `EnvironmentModel`, `BenchModel`, `HarnessModel`, `ConstraintModel`: 数据模型
- `RegionInjector`: pragma custom 区域注入器（YAML > merge 源 > 模板默认）
- `SemanticValidator`: 渲染前语义校验（`semantic_check.py`，`@rule` 注册）

## YAML Config Files
示例见 `examples/`（APB 全链路）：
- `apb_interface.yaml` — 接口定义（name/clock/reset/protocol/reset_active_low/ports/
  transaction_vars(带 is_master,iscompare,isrand)/transaction_constraints(master/slave)/custom_code）
- `apb_env.yaml` — 环境定义（agents(list)/subenvs/scoreboards(sb_type,trans_type)/
  analysis_components/analysis_exports/analysis_ports/register_model/harness_connect/
  coverage_crosses/tlm_connections）
- `apb_bench.yaml` — Bench 定义（clk_rst/wire_decls/agents/dut/harness/wave_dump/simulation）
- `apb_constraint.yaml` — 约束策略定义
- `apb_util_comp.yaml` — 工具组件（analysis 端口）
- `testpoint_apb.xlsx` — 测试点（`tool_uvmtestgen` 输入）

## Entry Point
```bash
# 生成 UVM 环境（-d/--dest_dir 指定输出目录；默认跳过已存在文件，-o 覆盖）
python -m src.tools.uvm_tools.tool_uvm.main -i ALU_env.yaml -d generated/

# 合并流程：从 hand_edited_src/ 提取 pragma custom 区域合并进新生成代码（自动备份）
python -m src.tools.uvm_tools.tool_uvm.main -i ALU_env.yaml -d generated/ -m hand_edited_src/

# 清理带生成签名的文件 / 列出模板 / 版本
python -m src.tools.uvm_tools.tool_uvm.main -c -d generated/
python -m src.tools.uvm_tools.tool_uvm.main --list-templates
python -m src.tools.uvm_tools.tool_uvm.main --version
```

### 自定义代码区域（pragma custom）

模板中的语义槽（slot 文件内唯一）：

| slot | 位置 | 说明 |
|------|------|------|
| `field_decl` | driver / monitor / seq_item 类体 | 新增成员声明 |
| `build_logic` | build_phase 末尾 | 附加构建逻辑 |
| `connect_logic` | env connect_phase 末尾 | 附加连接逻辑 |
| `drive_logic` | driver 驱动 task 内 | 协议驱动时序（缺省单拍驱动） |
| `collect_logic` | monitor 采样 task 内 | 帧采集逻辑（缺省逐字段采样） |
| `seq_body` | sequence / virtual_base_seq 类体 | 自定义序列 task |
| `run_logic` | test / virtual seq run 阶段 | 附加激励逻辑（objection 期间） |

YAML 注入（每次生成覆盖区域）：

```yaml
custom_code:
  drive_logic: |
    // 自定义协议时序
    repeat (2) @(vif.master_cb);
    vif.master_cb.penable <= 1'b1;
```

回填优先级：YAML `custom_code`（非空）> merge 源手改内容 > 模板默认。
旧字段 `custom_drive_logic` / `custom_collect_logic` 等价于 `custom_code` 同名槽的缺省值。

### UVM Harness（bind 式自连接，参考 CSDN hemlok/132674401）

```yaml
harness:
  name: apb_harness              # dummy interface 名
  bind_to: apb_slave_dut         # bind 目标 module 名（所有实例生效）
  style: bind                    # bind | inside
  # parameter: NUM_CLIENTS       # 可选：scalable harness（自适应 module parameter）
  interfaces:                    # 每个 interface 一项
    - name: apb_if               #   bind 实例名
      type: apb_interface
      agent_path: "apb_master_agent_h"   # config_db 目标（渲染 {path}.".<agent_path>.*"）
      connections: { pclk: pclk, presetn: presetn, paddr: paddr }
      # bind_to: 覆盖目标 module（缺省 = harness.bind_to）
      # source_path: 多实例层级路径（向上查找前缀，如 cache.memory）
      # count: 5 或参数名 → interface 数组 + virtual if 数组 + foreach set
  sub_harnesses:                 # 可选：virtual harness 批量连接
    - { path: "chip_module.math.harness", env_path: ".math_env" }
```

生成 `bench/<name>.sv`：bind 语句 + dummy interface（`set_vifs`）+ harness 自身 bind。
**推荐写在 bench YAML 内**（`bench.harness`，见 `examples/apb_bench.yaml`）——存在 harness 时
`tb_top` 自动跳过接口实例化与 `config_db` set（避免与 `set_vifs` 重复）。
测试侧连接：env YAML 里配 `harness_connect: {path: "APB_bench_tb_top.u_dut.harness", env_suffix: ".math_env0"}`，
`test_base` build_phase 自动渲染 `set_vifs(env.get_full_name())`。

## Output
```
generated/
├── agents/<name>_agent/        # AXI-VIP 风格编号分层
│   ├── 1_interface/  <name>_if.sv / <name>_system_if.sv
│   ├── 2_config/     <name>_master_config.sv / _slave_config.sv
│   ├── 3_transaction_sequencer/  seq_item + sequencer（slave 带 req_fifo）
│   ├── 4_driver_monitor/  driver + monitor（slave monitor → req_fifo）
│   ├── 5_agent/      agent + system_config + system_env
│   ├── 7_sequence/   master/slave sequence
│   ├── 8_ral/        reg_adapter
│   ├── <name>_pkg.sv / filelist.f / Makefile
│   └── loopback/     自闭环自检（master-drive → slave-monitor）
├── env/             # config / env / coverage / pkg / tests / seqs / cons / utils
├── bench/           # tb_top + harness
├── validation_report.txt / generation_report.json
└── README.md
```

## Consumed By
- `VerificationArchitect` agent

## Test
```bash
pytest src/tools/uvm_tools/tool_uvm/ -v
```
