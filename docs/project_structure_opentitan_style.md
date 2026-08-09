# SignOffAI 项目目录 & 数据模型设计

> 日期：2026-08-09  
> 参考：OpenTitan `hw/ip/<name>/` 布局体系

---

## 1. 设计原则

```
OpenTitan 模式                        SignOffAI 适配
─────────────────────────────────     ──────────────────────────
doc/*.md       人写规格               doc/*.md       AI 生成的规格文档
data/*.hjson   机器可读元数据          data/*.hjson   AI 生成 + 签核追溯
dv/            手写 UVM 环境          dv/            AI 生成的 UVM 环境
dvsim_cfg.hjson 手写回归配置          dvsim_cfg.hjson AI 自动生成
checklist.md   人手签核清单           checklist.md   AI 生成 + 人工审批
```

---

## 2. 项目目录结构（SoC 层级仓库）

```
<repo_root>/                          ← SoC 仓库根（对标 OpenTitan）
│
├── .signoffai.yaml                   ← SoC 级 AI 生成策略
│
├── hw/                               ← === 硬件设计 ===
│   ├── ip/                           ← IP 模块库
│   │   ├── uart/                     ← UART IP（见 §2.2）
│   │   ├── dma/                      ← DMA IP
│   │   ├── gpio/                     ← GPIO IP
│   │   └── ...
│   │
│   ├── dv/                           ← 共享 DV 基础设施
│   │   ├── tools/dvsim/              ← dvsim 工具 + common_sim_cfg.hjson + common_modes.hjson
│   │   ├── sv/                       ← 共享 UVM agent（tl_agent, push_pull_agent, ...）
│   │   ├── dpi/                      ← DPI-C 共享库（uartdpi, spidpi, ...）
│   │   └── doc/                      ← DV 方法论文档
│   │
│   └── top_<soc_name>/               ← === SoC 顶层 ===
│       ├── data/
│       │   ├── top_<soc>.hjson       ← SoC 寄存器 + 引脚 + 时钟 spec
│       │   ├── chip_testplan.hjson   ← 芯片级验证计划（import 所有 IP testplan）
│       │   ├── chip_conn_testplan.hjson ← 连接性验证（每个 IP 的 clk/rst/bus/intr 连接）
│       │   └── ip/                   ← 每个 IP 在芯片级的集成 testplan
│       │       ├── chip_uart_testplan.hjson
│       │       ├── chip_dma_testplan.hjson
│       │       └── ...
│       │
│       ├── rtl/                      ← SoC 顶层 RTL（连线 + 顶层模块）
│       │   ├── top_<soc>.sv
│       │   └── ...
│       │
│       ├── dv/                       ← === SoC 级验证环境 ===
│       │   ├── chip_sim_cfg.hjson    ← 芯片级 dvsim 回归配置
│       │   ├── chip_smoketests.hjson ← 冒烟测试
│       │   ├── chip_rom_tests.hjson  ← ROM 测试
│       │   ├── env/                  ← 芯片级 UVM env
│       │   │   ├── chip_env.sv
│       │   │   ├── chip_env_pkg.sv
│       │   │   ├── chip_scoreboard.sv
│       │   │   ├── chip_virtual_sequencer.sv
│       │   │   └── seq_lib/          ← 芯片级 sequences (cross-IP scenarios)
│       │   │       ├── chip_sw_base_vseq.sv
│       │   │       ├── chip_sw_uart_tx_rx_vseq.sv
│       │   │       └── ...
│       │   ├── tb/
│       │   │   └── tb.sv
│       │   └── cov/                  ← 芯片级覆盖率
│       │       ├── chip_cover.cfg
│       │       └── ...
│       │
│       ├── cdc/                      ← SoC 级 CDC 检查
│       └── lint/                     ← SoC 级 Lint
│
├── sw/                               ← === 软件（可选，对标 OpenTitan SW 测试）===
│   └── device/tests/                 ← 固件级测试
│
├── doc/                              ← === 项目文档 ===
│   └── dv_methodology.md             ← DV 方法论
│
└── results/                          ← === 回归结果（gitignore）===
    └── latest/
        ├── sim_results.json
        ├── dashboard.html
        └── coverage.json
```

