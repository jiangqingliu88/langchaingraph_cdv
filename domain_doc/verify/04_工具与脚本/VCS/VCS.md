---
id: KB-DV-TOOL-001
title: VCS 编译、仿真与覆盖率命令速查（含常见报错对号入座）
type: 工具卡
domain: 工具与脚本
subdomain: VCS
tags: [VCS, 回归, 覆盖率]
roles: [DV工程师]
stages: [编码, 回归, 覆盖率]
summary: >
  用 VCS 跑一次「编译 → 仿真 → 覆盖率」的最短命令链，
  以及每条命令在干什么、报什么错时该去哪查。
applicable: |
  第一次搭起来要跑起来、回归挂了一条要对号入座、
  出覆盖率要选对数据库格式的时候。
not_applicable: |
  想知道「回归整体怎么组织才是可复现的」（种子/并行/合并的编排）—— 去 `../脚本与CI/回归流水线.md`；
  想看波形与源码调试（nWave / nTrace）—— 去 `../Verdi/Verdi.md`；
  想理解覆盖率模型本身怎么建 —— 去 `../../07_度量与报告/覆盖率模型/功能覆盖率建模.md`。
prerequisites: []
references: []
related: []
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# VCS 编译、仿真与覆盖率命令速查

> **一句话**：VCS 的正常节奏是「只编译一次，仿很多次」——
> 把编译和仿真分开，改 test 不必重编、跑种子只需换 `+ntb_random_seed`。
> 把这两件事揉成一条命令，是回归慢和不可复现的头号原因。

## 干什么

VCS 是 Synopsys 的编译型数字仿真器，一条流水线里干三件事，对应三个可分离的阶段：

| 阶段 | 干什么 | 产物 | 何时重跑 |
|---|---|---|---|
| **编译（analyze + elaborate）** | 把 SV/Verilog/VHDL 与 TB 编成可执行的仿真快照 | `simv` + `simv.daidir/` | 只改了 test / 种子时**不重跑** |
| **仿真（simulate）** | 跑一个 test，在某个种子下推进时间 | 日志、FSDB/SHM 波形、覆盖率库 | 每跑一个 case / 换一个种子都重跑 |
| **覆盖率（coverage）** | 收集 / 合并 / 报告覆盖数据 | `.vdb` 库、`.urg` 报告 | 数据攒够后合并，出签核报告 |

**为什么要分开**：编译是分钟级，仿真是秒到分钟级。一次回归几百个 case，
如果每个 case 都重编一次，时间全花在重复编译上；而且每次重编出来的 `simv`
可能就是另一个二进制，**「同一个种子给同一个结果」就无从谈起**。

## 常用命令

### 1. 编译出 simv

```bash
vcs -full64 -sverilog -debug_access+all \
    -timescale=1ns/1ps \
    -f filelist.f \
    -top tb_top \
    -cm line+cond+fsm+tgl+branch \
    -cm_dir ./cov.vdb \
    -l compile.log \
    -o simv
```

| 开关 | 在干什么 |
|---|---|
| `-full64` | 64 位编译/仿真。**绝大多数平台必须带**，不带会撞内存上限或工具拒绝 |
| `-sverilog` | 允许 SystemVerilog 语法（UVM 必需） |
| `-debug_access+all` | 打开调试信息，Verilog/FSDB dump 与 `-debug` 家族的前提 |
| `-timescale=1ns/1ps` | 给没有自己写 timescale 的模块定默认精度；漏了会报警告并可能算错时间 |
| `-f filelist.f` | 从文件读源文件列表，**回归里不要手写文件列表** |
| `-top tb_top` | 指定顶层模块，避免多个候选顶层 |
| `-cm ...` | 打开哪几类覆盖率：`line`/`cond`/`fsm`/`tgl`/`branch` |
| `-cm_dir ./cov.vdb` | 覆盖率数据库输出目录，多 case 合并靠它 |
| `-l compile.log` | 编译日志落文件，回归里必留 |
| `-o simv` | 输出二进制名 |

**增量编译**：改一个文件重跑 `vcs`，VCS 默认只重编变化的部分（靠已有 `simv.daidir`），
所以**目录别随便删**，删了下次就是全量编译。

