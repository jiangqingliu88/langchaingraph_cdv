# tool_uvm 用户指南（User Guide）

从 YAML 描述符生成完整 UVM SystemVerilog 验证环境。本指南按「场景」组织：
每个场景给出目标、YAML 要点、命令、预期产物。CLI 参数速查见文末表格。

> 依赖：Python ≥3.10 <3.13、pyyaml、jinja2、jsonschema。
> 完整字段说明见 [readme.md](readme.md)，示例在 `examples/`（APB 全链路）。

## 0. 校验链（生成流程的执行顺序）

```
YAML 输入
  → Phase 0  schema 语法检查   （键名/类型/必填/枚举；error 阻断，warning 落盘不阻断）
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
│   ├── 2_config/      port_config（单类，is_master_side 区分角色）
│   ├── 3_transaction_sequencer/  seq_item + sequencer
│   ├── 4_driver_monitor/  driver + port_monitor（单类）
│   ├── 5_agent/       agent + system_config + system_env
│   ├── 7_sequence/    master/slave sequence
│   ├── 8_ral/         reg_adapter
│   ├── APB_pkg.sv / filelist.f / Makefile
│   └── loopback/      自闭环自检（master-drive → slave-monitor）
├── env/     config / env / coverage / pkg / tests / seqs / cons / utils
├── bench/   tb_top + harness
├── schema_report.txt / validation_report.txt / generation_report.json
└── README.md
```

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
    is_active: { master: True, slave: True }   # 标量 / "UVM_ACTIVE" / {master,slave} 均可
```

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

回填优先级：YAML `custom_code`（非空）> merge 源手改内容 > 模板默认。

---

## 9. 场景：pragma custom 注入（协议时序自定义）

**目标**：不手改生成文件，用 YAML 注入自定义协议时序。

```yaml
interfaces:
  - name: APB
    custom_code:
      drive_logic: |
        // 自定义协议驱动时序
        repeat (2) @(vif.master_cb);
        vif.master_cb.penable <= 1'b1;
```

常用槽位：`field_decl` / `build_logic` / `connect_logic` / `drive_logic` /
`collect_logic` / `seq_body` / `run_logic`（详见 readme）。
旧字段 `custom_drive_logic` / `custom_sample_logic` / `custom_collect_logic`
等价于 `custom_code` 同名槽的缺省值。

---

## 10. 场景：YAML schema 语法检查

**目标**：在生成前拦截「键名拼错 / 类型写错 / 必填缺失 / 非法枚举」——这类错误
会被解析器静默吞掉（如缺 name/type 的 harness interface 条目被直接丢弃）。

### 10.1 生成流程内置（Phase 0，缺省开启）

```bash
# schema error → 阻断生成，报告落盘 schema_report.txt
python -m src.tools.uvm_tools.tool_uvm.main -i my.yaml -d generated/
#  → Schema validation failed: 2 error(s), 1 warning(s) — see .../schema_report.txt

# warning（拼错键等）→ 不阻断，仅提示 + 落盘
#  → Schema check: 1 warning(s) — see .../schema_report.txt

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

- 严重度：未知键 → `warning`；`required`/`type`/`enum`/文档类型 → `error`
- 退出码：有 error → 1；仅 warning → 0（CI 可直接用）
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
| `Schema validation failed: N error(s) ...` | YAML 违反 schema（必填/类型/枚举）；按报告修 YAML，或 `--skip-schema-check` 临时绕过 |
| `Schema check skipped (jsonschema not available)` | 缺依赖：`pip install jsonschema` |
| 生成文件没有更新 | 缺省跳过已存在文件；用 `-o` 覆盖，或确认文件带生成签名（手改文件不会被覆盖） |
| `[SKIP] ... no UVM simulator` | 未装 vlog/vcs；门禁仅报告不阻断 |
| 警告不阻断但想去哪看 | `generated/schema_report.txt`（schema）与 `generated/validation_report.txt`（语义） |
| 独立检查 exit=0 但打印 warning | 设计如此：仅 warning → exit 0（CI 门禁可只卡 error） |

---

## 相关文档

- [readme.md](readme.md) — 功能清单 / 字段全解 / 模板结构 / 输出说明
- [examples/](examples/) — APB 全链路示例（5 个 YAML + 测试点 xlsx）
- [schema/uvm_config.schema.json](schema/uvm_config.schema.json) — YAML 配置契约（JSON Schema）
- `prompt.md` — Agent 集成说明
