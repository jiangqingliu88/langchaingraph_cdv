---
id: KB-DV-TOOL-007
title: VC Formal：从仿真资产切入的形式验证，与 JasperGold 的分工
type: 工具卡
domain: 工具与脚本
subdomain: VC_Formal
tags: [VCFormal, 形式, 断言]
roles: [形式, DV工程师]
stages: [编码, 调试]
summary: >
  Synopsys VC Formal 的定位不是「JasperGold 的替代品」——
  它把应用（FV/CC/SEQ/ABVIP/…）做成一套**可组合的 app 集合**，
  并且和 VCS/UVM 仿真流共享同一套 SVA、同一个编译前端，天然适合从已有仿真环境「长出来」。
applicable: |
  团队本来跑 VCS + UVM，想在同一套 SVA/编译流上补形式证明；
  要把多个形式应用（等价性/连通性/序列检查/属性证明）串成一条流；
  想按 sign-off 报告把形式结果并入证据链。
not_applicable: |
  想学形式验证基础（属性、假设、反例怎么组织）—— 去 `verify/04_工具与脚本/JasperGold/` 或 `verify/02_验证方法学/形式验证/`；
  仿真里 SVA 怎么写 —— 去 `verify/03_技术与组件/断言与覆盖率/`；
  Lint / CDC / RDC —— 去 `verify/04_工具与脚本/SpyGlass/`。
prerequisites: [KB-DV-TOOL-006, KB-DV-TOOL-001]
references: []
related: [KB-DV-TOOL-006]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# VC Formal：从仿真资产切入的形式验证，与 JasperGold 的分工

> **一句话**：VC Formal 和 JasperGold **解决的是同一类问题**（用形式方法证明 RTL 属性），
> 但**切入方式不同**：JasperGold 是一套**独立的形式平台**，属性/假设/脚本自成体系；
> VC Formal 是把它拆成一组**应用 app**（`FV` / `CC` / `SEQ` / `ABVIP` / `FTA` …），
> 每个 app 各管一件事，且与 VCS + UVM 共用编译前端和 SVA。
> **选哪个，取决于你手里现有的是什么。**

## 干什么

| app | 全称（意译） | 干什么 |
|---|---|---|
| **FV** | Formal Property Verification | 证明 `assert` 属性（对应 JasperGold 的核心能力） |
| **CC** | Connectivity Checking | 结构连通性/端口连接一致性检查（RTL 跟 spec/网表对不对得上） |
| **SEQ** | Sequential Equivalence | 时序等价性（RTL vs RTL、RTL vs 网表） |
| **ABVIP** | Assertion-Based VIP | 用断言 VIP 形式地验协议接口 |
| **FTA** | Fault / Test Analysis 类应用 | 故障/测试相关的结构分析 |
| **REGL** / **FXP** | 寄存器 / 浮点形式检查 | 寄存器自动生成属性、浮点数据通路形式化 |

**一句话概括分工**：JasperGold = 一个强大的单平台；VC Formal = 一组各司其职、可组合的 app，
从**已有仿真环境**里长出来。

## 常用命令

### 批处理启动

```bash
# 批处理入口（读 Tcl）
vcst -f vcformal.tcl -l vcformal.log

# 或先编后用
vcf -f vcformal.tcl
```

`vcst` 是 VC Formal 的命令行驱动；`vcf` 是另一种入口（按安装脚本名为准，
**不要照抄别处的脚本名——以本机 `which` 到的为准**）。

### 典型 Tcl 脚本

```tcl
# ── 与 VCS 共用的编译前端：读 UVM/SV 源码 ──
# 编译（vcst 会自动调用 VCS 的编译流程）
analyze -f filelist.f -sverilog -define VC_FORMAL
elaborate top

# ── FV app：属性证明 ──
# 属性可以直接复用仿真里的 SVA（同一个 SVA 前端）
set_app_var fv_assertion_file ./assertions/arb_*.sv
create_clock clk -period 10
create_reset rst_n -low

# 假设（与仿真 SVA 共用语法）
assume property (@(posedge clk) disable iff(!rst_n) req |-> ##[1:2] rsp);

# 证明
run_fv -all
report_fv -summary

# ── CC app：连通性检查 ──
set_app_var cc_guidance_file ./cc_guide.tcl
run_cc
report_cc -violation

# ── SEQ app：时序等价 ──
set_app_var seq_impl_top impl_top
set_app_var seq_ref_top  ref_top
run_seq
report_seq
```

### 与 VCS 仿真流衔接

```bash
# 同一套 filelist 与 SVA 宏：仿真和形式共用同一份属性源
vcs -f filelist.f -sverilog +define+SIM ...
vcst -f vcformal.tcl                # 形式侧读同一份属性，靠 define 区分
```

## 与 JasperGold 的差异（这才是本卡的重点）

**它们不是「同一种卡换个名字」。** 差异集中在四点：

