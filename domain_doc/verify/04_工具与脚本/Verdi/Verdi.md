---
id: KB-DV-TOOL-003
title: Verdi 打开 FSDB 做波形与源码调试（nWave / nTrace / nSchema）
type: 工具卡
domain: 工具与脚本
subdomain: Verdi
tags: [Verdi, 调试]
roles: [DV工程师]
stages: [调试, 后仿]
summary: >
  Verdi 怎么吃 FSDB：三个窗口（nWave 看波形、nTrace 追源码与驱动、
  nSchema 看逻辑锥）各管什么，以及「有波形没源码」「dump 不全」这类
  调试阻断怎么解。
applicable: |
  仿真挂了一条、要从波形和源码定位原因；
  或波形已 dump 出来、但 Verdi 里看不到源码/信号的时候。
not_applicable: |
  想知道怎么让仿真器产生波形（`$fsdbDumpfile`/`+fsdb+all`）—— 去 `../VCS/VCS.md`；
  想调覆盖率而不是波形 —— 去 `../../07_度量与报告/`；
  想做形式验证反例分析 —— 去 `../JasperGold/` 或 `../VC_Formal/`。
prerequisites: []
references: []
related: []
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# Verdi 打开 FSDB 做波形与源码调试

> **一句话**：Verdi 是**读 FSDB 的事后调试器** —— 它自己不跑仿真。
> 它做的三件事：nWave 看波形、nTrace 从信号追到驱动它的源码、
> nSchema 把逻辑锥画出来。会不会用，主要差在**有没有源码库（`-dbdir`/KDB）**。

## 干什么

| 窗口 | 干什么 | 什么时候用它 |
|---|---|---|
| **nWave** | 看波形、加信号、比对游标 | 「某个时刻这个信号为什么是 1」 |
| **nTrace** | 从信号/时刻追到源码，看驱动它的是哪行 | 「是谁把这根信号拉起来的」 |
| **nSchema** | 把一段逻辑的驱动锥/负载锥画成图 | 「这条路径经过哪些逻辑」 |
| **nCompare** | 比对两次仿真的波形差异 | 「改之前/改之后哪里行为变了」 |
| **Verdi Coverage** | 看覆盖率的源码标注 | 覆盖率漏洞定位（也可配合 URG） |

**核心前提**：Verdi 想给你「源码」，需要**编译期产生的源码数据库（KDB / `simv.daidir` 一类）**。
只有 FSDB、没有源码库时，nWave 能看，nTrace **追不到源码** —— 这是最常见的「波形有了但调不动」的原因。

## 常用命令

### 1. 交互打开

```bash
verdi -f filelist.f -sv \
      -ssf run.fsdb \
      -dbdir ./simv.daidir \
      -nologo &
```

| 开关 | 在干什么 |
|---|---|
| `-f filelist.f` | 给源码列表，**nTrace 需要它才能显示源码** |
| `-sv` | 按 SystemVerilog 解析 |
| `-ssf <fsdb>` | 打开波形文件（`-ssf` = show signal file），可多个 |
| `-dbdir <dir>` | 指定编译期产生的源码数据库目录 —— **没有它源码就追不到** |
| `-nologo` | 跳过启动 logo（脚本里省事） |
| `-norestore` | 不恢复上次会话的布局/信号列表（**复现调试现场时用它，避免被上次状态干扰**） |
| `-top <top>` | 指定顶层名 |
| `-incdir <dir>` | 头文件搜索路径 |
| `-nn <name>` | 命名信号列表文件 |

### 2. 从仿真直接进（一键调试）

```bash
# 仿真侧：先 dump FSDB —— 在 TB 里或命令行打开
#   $fsdbDumpfile("run.fsdb"); $fsdbDumpvars(0, tb_top);
# 命令行方式的等效开关（编译/仿真侧）：
#   +fsdb+all  或  -fsdb  家族开关

# 跑完直接掀开 Verdi
verdi -ssf run.fsdb -dbdir ./simv.daidir &
```

> **FSDB 是产生在仿真侧的**：TB 里 `$fsdbDumpfile` + `$fsdbDumpvars`，
> 或者仿真器侧的 plusarg/开关。Verdi 只负责**事后读**。
> 波形没 dump 出来，Verdi 帮不了你 —— dump 的开关见 `../VCS/VCS.md`。

### 3. 批处理方式（脚本/CI 里）

```bash
verdi -ssf run.fsdb -dbdir ./simv.daidir \
      -batch -do "nWave::addSignal tb_top.dut.state; run" \
      -nologo
```

| 开关 | 在干什么 |
|---|---|
| `-batch` | 不开全 GUI，跑 `-do` 里的命令 |
| `-do "<cmd>"` | 执行 Verdi 的 Tcl 命令，如 `nWave::addSignal` |
| `-exit` / `quit` | 批处理跑完退出，**不开就是挂着等人** |

批处理主要用来「自动加一批信号、导一张图」，**大多数调试还是交互式更快**。

## 调试一个失败 case 的常用动作