### 2.2 单个 IP 目录（`hw/ip/<name>/`）

```
hw/ip/<name>/
├── README.md
├── data/
│   ├── <name>.hjson                  ← IP 寄存器 spec（regtool 输入）
│   ├── <name>_testplan.hjson         ← IP 级验证计划
│   └── <name>_sec_cm_testplan.hjson  ← 安全对策 testplan
│
├── doc/
│   ├── theory_of_operation.md        ← 设计规格（人读）
│   ├── interfaces.md                 ← 接口文档
│   ├── registers.md                  ← 寄存器文档
│   ├── programmers_guide.md          ← 软件集成指南
│   └── checklist.md                  ← D1-D3 / V1-V3 签核清单
│
├── rtl/
│   ├── <name>.sv
│   ├── <name>_pkg.sv
│   ├── <name>_reg_pkg.sv             ← regtool 生成
│   └── <name>_reg_top.sv             ← regtool 生成
│
├── dv/
│   ├── <name>_sim_cfg.hjson          ← IP 级 dvsim 回归配置
│   ├── env/                          ← IP 级 UVM env
│   ├── tb/tb.sv
│   ├── tests/                        ← UVM tests
│   └── cov/<name>_cov_excl.el        ← 覆盖率排除
│
├── lint/<name>.vlt
└── syn/<name>_syn_cfg.hjson
```

### 2.3 需求层级 → 目录映射

```
Spec 中的需求层级   →   目录位置
─────────────────────────────────────────────
CHIP  (芯片级)      →   hw/top_<soc>/data/chip_testplan.hjson
ST    (系统级)      →   hw/top_<soc>/data/ip/chip_<ip>_testplan.hjson
IT    (集成级)      →   hw/top_<soc>/data/chip_conn_testplan.hjson
BT    (模块级)      →   hw/ip/<name>/data/<name>_testplan.hjson
UT    (单元级)      →   hw/ip/<name>/dv/env/seq_lib/<name>_<unit>_vseq.sv
```

---

## 3. 数据模型定义

### 3.1 `spec/spec.hjson` — 机器可读规格

```hjson
{
  // ── 基本标识 ──
  name: "apb_uart"
  human_name: "APB UART"
  one_line_desc: "APB-interfaced UART with 16-byte FIFO"
  one_paragraph_desc: '''
    Full-duplex UART with APB slave interface, supporting
    programmable baud rates (9600-115200), 8-bit data,
    configurable parity, and interrupt generation.
  '''

  // ── 版本管理 ──
  version: "1.0.0"
  design_stage: "D1"         // D1/D2/D3 (OpenTitan 设计阶段)
  verification_stage: "V1"   // V1/V2/V3 (OpenTitan 验证阶段)

  // ── AI 溯源 ──
  generated_by: "spec_planner"           // 哪个 Agent 生成
  source_doc: "specs/apb_uart_spec.md"   // 来源文档
  generation_run: "run_20260809_xxx"     // 哪次 run 生成
  human_reviewed: false                  // 是否经过人工审核

  // ── 时钟与复位 ──
  clocking: [{clock: "pclk", reset: "preset_n"}]

  // ── 总线接口 ──
  bus_interfaces: [
    {protocol: "APB", direction: "slave", data_width: 8, addr_width: 8}
  ]

  // ── 端口列表 ──
  available_input_list: [
    {name: "rx",      desc: "Serial receive input"}
  ]
  available_output_list: [
    {name: "tx",      desc: "Serial transmit output"},
    {name: "irq",     desc: "Interrupt output"}
  ]

  // ── 中断列表 ──
  interrupt_list: [
    {name: "tx_done",     desc: "TX FIFO emptied and last byte transmitted"},
    {name: "rx_ready",    desc: "RX FIFO has data available"},
    {name: "fifo_overflow", desc: "RX/TX FIFO overflow detected"},
    {name: "frame_err",   desc: "Framing error on receive"},
    {name: "parity_err",  desc: "Parity error on receive"}
  ]

  // ── 功能特性（从 spec 分析提取） ──
  features: [
    {
      id: "FEAT-TX-001"
      name: "uart_tx"
      description: "Serial transmission with start/stop/parity framing"
      priority: "P0"
      verification_stage: "V1"
    }
    {
      id: "FEAT-RX-001"
      name: "uart_rx"
      description: "Serial reception with configurable sampling"
      priority: "P0"
      verification_stage: "V1"
    }
    {
      id: "FEAT-FIFO-001"
      name: "fifo_management"
      description: "16-byte TX/RX FIFOs with watermarks and overflow detection"
      priority: "P1"
      verification_stage: "V2"
    }
    ...
  ]

  // ── 配置参数 ──
  parameters: [
    {name: "FIFO_DEPTH",  value: 16,  type: "int", desc: "TX/RX FIFO depth"},
    {name: "DATA_WIDTH",  value: 8,   type: "int", desc: "Data bits per frame"},
  ]

  // ── 性能目标 ──
  performance: {
    max_baud_rate: 115200
    apb_read_latency_cycles: 2
    interrupt_latency_cycles: 2
  }
}
```

