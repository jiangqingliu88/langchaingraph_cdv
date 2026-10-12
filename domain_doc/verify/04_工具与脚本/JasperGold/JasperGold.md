---
id: KB-DV-TOOL-006
title: JasperGold：属性怎么组织、反例怎么看、三种结论各意味着什么
type: 工具卡
domain: 工具与脚本
subdomain: JasperGold
tags: [JasperGold, 形式, 断言]
roles: [形式, DV工程师]
stages: [编码, 调试]
summary: >
  形式验证的属性组织（assume / assert / cover 三分天下）、
  `proven` / `covered` / `undetermined` 三结论的判读，
  以及反例波形从「第几拍违例」向上追溯到根因的顺序。
applicable: |
  用 JasperGold 跑形式验证；属性跑出一堆 `undetermined` 或者反例不知道从哪看起；
  要判断「proven 了是不是就万事大吉」。
not_applicable: |
  想要的是**仿真里** SVA 断言怎么写、断言覆盖率怎么涨 —— 去 `verify/03_技术与组件/断言与覆盖率/`；
  用 Synopsys VC Formal、想比较两家工具的分工 —— 去 `verify/04_工具与脚本/VC_Formal/`；
  Lint/CDC 检查 —— 去 `verify/04_工具与脚本/SpyGlass/`。
prerequisites: [KB-DV-METH 形式验证基础 —— 见 verify/02_验证方法学/形式验证/]
references: []
related: [KB-DV-TOOL-007]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# JasperGold：属性怎么组织、反例怎么看、三种结论各意味着什么

> **一句话**：形式验证的结果**只有三种**，而它们的**可信度完全不同**：
> `proven` 是「在给定假设下、所有可达状态里都不违例」，`covered` 是「这条激励场景真的能发生」，
> `unreachable` 是「在当前假设下根本到不了」。
> **`proven` 只有在 `assume` 写对的前提下才有效** —— 假设写错，proven 是空话。

## 干什么

- 对 RTL 做属性证明（formal property verification, FPV）与断言检验
- 证明 `assert` 属性在所有可达状态成立，或给出一条**具体反例**（counterexample）
- 证明 `cover` 属性可达（对激励/场景做可达性证明）
- 做连通性/等价性检查、死锁检测、X 传播检查（取决于 license 与应用）
- 在仿真之前/之外，对**接口约束、仲裁、状态机、FIFO 边界**等小范围逻辑给出确定性结论

## 常用命令

### 交互式 / 批处理

```tcl
# 批处理入口
jg -batch -tcl script.tcl
jg -project my_proj -batch -tcl script.tcl   # 用已有工程

# 交互式（REPL 里执行 Tcl）
jg
```

### 典型 Tcl 脚本结构

```tcl
# 1) 清场 + 读设计
clear -all
analyze -sv09 -f filelist.f -define FORMAL
elaborate -top my_top -create_related_cells

# 2) 时钟与复位
clock clk
reset -expression {!rst_n}

# 3) 假设（assume）—— 输入空间的约束，写在这里
assume -name a_input_valid {req |-> ##[1:3] rsp}
assume -name a_input_range  {(addr inside {[0:255]})}

# 4) 属性（assert）—— 要证明的东西
assert -name p_no_overflow {!fifo_full || !wr_en}
assert -name p_grant_onehot {$onehot0(grant)}

# 5) 覆盖（cover）—— 要证明「真能发生」
cover -name c_full_write {fifo_full && wr_en}
cover -name c_arb_switch {grant != $past(grant)}

# 6) 证明
prove -all
# 或只证某个：prove -property {p_no_overflow}

# 7) 导出结果
report -summary
report -results
```

### 提高收敛能力的常用开关

```tcl
set_prove_time_limit 30m            # 单条属性时间上限（超了 → undetermined）
set_engine_mode {Hp N M B}          # 换证明引擎组合
set_max_trace_length 50             # 限制反例长度，短反例更容易看懂
set_proofgrid_mode                  # 网格/多核并行（按 license）
```

### 反例（counterexample）

```tcl
# 有反例时，波形在 GUI 里看；批处理下导出
get_counterexample -property p_no_overflow
visualize -wave -property p_no_overflow    # GUI
# 导出波形
save -wave -property p_no_overflow -format vcd ./ce_wave.vcd
```

## 三种结论各意味着什么

| 结论 | 字面意思 | 你必须继续问的问题 |
|---|---|---|
| **proven**（已证明） | 在**给定 `assume` 下**、所有可达状态里属性恒成立 | **assume 写对了吗？** 假设过强（把输入空间砍太狠）会让属性「轻松 proven」却毫无意义。有没有 `unreachable` 把真正的场景挡掉了？ |
| **covered**（覆盖到） | 这条 `cover` 描述的**场景真的可达** | **`cover` 本身写完没有？** cover 点没列全时，"全 covered" 不代表场景全跑过 |
| **unreachable**（不可达） | 在**当前 `assume` 下**永远到不了 | **是真不可达，还是被自己的假设挡住？** 误判为 unreachable 是形式验证最危险的错 |
| 反例（cex / violated） | 找到一条**具体路径**让属性不成立 | 是设计 bug 还是**属性写错/假设缺失**？（见下节） |
| **undetermined**（未定） | 时间/引擎复杂度用完，没证出来也没找到反例 | **不是通过，也不是失败。** 要么加 `assume`、分块、加时间，要么承认它在当前抽象下证不了 |

