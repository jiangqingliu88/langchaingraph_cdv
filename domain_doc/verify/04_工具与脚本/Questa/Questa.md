---
id: KB-DV-TOOL-002
title: Questa / ModelSim 的 vlog / vsim / vcover 命令速查与报错对号入座
type: 工具卡
domain: 工具与脚本
subdomain: Questa
tags: [Questa, 回归, 覆盖率]
roles: [DV工程师]
stages: [编码, 回归, 覆盖率]
summary: >
  用 Questa（或 ModelSim）跑一次「vlib → vlog/vcom → vsim → vcover」的
  最短命令链，以及编译/仿真/覆盖率三处的典型报错怎么确认与解决。
applicable: |
  用 Questa 或 ModelSim 起环境、编译报错对不上号、
  或要合并 ucdb 出覆盖率报告的时候。
not_applicable: |
  工具是 VCS —— 去 `../VCS/VCS.md`（命令体系完全不同）；
  工具是 Xcelium —— 去 `../Xcelium/`；
  想知道回归怎么编排、种子怎么管 —— 去 `../脚本与CI/回归流水线.md`。
prerequisites: []
references: []
related: []
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# Questa / ModelSim 的 vlog / vsim / vcover 命令速查

> **一句话**：Questa 的正常节奏是「先建库（vlib）→ 编进库（vlog/vcom）→ 从库里跑（vsim）→ 收覆盖率（vcover）」——
> **库（library）是 Questa 和 VCS 最大的手感差异**：一切都要先有库，编译是「往库里塞单元」。

## 干什么

Questa 是 Siemens 的仿真器（ModelSim 是它的同源老产品，命令体系基本一致），流程天然按「库」组织：

| 阶段 | 命令 | 干什么 | 产物 |
|---|---|---|---|
| **建库** | `vlib` / `vmap` | 在工作目录建一个物理库目录，并映射一个逻辑库名 | `work/` 之类的库目录 |
| **编译** | `vlog` / `vcom` | 把 SV/Verilog 或 VHDL 编成一个「设计单元」塞进库 | 库里的编译单元 |
| **仿真** | `vsim` | 从库加载顶层，跑一个 test | 日志、`vsim.wlf` 波形、`ucdb` 覆盖率 |
| **覆盖率** | `vcover` | 合并 / 报告 ucdb 覆盖率数据 | 合并后的 `.ucdb`、文本/HTML 报告 |

**「work」是一个逻辑库名，不是文件夹名。** `vmap work ./work` 把逻辑名 `work`
指到物理目录 `./work`；你可以在别的路径建库、给逻辑名换映射，
**回归里每跑一个 case 用独立库目录，是避免互相污染的关键**。

## 常用命令

### 1. 建库

```bash
vlib work
vmap work work
```

| 命令 | 在干什么 |
|---|---|
| `vlib work` | 在当前目录建物理库目录 `work/`（已存在则复用） |
| `vmap work work` | 把逻辑库名 `work` 映射到物理路径 `work`。**库名和路径不一致时必须显式做** |

### 2. 编译

```bash
# SystemVerilog
vlog -sv -work work \
     +incdir+./tb/include \
     +define+SIM \
     -lint \
     -f filelist.f \
     -l vlog.log

# VHDL
vcom -2008 -work work -f vhdl_files.f
```

| 开关 | 在干什么 |
|---|---|
| `-sv` | 允许 SystemVerilog（UVM 必需） |
| `-work work` | 编进哪个逻辑库 |
| `+incdir+<dir>` | 头文件搜索路径，**可重复给** |
| `+define+<M>` | 编译期宏 |
| `-lint` | 打开额外静态检查（未连接、隐式类型等） |
| `-f filelist.f` | 从文件读单元列表，回归里别手写 |
| `-l <log>` | 编译日志落文件 |