### 3.2 `design/design_arch.hjson` — 设计架构

```hjson
{
  module_name: "apb_uart"
  version: "1.0.0"
  generated_by: "design_architect"
  generation_run: "run_20260809_xxx"

  // 功能层次树
  function_hier: {
    name: "UART_TOP"
    children: [
      {name: "TX",  children: [
        {name: "tx_shift_register"},
        {name: "tx_fsm"},
        {name: "tx_fifo"},
      ]}
      {name: "RX",  children: [
        {name: "rx_sampler"},
        {name: "rx_fsm"},
        {name: "rx_fifo"},
      ]}
      {name: "APB_REG", children: [
        {name: "apb_decoder"},
        {name: "reg_bank"},
      ]}
      {name: "INT", children: [
        {name: "int_controller"},
      ]}
      {name: "BAUD", children: [
        {name: "baud_divider"},
      ]}
    ]
  }

  // 寄存器映射
  registers: [
    {name: "BAUD_RATE",   offset: "0x00", width: 8, access: "RW", desc: "Baud rate config"}
    {name: "CTRL",        offset: "0x01", width: 8, access: "RW", desc: "Control register"}
    {name: "STATUS",      offset: "0x02", width: 8, access: "RO", desc: "Status register"}
    {name: "TX_DATA",     offset: "0x03", width: 8, access: "WO", desc: "TX FIFO write"}
    {name: "RX_DATA",     offset: "0x04", width: 8, access: "RO", desc: "RX FIFO read"}
    {name: "INT_EN",      offset: "0x05", width: 8, access: "RW", desc: "Interrupt enable"}
    {name: "INT_STATUS",  offset: "0x06", width: 8, access: "RO", desc: "Interrupt status"}
  ]

  // RTL 源码映射（如果提供 RTL）
  rtl_files: [
    {file: "rtl/apb_uart.sv",    hash: "sha256:xxx"}
    {file: "rtl/uart_tx.sv",     hash: "sha256:xxx"}
    {file: "rtl/uart_rx.sv",     hash: "sha256:xxx"}
    {file: "rtl/apb_reg.sv",     hash: "sha256:xxx"}
    {file: "rtl/fifo.sv",        hash: "sha256:xxx"}
  ]
}
```

### 3.3 `dv/dv_testplan.hjson` — 验证计划（对标 OpenTitan testplan）

