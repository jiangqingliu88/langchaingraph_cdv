# {{ module }} UVM 验证环境搭建计划（代码搭建蓝图）

> **文档版本**：`{{ build_version }}`（Code Skeleton Only）
> **日期**：`{{ date }}`
> **适用 DUT**：`{{ rtl_top }}`
> **参考框架**：{{ reference_framework }}
> **验证计划**：[plan.md](plan.md)
> **环境架构**：[envarch.md](envarch.md)

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| {{ build_version }} | {{ date }} | {{ author }} | {{ change_note }} |

## Table of Contents

- [第 0 章 文档定位与范围](#第-0-章-文档定位与范围)
- [第 1 章 前置决策冻结](#第-1-章-前置决策冻结)
- [第 2 章 RTL 接口与子模块速查](#第-2-章-rtl-接口与子模块速查)
- [第 3 章 目录结构与文件清单](#第-3-章-目录结构与文件清单)
- [第 4 章 复用清单](#第-4-章-复用清单)
- [第 5 章 Package 与公共类型](#第-5-章-package-与公共类型)
- [第 6 章 Interface 清单](#第-6-章-interface-清单)
- [第 7 章 Agent 骨架](#第-7-章-agent-骨架)
- [第 8 章 Env 层骨架](#第-8-章-env-层骨架)
- [第 9 章 Top 层与 SVA](#第-9-章-top-层与-sva)
- [第 10 章 Covergroup 落点](#第-10-章-covergroup-落点)
- [第 11 章 Test 基类](#第-11-章-test-基类)
- [第 12 章 编译与运行](#第-12-章-编译与运行)

---

## 第 0 章 文档定位与范围

### 0.1 本文档是什么

`{{ module }}` UVM 环境的**代码骨架蓝图**：目录、package、interface、agent、env、top、SVA、covergroup、test、编译/运行命令。
本文档只给结构与签名，不含测试点 / 覆盖率目标 / 回归 / 签核结论 —— 那些在 `plan.md` / `report.md` / `signoff.md`。

### 0.2 本文档不是什么

- 不是功能规格书（见 `{{ spec_doc }}`）
- 不是验证计划（见 `plan.md`）
- 不替代 `casemodel.yaml` / `case_ir.json` 的契约

### 0.3 阅读对象

验证工程师、设计工程师、环境集成者。

---

## 第 1 章 前置决策冻结

### 1.1 工具链与方法学

| 项 | 值 |
|---|---|
| 语言 | SystemVerilog |
| 方法学 | UVM {{ uvm_version }} |
| 仿真器 | {{ simulator }} |
| 波形 | {{ waveform_tool }} |
| 覆盖率 | {{ coverage_tool }} |

### 1.2 Agent 划分（冻结）

| Agent | Interface | 方向 | Seq Item | 说明 |
|---|---|---|---|---|
| {{ agent.name }} | `{{ agent.iface }}` | {{ agent.direction }} | `{{ agent.seq_item }}` | {{ agent.description }} |

### 1.3 与参考框架的对位

| 参考框架组件 | 本环境对应 | 备注 |
|---|---|---|
| {{ ref.component }} | {{ local.component }} | {{ ref.note }} |

---

## 第 2 章 RTL 接口与子模块速查

### 2.1 顶层互联

{{ top_interconnect }}

### 2.2 子模块参数冻结

| 子模块 | 参数 | 值 | 说明 |
|---|---|---|---|
| `{{ submodule }}` | `{{ param }}` | `{{ value }}` | {{ description }} |

### 2.3 关键 FSM

| FSM | 状态 | 迁移 | 覆盖点 |
|---|---|---|---|
| {{ fsm.name }} | {{ fsm.states }} | {{ fsm.transitions }} | {{ fsm.coverage }} |

### 2.4 端口分组 → Agent 映射

| 端口组 | Agent | 说明 |
|---|---|---|
| {{ port_group }} | `{{ agent }}` | {{ description }} |

### 2.5 关键 CSR / 配置位

| 寄存器 / 位 | 作用 | 覆盖 / 检查 |
|---|---|---|
| `{{ csr.name }}` | {{ csr.role }} | {{ csr.check }} |

---

## 第 3 章 目录结构与文件清单

### 3.1 目录树

```text
{{ module }}/
├── rtl/
├── testbench/
│   ├── common/
│   ├── interfaces/
│   ├── agents/
│   │   └── {{ agent.name }}/
│   ├── env/
│   ├── top/
│   ├── test/
│   └── sva/
├── sim/
└── regress/
```

### 3.2 命名规范

- package：`{{ module }}_<domain>_pkg.sv`
- interface：`<agent>_if.sv`
- agent：`<agent>_agent.svh` / `<agent>_driver.svh` / `<agent>_monitor.svh` / `<agent>_sequencer.svh` / `<agent>_seq_item.svh`
- env：`{{ module }}_env.svh` / `{{ module }}_env_cfg.svh`
- test：`{{ module }}_test_base.svh` / `test_<name>.svh`

### 3.3 文件统计

| 类别 | 数量 |
|---|---:|
| Interface | {{ iface_count }} |
| Agent | {{ agent_count }} |
| Package | {{ pkg_count }} |
| Test | {{ test_count }} |
| SVA | {{ sva_count }} |

---

## 第 4 章 复用清单

### 4.1 dv_utils 复用

| 模块 | 用途 |
|---|---|
| `{{ util.name }}` | {{ util.purpose }} |

### 4.2 scripts 复用

| 脚本 | 用途 |
|---|---|
| `{{ script.name }}` | {{ script.purpose }} |

### 4.3 Makefile 关键变量

```make
UVM_HOME   ?= {{ uvm_home }}
SIMULATOR  ?= {{ simulator }}
WORK       ?= {{ work_lib }}
COV_FLAG   ?= {{ cov_flag }}
```

---

## 第 5 章 Package 与公共类型

### 5.1 `{{ module }}_params_pkg.sv`

```systemverilog
package {{ module }}_params_pkg;
  // 参数、typedef、enum
endpackage
```

### 5.2 `{{ module }}_common_pkg.sv`

```systemverilog
package {{ module }}_common_pkg;
  `include "uvm_macros.svh"
  import uvm_pkg::*;
  // 公共 transaction / cfg / utils
endpackage
```

### 5.3 包导入依赖

```text
{{ pkg_dependency_graph }}
```

---

## 第 6 章 Interface 清单

| Interface | 方向 | 时钟 | 复位 | 文件 |
|---|---|---|---|---|
| `{{ iface.name }}` | {{ iface.direction }} | `{{ iface.clock }}` | `{{ iface.reset }}` | `{{ iface.file }}` |

```systemverilog
interface {{ iface.name }} (
  input logic {{ iface.clock }},
  input logic {{ iface.reset }}
);
  // signals / clocking block / modport
endinterface
```

---

## 第 7 章 Agent 骨架

| Agent | Seq Item | Driver | Monitor | Sequencer | 说明 |
|---|---|---|---|---|---|
| `{{ agent.name }}` | `{{ agent.seq_item }}` | `{{ agent.driver }}` | `{{ agent.monitor }}` | `{{ agent.sequencer }}` | {{ agent.description }} |

```systemverilog
class {{ agent.name }}_agent extends uvm_agent;
  `uvm_component_utils({{ agent.name }}_agent)
  // driver / monitor / sequencer / config
endclass
```

---

## 第 8 章 Env 层骨架

| 文件 | 职责 |
|---|---|
| `env/{{ module }}_env_pkg.sv` | include 顺序、import |
| `env/{{ module }}_env_cfg.svh` | 环境配置对象 |
| `env/{{ module }}_page_table_mem.svh` | 页表 / 存储模型（如需要） |
| `env/{{ module }}_ref_model.svh` | 参考模型（Pred） |
| `env/{{ module }}_scoreboard.svh` | 事务级 scoreboard |
| `env/{{ module }}_virtual_sequencer.svh` | virtual sequencer |
| `env/{{ module }}_vseq_lib.svh` | virtual sequences |
| `env/{{ module }}_env.svh` | 环境容器 |

**Pred / Scoreboard 接线**

```text
{{ in_agent }}_agent_ap    → {{ module }}_pred.in_export
{{ module }}_pred.out_port → {{ module }}_scb.expected_export
{{ out_agent }}_agent_ap   → {{ module }}_scb.actual_export
```

---

## 第 9 章 Top 层与 SVA

### 9.1 `top/{{ tb_top }}`

- 例化 DUT、interface、env、SVA bind
- `config_db` 设置 vif / cfg
- 时钟/复位生成

### 9.2 SVA 文件清单

| SVA 文件 | 绑定目标 | 断言类 |
|---|---|---|
| `{{ sva.file }}` | `{{ sva.bind_target }}` | {{ sva.class }} |

---

## 第 10 章 Covergroup 落点

### 10.1 黑盒 covergroup（agent 内）

| Agent | Covergroup | Coverpoint / Cross |
|---|---|---|
| `{{ agent }}` | `{{ cg.name }}` | {{ cg.points }} |

### 10.2 白盒 covergroup（env / bind）

| Covergroup | 采样源 | 说明 |
|---|---|---|
| `{{ cg.name }}` | `{{ cg.sample_source }}` | {{ cg.description }} |

### 10.3 覆盖率合并

```text
{{ cov_merge_config }}
```

---

## 第 11 章 Test 基类

### 11.1 `test/{{ module }}_test_base.svh`

```systemverilog
class {{ module }}_test_base extends uvm_test;
  `uvm_component_utils({{ module }}_test_base)
  // env / cfg / vseq 句柄
endclass
```

### 11.2 测试目录

{{ test_dirs }}

### 11.3 `+plusarg` 协议

| plusarg | 含义 | 默认 |
|---|---|---|
| `{{ plusarg }}` | {{ plusarg_meaning }} | {{ plusarg_default }} |

---

## 第 12 章 编译与运行

### 12.1 `Files.f` 编译顺序

```text
# === 基础 ===
{{ base_files }}
# === interfaces ===
{{ iface_files }}
# === agents ===
{{ agent_files }}
# === env ===
{{ env_files }}
# === tests ===
{{ test_files }}
# === SVA ===
{{ sva_files }}
# === DUT ===
{{ dut_files }}
# === tb_top ===
{{ top_files }}
```

### 12.2 Makefile target

```make
compile:
{{ compile_cmd }}

run:
{{ run_cmd }}

cov:
{{ cov_cmd }}
```

### 12.3 单测试运行

```bash
{{ single_test_cmd }}
```

### 12.4 Verdi

```bash
{{ verdi_cmd }}
```