| 维度 | JasperGold | VC Formal | 这条差异影响什么 |
|---|---|---|---|
| **组织形态** | **平台**：一套 Tcl/属性体系，能力集中在主引擎 | **应用集**：FV / CC / SEQ / ABVIP 各自独立入口与报告 | 想一次跑多种形式检查（连通性+等价+属性）时，VC Formal 的组合更顺；JasperGold 要靠单平台的 app 切换 |
| **与仿真的耦合** | 相对独立，属性/假设常单独维护 | 与 **VCS 共用编译前端与 SVA**，属性可从仿真环境直接复用 | 「已有 UVM + SVA 环境，想补形式」时 VC Formal 起步成本低 |
| **收尾/报告流** | 报告偏「形式工程」内部视角 | 与 Synopsys sign-off 报告流（同一套报告基础设施）衔接 | 要把形式结论并入**签核证据链**时，VC Formal 更省转接 |
| **团队生态** | Cadence 侧，与 Xcelium/SimVision 生态近 | Synopsys 侧，与 VCS/Verdi/DC 生态近 | **工具链一致性**往往比引擎本身差异更重要 —— 你已有的仿真器是哪家？ |

**怎么选（判据）**：

```
① 已有环境是 VCS/UVM + SVA  → 优先 VC Formal（共用前端，复用属性）
② 已有环境是 Xcelium        → 优先 JasperGold（生态一致）
③ 要一次做连通性+等价+属性  → VC Formal 的 app 组合更直接
④ 只要一条属性证明的深度能力 → 两家都行，比的是团队熟练度而非工具
```

> ⚠️ **不要用「哪个 proven 多」来选工具。** 同一属性在两家的结论差异，
> 多半来自**默认假设/抽象策略不同**，而不是谁更强 —— 结论要连同**假设清单和工具版本**一起记录。

## 常见报错与解法

| 报错文本特征 | 怎么确认 | 怎么解 |
|---|---|---|
| 编译报错指向仿真里没有问题的 SVA | 形式前端对某些仿真容忍的写法更严 | 按形式语义改写；用 `` `ifdef VC_FORMAL `` 分出形式专用版 |
| `elaborate` 失败、找不到 top | 与 VCS 共用的 elaborat 配置不对 | 统一 top 名和 `-define`；确认形式侧 filelist 与仿真一致或**有理由地**不同 |
| 属性全 `unresolved` / 未证 | 是不是时钟/复位没 `create_clock` / `create_reset`？ | 补时钟复位；确认属性能被引擎认到 |
| CC app 报「端口不匹配」一堆 | 引导文件（guidance）没写，工具做了最保守的匹配 | 写 `cc_guidance` 指明哪些端口该对哪些；不要一股脑 waive |
| SEQ 报不等价 | 是不是复位/初始化没对齐，或真的不等价 | 先对齐 clock/reset/initial；真不等价就对了，别急着 waive |
| 运行时间爆掉 | app 没设时间上限 | 各 app 都要设时间预算；超限项单列 |
| 结果与仿真断言不一致 | 假设空间不同（仿真有激励约束、形式没有） | 把仿真里的输入约束补成 `assume`；两边对**同一套假设**比较 |

## 版本坑

| 坑 | 表现 | 处理 |
|---|---|---|
| 形式与仿真**共用**SVA 但没分版本保护 | 仿真能过的写法形式报错，或反之 | 形式专用属性放 `` `ifdef `` 块，或用独立文件 |
| 编译前端随 VCS 版本变 | 换 VCS 版本后形式侧编译行为跟着变 | 形式的编译前端版本**绑定**到 VCS 版本记录里 |
| app 组合方式随版本变 | 老脚本里 app 名/开关在新版报未知 | 脚本进版本控制，升级后回归一遍，记录基线版本 |
| `create_clock` 周期与仿真 `timescale` 不一致 | 时序类属性结论看起来对其实错 | 形式的时钟周期**对物理时间有含义**，必须和 SDC/仿真对齐 |
| 报告格式随版本变 | 自动解析签核报告的脚本失效 | 报告解析脚本与被解析工具版本一起 pin |

## 坑

| 坑 | 为什么诱人 | 后果 |
|---|---|---|
| 把 VC Formal 当「JasperGold 换皮」 | 两边 concept 都是 assert/assume/cover | 忽略 app 组织与报告流的差异，用错 app 白跑 |
| 形式属性与仿真 SVA 完全共用、不分版本 | 一份文件省事 | 一边能过一边报错，来回改，最后两边都不干净 |
| 只跑 FV app | 「属性证明不就是核心吗」 | 连通性/等价性本来就该在更早阶段拦住的问题漏到后仿 |
| 按「谁 proven 多」选工具 | 报告数字直观 | 比的是默认假设，不是能力；结论不可比 |
| 用 `waive` 清掉形式违例 | 报告立刻干净 | 形式 waive 必须带理由+审批 —— 它是「我声明这条不用证」，不比仿真 waive 轻 |
| 不记录工具版本 | 「形式结果就是结论」 | 换版本后结论变化，无法复现当时的签核依据 |
| 形式结论不并入证据链 | 结果在工程师机器上，报告没归档 | 签核时拿不出「这条为什么可以不下仿真」的证据 |

> **最值钱的一条**：VC Formal 的真正价值在**「从仿真资产长出来」** ——
> 同一份 SVA、同一个编译前端、同一套报告流。
> 如果你把它当成一个独立工具、属性从零重写、结果手动抄进报告，
> 那你就用了个更贵的 JasperGold，而没吃到它真正的差异。