> 与 VCS 不同，Questa 的时间单位常靠源码里的 `` `timescale ``；缺了会告警。

### 3. 仿真

```bash
vsim -c -do "run -all; quit -f" \
     -sv_seed 12345 \
     -coverage \
     -gG_TEST_NAME=my_test \
     -wlf vsim.wlf \
     -l vsim.log \
     work.tb_top
```

| 参数 / 开关 | 在干什么 |
|---|---|
| `-c` | 命令行批处理模式（回归必需；不带就开 GUI） |
| `-do "run -all; quit -f"` | 跑完自动退出，**不加就挂在那等人敲命令，回归卡死** |
| `-sv_seed <N>` | **SystemVerilog 随机种子** —— Questa 复现的关键，必记 |
| `-coverage` | 打开覆盖率收集 |
| `-g<NAME>=<v>` | 传 VHDL generic / SV `$value$plusargs` 参数（针对编译期宏用 `vlog +define+`） |
| `-wlf vsim.wlf` | 波形数据库文件名 |
| `-voptargs="+acc"` | 保留可访问性，**调波形/读内部信号时的常用补救**（见下） |
| `work.tb_top` | `库名.顶层单元名` —— 注意这个点号，不是文件名 |

**批处理下的 `-do`**：回归脚本里几乎都要 `run -all`。
若要在特定时刻停/做检查，写成 `-do "run 1us; examine ...; run -all; quit -f"`。

### 4. 覆盖率

```bash
# 合并多个 case 的 ucdb
vcover merge merged.ucdb case1.ucdb case2.ucdb case3.ucdb

# 出文本报告
vcover report -details -output report.txt merged.ucdb

# 出 HTML 报告
vcover report -html -htmldir cov_html merged.ucdb
```

| 开关 | 在干什么 |
|---|---|
| `vcover merge` | 把多个 `.ucdb` 合并成一份，**与 VCS 的 `urg -dir` 对应** |
| `-details` | 报告里列出每个 bin / 每条语句，不只是汇总百分比 |
| `-html -htmldir` | 出 HTML，便于分享 |
| `-assert` | 报告 SVA 覆盖率 |
| `-code sbtcef` | 指定代码覆盖率度量集合（语句/分支/条件/表达式/FSM） |
| `-threshold` | 只列低于门槛的项，**抓漏洞时比翻全报告快** |

## 常见报错与解法

| 报错文本特征 | 出自 | 含义 |
|---|---|---|
| `** Error: (vlog-XXXX)` | 编译 | 语法 / 单元定义错 |
| `** Warning: (vlog-XXXX)` | 编译 | 推断、`-lint` 命中 —— **latch 推断在这**
| `Fatal: (vsim-XXXX)` | 仿真 | 运行期致命错误 |
| `Error: (vsim-XXXX)` | 仿真 | 运行期错误（可继续，常被 UVM 汇总） |
| `# ** Fatal: (vsim-XXXX)` | 仿真 | 带仿真时间的致命错误，前面 `#` 是仿真输出的行首标记 |
| `UVM_FATAL` / `UVM_ERROR` | UVM 库 | TB 自身报的 |

### 编译期

**`Warning: (vlog-...) latch inferred` / 锁存器推断**
- **怎么确认**：日志搜 `latch`；对到 always 块，查「分支未走完 + 无 else + 无默认值」。
- **怎么解**：补默认赋值或 `else`；组合逻辑改用 `always_comb` 让工具更强硬地报。

**`Error: (vlog-...) near "<token>": syntax error`**
- **怎么确认**：看 `near` 后面那个 token 的前一行 —— SV 语法错经常「报在下一行」。
- **怎么解**：先排漏分号、`end`/`endmodule` 配错、宏展开后的括号；

**`Error: ... Module '<name>' not found` / 顶层单元找不到**
- **怎么确认**：`vsim work.tb_top` 里的 `work` 库映射对不对、`tb_top` 是否真编进 `work`。
- **怎么解**：`vmap` 检查库映射；确认 `vlog -work work` 编的是同一个库名；**编译和仿真的库名必须一致**。

