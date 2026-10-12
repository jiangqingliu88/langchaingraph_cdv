---
id: KB-DV-TOOL-005
title: Xcelium：仿真编译运行、覆盖率采集与常见报错
type: 工具卡
domain: 工具与脚本
subdomain: Xcelium
tags: [Xcelium, SystemVerilog, 覆盖率]
roles: [DV工程师]
stages: [编码, 调试, 回归]
summary: >
  Cadence Xcelium 的编译-运行-覆盖率三条流水线：单条 `xrun` 与
  `xmvlog`/`xmelab`/`xmsim` 三条分开干各自什么时候用，
  UVM 库与 DPI 怎么挂进来，以及编译/elaboration/运行三段各自最常见的报错和判读。
applicable: |
  用 Xcelium 跑 UVM 仿真；不确定某一步该走单条 xrun 还是分开跑；
  xrun 编译或运行报错需要定位；要采代码/功能覆盖率并生成可读的覆盖率数据库。
not_applicable: |
  想要的是波形怎么看、信号怎么追、覆盖率怎么涨上去 —— 波形去 `verify/04_工具与脚本/Verdi/`（或 simvision/nWave），
  覆盖率收敛去 `verify/07_度量与报告/覆盖率收敛/`；
  形式验证属性写不出来 —— 去 `verify/04_工具与脚本/JasperGold/`；
  跨时钟域违例怎么判读 —— 去 `verify/04_工具与脚本/SpyGlass/`。
prerequisites: [KB-DV-TOOL-005 所依赖的 UVM 基础 —— 见 verify/02_验证方法学/UVM/]
references: []
related: [KB-DV-TOOL-001, KB-DV-TOOL-003]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# Xcelium：仿真编译运行、覆盖率采集与常见报错

> **一句话**：Xcelium 把「编译」「elaboration」「运行」三段拆成三个可独立重跑的阶段。
> 单条 `xrun` 图省事把三段串起来，但**一旦要迭代，分开跑能省掉大量重复编译时间**。
> 报错判断的第一步永远是：**这是哪一段报的**。

## 干什么

- 编译 SystemVerilog / Verilog / VHDL / UVM 测试平台与 DUT
- 运行仿真，产生波形（FSDB / SHM / VCD）与日志
- 采集代码覆盖率（line / toggle / branch / FSM / expression）
- 合并多个测试的覆盖率数据库，生成文本 / 网页报告（`imc` / `urg` 风格汇总量）
- 支持 SystemC/DPI-C 协同、低功耗 UPF、SVA 断言与 `covergroup`

## 常用命令

### 三条主干流程

```bash
# ① 单条流：编译 + elaborate + 运行一步到位（小改动、快速验证时用）
xrun -f filelist.f -sv -uvm \
     -top tb_top \
     -access +rwc \
     -timescale 1ns/1ps \
     -coverage all \
     -covtest smoke_001 \
     -xmlibdirname ./xcelium.d \
     -l sim.log

# ② 三段流：分别编译 / 链接 / 运行（回归和大项目常用）
xmvlog -sv -uvm -f filelist.f -work worklib -l comp.log      # 编译 SV 源
xmvhdl -v93 -work worklib -f vhdl.f -l vhdl.log              # 编译 VHDL
xmelab -work worklib -top tb_top -access +rwc -l elab.log    # elaboration（链接）
xmsim  -work worklib tb_top -input run.tcl -l run.log        # 运行

# 只做语法/elaboration 检查，不跑仿真（快速回归前的门禁）
xrun -f filelist.f -sv -uvm -top tb_top -elaborate -l elab.log
```

### UVM 与库

```bash
# 用 Xcelium 自带的 UVM 库（版本随安装，别和源码库混用）
xrun -uvm ...

# 用自己的 UVM 源码
xrun -uvmhome $UVM_HOME ...

# 挂 DPI-C / SystemC
xrun -sv_lib ./libmy_dpi.so ...

# 若需要用户 C 代码
xrun -I./include -L./lib -lmy_c ...
```