```hjson
{
  name: "apb_uart"
  generated_by: "vplan_generator"
  generation_run: "run_20260809_xxx"

  // 复用公共 testplan（CSR/中断/告警/应力等标准测试）
  import_testplans: [
    "{proj_root}/hw/dv/tools/dvsim/testplans/csr_testplan.hjson",
    "{proj_root}/hw/dv/tools/dvsim/testplans/intr_test_testplan.hjson",
    "{proj_root}/hw/dv/tools/dvsim/testplans/stress_all_with_reset_testplan.hjson",
  ]

  // 自定义 testpoints
  testpoints: [
    {
      name: uart_smoke
      desc: '''
        Basic UART smoke test:
        - TX: program one byte, wait for completion, check serial waveform
        - RX: inject one serial byte, read register, compare
        - Scoreboard checks TX data == RX data
      '''
      stage: V1
      tests: ["uart_smoke"]
    }
    {
      name: uart_tx_rx_random
      desc: '''
        Random TX/RX transfer:
        - TX thread: keep writing random data when FIFO not full
        - RX thread: keep reading when FIFO not empty
        - Scoreboard compares all TX and RX data
      '''
      stage: V2
      tests: ["uart_tx_rx"]
    }
    {
      name: uart_baud_rates
      desc: '''
        Verify all standard baud rates:
        - 9600, 19200, 38400, 57600, 115200
        - Tolerance within +/-2%
        - Run 1000 transfers at each rate
      '''
      stage: V2
      tests: ["uart_tx_rx"]
    }
    {
      name: uart_parity
      desc: '''
        Even/odd parity verification:
        - Enable parity, send bytes with random parity
        - Inject parity errors on RX, verify interrupt
      '''
      stage: V2
      tests: ["uart_rx_parity_err", "uart_intr"]
    }
    {
      name: uart_fifo_watermark
      desc: '''
        FIFO watermark interrupt:
        - Program random watermark level
        - Fill FIFO past watermark, verify interrupt
        - Ensure interrupt stays asserted until cleared
      '''
      stage: V2
      tests: ["uart_tx_rx", "uart_intr"]
    }
    {
      name: uart_fifo_overflow
      desc: '''
        FIFO overflow behavior:
        - Send >32 bytes, ensure overflow flag + interrupt
        - Verify no data corruption in non-overflowed entries
      '''
      stage: V2
      tests: ["uart_fifo_overflow"]
    }
    {
      name: uart_stress_all
      desc: '''
        Combined stress:
        - TX + RX simultaneous at max baud rate
        - Random FIFO levels + parity + interrupt check
        - Run 10,000 total transfers
      '''
      stage: V2
      tests: ["uart_stress_all_with_rand_reset"]
    }
  ]

  // 功能覆盖率模型
  covergroups: [
    {
      name: uart_tx_cg
      desc: "TX functional coverage"
      coverpoints: [
        {name: "tx_baud_rate",    bins: [9600, 19200, 38400, 57600, 115200]}
        {name: "tx_parity",       bins: ["none", "even", "odd"]}
        {name: "tx_fifo_level",   bins: [0, 1, 8, 15, 16]}
        {name: "tx_frame_format", bins: ["start", "data", "parity", "stop"]}
      ]
    }
    {
      name: uart_rx_cg
      desc: "RX functional coverage"
      coverpoints: [
        {name: "rx_baud_rate",    bins: [9600, 19200, 38400, 57600, 115200]}
        {name: "rx_parity",       bins: ["none", "even", "odd"]}
        {name: "rx_fifo_level",   bins: [0, 1, 8, 15, 16]}
        {name: "rx_error_type",   bins: ["none", "parity", "frame", "overflow"]}
      ]
    }
    {
      name: uart_intr_cg
      desc: "Interrupt functional coverage"
      coverpoints: [
        {name: "intr_source", bins: ["tx_done", "rx_ready", "fifo_overflow", "frame_err", "parity_err"]}
        {name: "intr_enabled", bins: [true, false]}
        {name: "intr_cleared", bins: [true]}
      ]
    }
  ]

  // 覆盖率目标
  coverage_targets: {
    code_coverage:      {line: 95, branch: 90, toggle: 85, fsm: 100}
    functional_coverage: 100
    assertion_coverage:  100
  }
}
```