**`Error: ... Design unit '<x>' not found in library 'work'`**
- **怎么确认**：像编译成功了，但仿真说库里没有 —— 通常是 `vlog` 用了一个库、`vsim` 加载了另一个映射的 `work`。
- **怎么解**：统一库名；跨目录跑时每次显式 `vmap`。

### 仿真期

**`Fatal: (vsim-...) Signal '<name>' not found in region` / 读不到信号**
- **怎么确认**：想读 DUT 内部信号但波形里没有；层次名与优化后的名字对不上。
- **怎么解**：加 `-voptargs="+acc"` 保留可访问性（**最常见的「明明有信号却读不到」解法**）；或核对层次路径。

**`Fatal: (vsim-...) Null instance / null object` / 空指针**
- **怎么确认**：堆栈含 UVM 组件路径；多半 `config_db::get` 名/类型没对上。
- **怎么解**：核对 `config_db` 路径字符串；在 `build_phase` 加失败分支。

**`vsim` 跑起来就停在那，回归挂住**
- **怎么确认**：日志停在编译结束、没有任何 `run` 输出。
- **怎么解**：**漏了 `-c`（批处理）或 `-do "run -all; quit -f"`**。交互模式下 `vsim` 是等人敲命令的。

**`UVM_ERROR ( ... )` 汇总非零但仿真正常结束**
- **怎么确认**：看末尾 `--- UVM Report Summary ---`。
- **怎么解**：需要快速失败时设 `set_report_max_quit_count`；否则错误一路带到底、日志淹没。

## 版本坑

| 坑 | 老行为 → 新行为 | 怎么避 |
|---|---|---|
| ModelSim 与 Questa 的覆盖率能力 | ModelSim 版覆盖率支持有限、`vcover` 度量少；**Questa 版才有完整的 ucdb 与合并** | 用覆盖率功能前先确认是 Questa 而不是受限的 ModelSim |
| 优化（vopt）默认力度 | **新版本默认优化更强，信号/层次名会被改**，老脚本直接读内部信号会突然「找不到」 | 需要访问内部信号就固定写 `-voptargs="+acc"`，别依赖默认 |
| 库格式（`-sv_seed` 与求解器） | 随机求解器实现跨版本会变，**同一 `-sv_seed` 不同版本不保证逐位一致** | 复现要**钉死工具版本**；同版本 + 同种子才保证同结果 |
| `-2008` VHDL 标准 | 新版本默认 VHDL 标准可能更严，老代码里的宽松写法会报警甚至报错 | 编译 VHDL 显式给 `-2008`（或工程约定的标准版本） |
| `-do` 里 `quit` 的写法 | 旧脚本 `quit` 在新版本可能被要求 `quit -f` 才强制退出 | 批处理统一写 `quit -f` |
| ucdb 合并的度量一致性 | 用不同 `-coverage` 度量集合产生的 ucdb 合并，报告口径会不齐 | 全回归用**同一套覆盖率开关**，合并前对齐 |

> 关键取舍与 VCS 同理：**工具版本、编译开关、种子三者一起归档**才叫可复现（归档清单见 `../脚本与CI/回归流水线.md`）。

## 坑

| 坑 | 为什么诱人 | 后果 |
|---|---|---|
| 所有 case 共用一个 `work` 库 | 少建几个目录，省事 | 上一个 case 的编译单元污染下一个，报错诡异且难复现 |
| `vsim` 不加 `-c -do` | GUI 下点一下就跑起来了 | 回归卡死等人敲命令 |
| 忘了 `vmap` | 觉得「work 就是 work 目录」 | 跨目录跑时库映射漂了，`Design unit not found` |
| 读内部信号不加 `+acc` | 不知道有这回事 | 波形里信号缺失，误判「DUT 没这个信号」 |
| `-sv_seed` 不记 | 跑过了就算过 | 挂掉复现不了，只能整条回归重跑 |