### 覆盖率

```bash
# 打开覆盖率：all = line+toggle+branch+fsm+expr+cond
xrun ... -coverage all -covtest <test_name>

# 指定覆盖率工作目录
xrun ... -coverage all -covworkdir ./cov_work

# 只采代码覆盖率、不要功能覆盖率
xrun ... -coverage code

# 合并多次测试的覆盖率库
imc -load ./cov_work/scope/<lib>/* -merge -exec merge_cmds.tcl

# 生成文本报告 / 网页报告
imc -load cov_work/scope/test_* -exec report_cmds.tcl -report_html ./cov_report
```

### 运行期控制

```bash
# 用 Tcl 脚本跑（在 -input 里写 run / dump 命令）
xrun ... -input run.tcl

# 只 dump 关心的信号（波形文件能小一个数量级）
xrun ... -wave_intf ./dump.tcl
```

## 常见报错与解法

**先判段，再看文本。** 同样一句报错，在编译段和在运行段含义完全不同。

| 报错文本特征 | 是哪一段 | 怎么确认 | 怎么解 |
|---|---|---|---|
| `near "xxx": syntax error`、`token 'xxx' not expected` | 编译（`xmvlog`） | 看报错行号是否指到真实源文件；有时是**前一行的宏没展开** | 顺着**上一个**未闭合的 `begin` / `(` / 宏去看；用 `-E` 只做预处理看展开结果 |
| `Cannot find module/interface 'xxx'` | 编译 | 该模块是否在 filelist 里？文件名与模块名大小写一致？ | 补 filelist；确认 `-y`/`-v` 搜索路径；`-incdir` 补 include |
| `Undefined variable/identifier` 但源码里明明有 | 编译（顺序/宏） | 文件**编译顺序**是否在 filelist 里排对了（package 要先编） | 调整 filelist 顺序，或把公共 package/typedef 提到最前 |
| `Duplicate declaration of 'xxx'` | 编译 | 是不是同一个文件在 filelist 里被包含两次？ | 去重 filelist；用 include guard |
| `No top-level module found`、`Top module 'xxx' not found` | elaboration（`xmelab`） | `-top` 名字拼错？还是模块只在 `--elaborate` 子集里没编进来 | 核对 `-top`；确认该模块确实编进了 `-work` 库 |
| `Instantiation of 'xxx' failed: unresolved reference` | elaboration | 被例化的模块编到别的库/别的 work 了 | 统一 `-work`，或加 `-v` 把源直接喂进来 |
| **Port width mismatch** / **port connection does not match** | elaboration | 某个例化的端口宽度与定义不符 | 按报错给的层次路径回去核对例化；这类**必须修**，不是能忽略的告警 |
| `undefined reference to 'uvm_...'` / UVM 相关链接错误 | elaboration | `-uvm` 没给，或 `-uvmhome` 指到了错误的版本 | 明确指定 `-uvm` 或 `-uvmhome`；**不要同时用自带库和源码库** |
| 运行刚开始就 `$fatal`、`UVM_FATAL`、`UVM_ERROR` 计数不为 0 | 运行（`xmsim`） | 看日志里第一个 `UVM_ERROR` / `UVM_FATAL` 的位置——**看第一个，不是最后一个** | 按第一个报错修；后续的多半是级联 |
| `Simulation terminated due to ...` + 无波形 | 运行/波形 | 是不是 dump 命令写在 `run` 之前？或者 `-access +rwc` 没给导致内部信号不可见 | 把 dump 命令放到 `run` 之前；补 `-access` 级别 |
| 仿真挂住不结束、无输出 | 运行 | 是不是 `run` 没给结束条件（`$finish` 没触发 / `run -all` 没写） | 加超时（`-input` 里 `run 10ms`）；检查测试是否在等一个永远不来的事件 |
| `xmsim: *E,...` 出现在**回归中途**且时间点靠后 | 运行/竞争 | 打开 `-linedebug` 或 `-warn_multiple_driver` 看是否多驱动 | 多驱动/竞争要按 SV 语义修，别拿 `-suppress` 掩盖 |
| `Coverage database is empty`、`imc` 打不开库 | 覆盖率 | 该次运行是否真的加了 `-coverage`？`-covtest` 名字是否重复导致覆盖？ | 加 `-coverage`；每次 test 给**唯一** `-covtest` 名 |
| `Error: cannot open file 'xxx'` 且路径里有空格 | 任意段 | 路径没加引号 | filelist 里给含空格路径加引号 |