### 2. 跑仿真

```bash
./simv -l sim.log \
       +ntb_random_seed=12345 \
       +UVM_TESTNAME=my_test \
       +fsdb+all \
       +plusarg_save \
       +ntb_random_seed_automatic
```

| 参数 / 开关 | 在干什么 |
|---|---|
| `+ntb_random_seed=<N>` | **固定随机种子** —— 复现的前提。数字记进结果归档，谁都能重跑同一条 |
| `+UVM_TESTNAME=<t>` | 选跑哪个 UVM test；不写就用 `uvm_test_top` 的默认 |
| `+fsdb+all` / `$fsdbDumpfile` | 打开 FSDB 波形 dump（配合 Verdi 用） |
| `+plusarg_save` | 让 `$test$plusargs` 之类的 plusarg 不因大小写/顺序出岔子 |
| `-cm ...` | 仿真侧也要给同样的 `-cm`，否则不收集 |
| `-assert ...` | 打开 SVA 断言统计 |
| `+define+<MACRO>` | 传编译期宏（编译侧用 `+define+`，运行期宏要在编译时一起给） |

**运行期也是命令入口**：`./simv` 后面挂的一切都是「这一跑的输入」——
种子、test 名、plusarg。**这些输入不记下来，这一跑就不能被复现**
（归档清单见 `../脚本与CI/回归流水线.md`）。

### 3. 覆盖率：合并与报告

```bash
# 把多个 case 的覆盖数据库合并成一份
urg -full64 -dir cov.vdb -dir second.vdb -dir third.vdb \
    -dbname merged.vdb \
    -format both \
    -report merged_report \
    -l urg_merge.log
```

| 开关 | 在干什么 |
|---|---|
| `-dir ...` | 要合并的数据库，可给多个。**回归里一个 case 一个 `.vdb`，这里全喂进来** |
| `-dbname` | 合并产物，后续 `-dir merged.vdb` 就能被别的报告复用 |
| `-format both` | 同时出文本与 HTML 报告 |
| `-report <dir>` | 报告输出目录 |
| `-metric line+cond+fsm+tgl+branch` | 只报关心的度量，避免噪声 |
| `-show tests` | 报告里带上「哪些 case 覆盖了这条」——**定位漏洞时最有用** |

> 想直接看某个目的目录里的覆盖率排名：`urg -dir cov.vdb -report rpt`，
> 报告里 `report.html` / `text` 两个入口各取所需。

## 常见报错与解法

先认一个规律：**看报错前缀，就知道该翻编译还是仿真。**

| 前缀 | 出自 | 含义 |
|---|---|---|
| `Error-[XXX]` | 编译 / elaborate | 语法、类型、层次绑定类问题 |
| `Warning-[XXX]` | 编译 | 推断、截断、未连接 —— **latch 推断就在这类** |
| `Fatal: (sim-` / `(vsim-` | 仿真 | 运行期错误（空指针、越界、assertion） |
| `UVM_FATAL` / `UVM_ERROR` | UVM 库 | TB 自身报的，非工具 |
| `%Error:` | Verilog 编译 | 老式 VL 模式报的语法错 |

### 编译期

**`Warning: latch inferred` / 推断出锁存器**
- **怎么确认**：日志里搜 `latch`；定位到 always 块，看是不是「分支没走完、又没有 else、又没给默认值」。
- **怎么解**：补 `else` 或给寄存器赋默认值；**组合逻辑用 `always_comb` 而非 `always @(*)`，工具会更强硬地拦下**。若确实是刻意锁存（如低功耗结构），加 `// synopsys_...` 或显式注释并关掉这一条。

**`Warning: port ... is not connected` / 端口未接**
- **怎么确认**：看层次路径与端口名，多半是顶层例化漏了或名字打错。
- **怎么解**：对 TB 顶层无所谓（故意的空接）；对 DUT 端口是**真问题**，必须接上或用 `.*` 显式留空并说明。

**`Error: cannot find module` / 找不到模块或 include**
- **怎么确认**：看是不是 `-f filelist.f` 里漏了这个文件，或 `include` 用的相对路径在别的 workdir 下失效。
- **怎么解**：把文件加进 filelist；include 路径统一用 `-incdir` 显式给出，别依赖当前目录。