### 3.4 `dv/dv_sim_cfg.hjson` — dvsim 回归配置

```hjson
{
  name: "apb_uart"
  dut: "apb_uart"
  tb:   "tb"
  tool: "vcs"                      // 或 xcelium / verilator

  // RAL spec（寄存器模型生成）
  ral_spec: "{proj_root}/design/registers.hjson"

  // Testplan
  testplan: "{proj_root}/dv/dv_testplan.hjson"

  // 导入 OpenTitan 公共配置（build/run/coverage 基础设施）
  import_cfgs: [
    "{proj_root}/hw/dv/tools/dvsim/common_sim_cfg.hjson",
    "{proj_root}/hw/dv/tools/dvsim/common_modes.hjson",
    "{proj_root}/hw/dv/tools/dvsim/fusesoc.hjson",
    "{proj_root}/hw/dv/tools/dvsim/{tool}.hjson",
    "{proj_root}/hw/dv/tools/dvsim/tests/csr_tests.hjson",
    "{proj_root}/hw/dv/tools/dvsim/tests/intr_test.hjson",
    "{proj_root}/hw/dv/tools/dvsim/tests/stress_tests.hjson",
  ]

  sim_tops: ["apb_uart_bind"]

  // 默认值
  reseed: 10
  uvm_test: apb_uart_base_test
  uvm_test_seq: apb_uart_base_vseq

  // AI 生成的 test 列表
  tests: [
    {name: uart_smoke,         uvm_test_seq: uart_smoke_vseq}
    {name: uart_tx_rx,         uvm_test_seq: uart_tx_rx_vseq,         reseed: 50}
    {name: uart_rx_parity_err, uvm_test_seq: uart_rx_parity_err_vseq}
    {name: uart_fifo_overflow, uvm_test_seq: uart_fifo_overflow_vseq}
    {name: uart_intr,          uvm_test_seq: uart_intr_vseq,
     run_opts: ["+test_timeout_ns=3000000000"]}
    {name: uart_stress_all,    uvm_test_seq: uart_stress_all_vseq,
     run_opts: ["+test_timeout_ns=300000000000"], reseed: 20}
  ]

  // AI 生成的 regression 集
  regressions: [
    {name: smoke,    tests: ["uart_smoke"]}
    {name: nightly,  tests: ["uart_smoke", "uart_tx_rx", "uart_rx_parity_err",
                              "uart_fifo_overflow", "uart_intr", "uart_stress_all"]}
  ]
}
```

### 3.5 `.signoffai.yaml` — 项目元数据

```yaml
# ── 项目基本标识 ──
project:
  name: "apb_uart"
  description: "APB UART IP verification"
  created: "2026-08-09"

# ── LLM 配置覆盖 ──
llm:
  provider: "deepseek"
  model: "deepseek-chat"

# ── 生成策略 ──
generation:
  overwrite_existing: false        # 不覆盖已人工审核的文件
  require_human_review:            # 哪些产物需要人工审核
    - "spec/spec.hjson"
    - "dv/dv_testplan.hjson"
    - "signoff/signoff_report.md"
  auto_generate:                   # 哪些产物自动生成
    - "dv/env/*.sv"               # UVM 环境代码
    - "dv/tests/*.sv"             # UVM Test 代码
    - "dv/seq_lib/*.sv"           # UVM Sequence 代码

# ── 数据溯源 ──
provenance:
  enabled: true
  track_generation_run: true       # 记录每个文件由哪个 run 生成
  git_backed: true                 # 所有产物 Git 版本化

# ── dvsim 配置 ──
dvsim:
  tool: "vcs"                      # 默认工具
  proj_root_var: "proj_root"       # Hjson 中的项目根变量名
  common_cfg_dir: "hw/dv/tools/dvsim"  # 公共 dvsim 配置路径（从 OpenTitan 复制）
```