### 定位顺序（别乱来）

```
① 看日志最后一行报的阶段名（xmvlog / xmelab / xmsim 哪个在报）
② 该段若有 line number，先回到那一行；没有就跑 -E 看宏展开
③ 编译过了但 elaborate 错 → 一定是 filelist / -top / -work / 库 的问题
④ elaborate 过了但运行错 → 看第一个 UVM_ERROR / $fatal，不看最后的
```

## 版本坑

| 坑 | 表现 | 处理 |
|---|---|---|
| 自带 UVM 库与源码 UVM 混用 | elaboration 链接到两套符号，`undefined reference` 或行为诡异 | **只用一方**：要么 `-uvm`，要么 `-uvmhome` 指源码；不要既挂源码又加 `-uvm` |
| UVM 版本随工具升级 | 换版本后 `uvm_*` 宏/类找不到或行为变化 | 把 UVM 版本**固定在项目侧**（独立目录 + 记录版本），不要吃工具默认 |
| `-timescale` 未给、源里也没有 `` `timescale `` | 编译警告 + 仿真时间尺度错乱（延迟大十倍或小十倍） | 显式给 `-timescale`，或在顶层统一 `timescale` |
| `-access +rwc` 开太满 | 大设计编译/运行显著变慢、波形巨大 | 按需给：调试期给 `+rwc`，回归只给 `+r`；用 `-wave_intf` 只 dump 关心的信号 |
| 覆盖率类别全开 | 运行变慢、cov 库膨胀、报告里一堆无关项 | 按需选类别；`-coverage all` 只在需要时 |
| `-covtest` 名字复用 | 多次运行互相覆盖，合并后仍是单次数据 | 每次 test 用唯一名（含 seed/日期） |
| 用 `-suppress` 消警告 | 报告干净了，真问题也被埋了 | 只 suppress **有理由、有记录**的，且按 ID 精确 suppress，忌全局 suppress |

## 坑

| 坑 | 为什么诱人 | 后果 |
|---|---|---|
| 一直用单条 `xrun` 迭代 | 一条命令方便 | 每次小改都重编全量，回归时间被编译吃掉 |
| `-top` 写错却以为是源码错 | 报错看着像「模块不存在」 | 白查源码；其实是 elaborate 段找不到入口 |
| 编译报错只看最后一行 | 工具把**第一个**错排在前面 | 修了最后一个，前面还有一堆，误以为越修越多 |
| 运行报错只看最后一个 `UVM_ERROR` | 最后一个最显眼 | 最后一个是级联，真因在第一个 |
| `-access` 默认值以为够用 | 「不就 dump 个波形」 | 内部信号 dump 出来是 `x`/不可见，以为是 DUT 问题 |
| 覆盖率库到处生成、从不合并 | 每次跑完就完事 | 签核时才发现数据散落、合不出来，覆盖率数字不认 |
| 波形和覆盖率同时全开跑长回归 | 「一次跑全拿到」 | 磁盘和 IO 成为瓶颈，回归跑不完 |

> **最值钱的一条**：把「编译成功」当成「能跑起来」。
> elaborate 段（`xmelab`）和运行段（`xmsim`）的报错**看起来都像编译错误**，
> 但解法完全不同 —— 分清是哪一段，能省掉一半的排查时间。