**`Error: undefined variable / unresolved`**
- **怎么确认**：编译顺序 —— SV 里**先编译的被后者看到**，`package` 要排在用它的模块之前。
- **怎么解**：调整 filelist 顺序；或用 `-sverilog` 下正确的 `import pkg::*`。

### 仿真期

**`Fatal: ... null object access` / 空指针**
- **怎么确认**：堆栈里有 UVM 组件路径；多半是 `config_db::get` 没拿到（名字/类型不匹配）就往下用了。
- **怎么解**：在 `build_phase` 里查 `config_db` 是否 `set` 成功，路径名逐字符核对；给 `get` 加失败分支。

**`Fatal: ... out of bounds` / 越界**
- **怎么确认**：报的是哪条 `$fatal` / 哪个数组下标。
- **怎么解**：查访存下标来源；动态数组要先判断 `size()`。

**`Error: assertion failed` 类**
- **怎么确认**：看断言名与触发时刻；这是**设计行为不符合规范**的信号，不是工具问题。
- **怎么解**：把它当 bug 看待，回波形复现（见 `../Verdi/Verdi.md`）；不要靠关断言「解决」。

**`UVM_ERROR ( ... )` 计数非零但仿真仍结束**
- **怎么确认**：`uvm_report_server` 的 error 计数。
- **怎么解**：UVM 默认 error 不终止仿真。若要让回归**快速失败**，在 `end_of_elaboration` 里设 `set_report_max_quit_count(1)`，否则错误会一路带到底、日志淹掉。

## 版本坑

| 坑 | 老行为 → 新行为 | 怎么避 |
|---|---|---|
| 覆盖率默认数据库格式 | 旧版本默认 VCD/老 `.vdb` 结构，新版本偏 `.vdb` + 独立 `.cm` 目录 | **合并报告与产生数据必须同版本工具**；跨版本合并常直接报库格式不认 |
| `-sverilog` 的必要性 | 早期还要配 `-ntb_opts uvm`；**新版本 UVM 库路径与 `-sverilog` 是默认要求**，老命令行迁移过来常缺 `-sverilog` | 命令行模板固定写 `-full64 -sverilog`，别依赖工具默认 |
| 随机稳定性（稳定性保证策略） | 工具对「无约束随机」的求解器实现会跨版本变化，**同一 `+ntb_random_seed` 在不同版本上不一定逐位相同** | 复现要**连工具版本一起钉死**；只有同版本同种子才保证同结果 |
| `-debug` 家族 | 旧的 `-debug_all` 逐渐被 `-debug_access+*` 系列取代 | 新命令行用 `-debug_access+all`；老脚本里的 `-debug_all` 会告警 |
| `timescale` 默认 | 不同版本对「未指定 timescale 时」的误差容忍不同 | 每个编译单元显式写 `` `timescale ``，别赌默认值 |

> 版本相关的取舍：**「同一版本」不是洁癖，是复现的必要条件**——
> 一个回归要能被别人重跑出同样的数，工具版本、编译开关、种子三者缺一不可。
> 归档这三样的做法见 `../脚本与CI/回归流水线.md`。

## 坑

| 坑 | 为什么诱人 | 后果 |
|---|---|---|
| 每个 case 都重编 | 「一条命令走完多省事」 | 回归时间翻几倍；且每次重编的二进制可能不同，不可复现 |
| 不记编译开关 | 「反正能跑起来」 | 换台机器 / 换个人跑，覆盖率数字对不上 |
| 覆盖率不开合并直接看单 case | 单 case 报告立刻有数 | 单 case 覆盖率没有意义，容易误判「已经覆盖好了」 |
| 用关断言来消 `assertion failed` | 报错消失，回归变绿 | 掩盖真实设计缺陷，签核结论失真 |
| `-cm` 编译侧给、仿真侧漏 | 编译日志里明明开了覆盖率 | 跑完发现没数据，白跑一轮 |
| 把 `.daidir` 当垃圾清掉 | 想省磁盘 | 下次全量编译，回归多花几十分钟 |