---

## 4. 数据流 & Agent 责任映射

```
┌─────────────────────────────────────────────────────────────────────┐
│ 阶段      产物                           Agent               格式     │
├─────────────────────────────────────────────────────────────────────┤
│ 1.spec    spec/spec.hjson              spec_planner          Hjson   │
│           spec/spec.md                 (从 hjson 渲染)        MD      │
│                                                                     │
│ 2.design  design/design_arch.hjson     design_architect      Hjson   │
│           design/registers.hjson       design_architect      Hjson   │
│                                                                     │
│ 3.model   model/ref_model.cpp          model_agent           C++     │
│           model/model.hjson            model_agent           Hjson   │
│                                                                     │
│ 4.vplan   dv/dv_testplan.hjson         vplan_generator       Hjson   │
│           dv/dv_testplan.md            (从 hjson 渲染)        MD      │
│                                                                     │
│ 5.UVM     dv/env/*.sv                  verification_architect SV     │
│           dv/tb/tb.sv                                           │
│           dv/tests/*.sv                                         │
│           dv/sva/*.sv                                           │
│                                                                     │
│ 6.test    dv/env/seq_lib/*.sv          test_engineer         SV      │
│           dv/dv_sim_cfg.hjson          dvsim_adapter         Hjson   │
│                                                                     │
│ 7.signoff dv/dv_checklist.md           quality_assurance     MD      │
│           signoff/signoff_report.md    report_generator      MD      │
│           signoff/evidence.zip         manifest              ZIP      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 5. 数据库模型映射

> 项目目录是文件系统表现，数据库是查询/溯源/协作的索引层。

| 文件 | 数据库表 | 关系 |
|------|----------|------|
| `spec/spec.hjson` | `doc_documents` (path+content) | 1 project : N documents |
| `spec/spec.hjson` | `doc_requirements` (extracted reqs) | 1 document : N requirements |
| `design/design_arch.hjson` | `design_modules` + `design_features` | 1 module : N features |
| `dv/dv_testplan.hjson` | `testpoints` + `covergroups` (via testplanner) | N testpoints : N tests |
| `dv/dv_sim_cfg.hjson` | `pipeline_runs` (dvsim 结果回流) | 1 run : N test results |
| `dv/dv_checklist.md` | `checklist_items` (D1-D3, V1-V3 status) | 1 item : 1 resolution |
| `signoff/signoff_report.md` | `signoffs` | 1 signoff : N evidence artifacts |

---

## 6. 与现有代码的迁移路径

```
现有 (SignOffAI)                   →  新结构 (OpenTitan 风格)
─────────────────────────────────     ─────────────────────────────
specs/apb_uart/apb_uart_spec.md      projects/apb_uart/spec/spec.hjson
                                       projects/apb_uart/spec/spec.md

output/demo_apb_uart/agents/         projects/apb_uart/dv/env/
output/demo_apb_uart/bench/          projects/apb_uart/dv/tb/
output/demo_apb_uart/env/            projects/apb_uart/dv/env/
output/demo_apb_uart/rtl/            projects/apb_uart/design/rtl/

src/tools/uvm_tools/                 (保持不变，工具层不改)
src/tools/dvsim/                     (保持不变，工具层不改)
src/tools/dvsim_adapter/             (新增：Hjson 生成器)
```

---

## 7. 一句话总结

> **复用 OpenTitan 的目录骨架（`data/*.hjson` + `doc/*.md` + `dv/` + `checklist.md`），把 SignOffAI 的 AI 生成能力嵌入每个环节，用 Hjson 做机器可读的"源"，用 Markdown 做人可读的"视图"，用 `.signoffai.yaml` 统一管理 AI 生成策略和溯源。**