| 想干的事 | Verdi 里的做法 |
|---|---|
| 找到出错时刻 | nWave 里搜 `$fatal` 时刻，或从日志时间戳定位游标 |
| 看该时刻信号值 | 加信号到 nWave，游标拖到该时刻 |
| 找是谁驱动的 | 信号上右键 → Trace Driver（跳到 nTrace） |
| 看这段逻辑的输入 | nTrace 里对信号做 Trace Load |
| 看逻辑锥全貌 | 转 nSchema |
| 比对改前改后 | 两次 FSDB 都打开，用 nCompare 比差异 |
| 存调试现场 | 保存 signal list / 会话，**下次带 `-norestore` 之外的方式复现** |

## 常见报错与解法

Verdi 的「报错」更多是**现象**而非编号错误。按现象对号入座：

| 现象 | 原因 | 怎么确认 | 怎么解 |
|---|---|---|---|
| 波形能看，但 nTrace 里**看不到源码** | 缺源码库 / `-f` 文件列表 | nTrace 里源码区空白或提示找不到文件 | 编译时**生成源码数据库**，Verdi 加 `-dbdir <dir>` 并给 `-f filelist.f` |
| 打开 FSDB 报**文件为空 / 无法解析** | 仿真根本没 dump，或 dump 中途被杀 | 看 `run.fsdb` 大小是不是 0 | 回仿真侧打开 dump（`$fsdbDumpvars`）；确保 run 正常结束再读 |
| **只有顶层信号，DUT 内部信号没有** | `$fsdbDumpvars` 的层次参数只 dump 了顶层级 | nWave 里层次树只有浅层 | 把 dump 层次改成覆盖 DUT（`$fsdbDumpvars(0, tb_top, "+all")` 或按需指到 DUT 实例） |
| 信号名**和源码对不上**（多出 `_r` / 被改名） | 仿真器优化改了名字 | 层次名与 RTL 不一致 | 仿真侧关掉优化（VCS `-debug_access+all`、Questa `+acc`），或按实际名字找 |
| 打开很慢 / 内存爆 | FSDB 太大（全层次全时刻 dump） | 文件几个 GB 起 | 只 dump 关心的层次与时间窗，别整芯片全 dump |
| **宏/参数化模块源码显示不全** | 缺 `-incdir` / 宏未定义 | nTrace 里宏处报错 | 补 `-incdir`、在 Verdi 侧也定义编译宏 |
| 两次对比**找不到相同信号** | 改名或层次变了 | nCompare 匹配失败 | 用信号别名/映射，保证两次同名同层次 |
| 打开 Verdi **恢复了上次布局、信号乱** | 上次会话被恢复 | 信号列表与预期不符 | 加 `-norestore`，从干净现场开始 |

## 版本坑

| 坑 | 老行为 → 新行为 | 怎么避 |
|---|---|---|
| 源码数据库（KDB）格式 | 旧版本靠 `-dbdir` 指 `simv.daidir`；**新版本主推独立的 KDB 目录**，格式与生成方式变过 | 用**与仿真器同版本配套**的 Verdi 生成/读取源码库，别跨版本混用 |
| FSDB 与应用版本的配套 | FSDB 是 STS 私有格式，**新版本可能引入旧 Verdi 读不了的特性**（如新的压缩/新信号类型） | dump 的仿真器与看波形的 Verdi **尽量同版本族** |
| `-norestore` / 会话恢复 | 新版本默认恢复上次会话，老习惯「打开就是干净的」不再成立 | 需要干净现场就显式 `-norestore` |
| 优化与信号可见性 | 新版仿真器默认优化更强，**即使 dump 了也可能因优化丢内部信号/改名** | dump 时同时保留可访问性（VCS `-debug_access`、Questa `+acc`） |
| FSDB 与 SHM/VCD 的选择 | SHM 是 Questa 的原生格式、VCD 是通用格式；**Verdi 对 FSDB 支持最好，VCD 信息量最小** | 用 Verdi 调试就优先 dump FSDB，别用 VCD 凑合（VCD 无层次、无枚举名） |

> 复现取舍：**波形的可复现靠「同一种子 + 同一 dump 开关」**，
> 而**能把波形看懂靠「源码库配得上」**。两者缺一个，调试就退化成瞎看。
> 种子与归档见 `../脚本与CI/回归流水线.md`。

## 坑

| 坑 | 为什么诱人 | 后果 |
|---|---|---|
| 只 dump FSDB 不给源码库 | 「有波形不就行了」 | nTrace 用不了，只能肉眼猜信号关系，调试效率掉一半 |
| 全层次全时刻 dump | 「怕漏，全都存」 | FSDB 几十 GB，打开就卡死，还没开始调就耗尽内存 |
| 用 VCD 代替 FSDB 调 Verdi | 「VCD 通用」 | 没有层次名、枚举/结构体变整数，看不出问题 |
| 优化开着还想读 DUT 内部信号 | 没意识到优化会改名/删信号 | 「信号名对不上」，误以为 RTL 写错 |
| 每次都恢复上次会话 | 省得重新加信号 | 带着无关信号、旧布局，反而看不清 |
| 拿别人跑了一夜的 FSDB 却不知道种子 | 有文件就打开 | 波形不可复现，只能看不能重跑 |