**`undetermined` 是最容易被误读的一个** —— 报告里它不算 fail，很容易被跳过。
但签核意义上，它和「没做」等价，必须逐条给出「为什么接受」的理由（加约束？降规模？转仿真？）。

## 反例怎么读：从违例拍往回追

反例是一条**波形**：每一拍都给出使属性在第 N 拍失败的最小激励序列。
**别从中间开始看，按这个顺序：**

```
① 定位违例拍（最后一拍）：属性是在哪一拍、哪个信号上失败的
② 从违例拍向前推 1-2 拍：看被违反的信号/状态在这一拍的**前因**
③ 继续向前，直到找到第一个「本不该发生」的事件
   —— 那才是根因拍；后面的都是它的后果
④ 检查这一步是不是由 `assume` 缺失造成的：
   - 如果这个"非法"事件在协议上根本不该被驱动 → 是缺 assume
   - 如果它是合法驱动、设计却没处理 → 是设计 bug
```

**判据一句话**：把违例拍**当作结果**，把**第一个不可解释的激励拍**当作原因。
拿到原因后，问「这个激励合法吗？」 —— 合法则是 RTL bug，不合法则是 `assume` 漏了。

| 反例看起来像 | 常见真因 | 处理 |
|---|---|---|
| 复位还没释放就开始违例 | 忘了把复位序列 `assume` / 或属性没考虑复位窗口 | 加复位假设，或让属性在复位期 disable |
| 输入在「物理上不可能」的组合下违例 | 输入约束（`assume`）没写全 | 补 `assume` |
| 反例长度长到几百拍、看不出主线 | 属性缺假设，工具在自由输入空间里乱走 | 先补 `assume`，限制输入自由度和 trace 长度 |
| 违例拍是 X（未知值） | X 传播 / 未初始化寄存器 | 明确初始化；考虑开 X-check |
| 反例走了一条「协议上合法但设计没想到」的路 | RTL 真 bug | 修 RTL，回仿真补用例 |

## 版本坑

| 坑 | 表现 | 处理 |
|---|---|---|
| 属性直接写在 RTL 里，形式与仿真**共用一个文件** | 形式的 `assume` 被仿真的激励无意义地满足/冲突 | 形式专用的假设集中在**单独文件**（如 `*_formal.sv`），用 `` `ifdef FORMAL `` 包起来 |
| 换工具版本后 proven 数量突变 | 同一套属性结论变了（引擎/抽象变化） | 结论要**跟着工具版本记录**；版本升级后重跑并在记录里标注版本 |
| `assume` 与 `assert` 混在一处 | 读者分不清哪条是「约束」哪条是「要证的目标」 | 分文件、分前缀（`a_*` vs `p_*`），并在属性文件头写清各自的作用域 |
| 把 `cover` 当 `assert` 用 | 以为「cover 到了」等于「功能对了」 | cover 只证可达，不证正确；正确性必须由 assert 承担 |
| 无 `set_prove_time_limit` | 单条属性吃光整个回归时间 | 设上限，超限的归入 `undetermined` 并**单独跟** |
| 深层次/大位宽设计不切分就整块证 | 全 `undetermined` | 加假设切小、做黑盒抽象（`abstract`）、分块证明、或改用 `假设-证明` 组合（assume-guarantee） |

## 坑

| 坑 | 为什么诱人 | 后果 |
|---|---|---|
| 把 `proven` 当「功能正确」 | 报告上明晃晃一个绿色 | 假设过强时，proven 是**空话**——把输入砍到只剩几条，什么都能证 |
| 把 `unreachable` 当「设计冗余」 | 「到不了就不用管」 | 真不可达和「被自己假设挡住」长得一样，误判会漏掉真 bug |
| 把 `undetermined` 当通过 | 时间用完，报告没红 | 签核意义上它等于「没做」；必须逐条说明接受理由 |
| 反例从中间读 | 中间拍信号最全 | 根因在**前面**，从中间读只会看到一堆后果 |
| 反例一出来就改 RTL | 「工具给了波形，照着修」 | 反例可能是缺 `assume` 造出来的**假反例**，白改 RTL 还把合法行为改坏 |
| `assume` 加得太随意 | 「加一条就不报了，真方便」 | 每加一条 assume 都是在**缩小结论的适用范围**，加到最后 proven 不覆盖任何真实场景 |
| 属性只覆盖正常路径 | 好写、容易过 | 异常/背压/越界没写属性 → 形式给不出「没 bug」的证据 |

> **最值钱的一条**：**`assume` 和 `assert` 是一体的两面。**
> 一条 `assert` 的强度，永远等于「在它上面那堆 `assume` 划出的空间里」的强度。
> 评审形式结果时，**先看假设清单，再看 proven 数量** —— 顺序反了，就等于只看结论不看前提。
> 与 VC Formal 的分工与差异见 `VC_Formal.md`。
