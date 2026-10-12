---
id: KB-DV-TECH-004
title: RAL 寄存器抽象层 —— adapter / predictor / mirror 的职责与失同步
type: 组件卡
domain: 技术与组件
subdomain: RAL
tags: [UVM, SystemVerilog]
roles: [DV工程师]
stages: [TB架构, 编码, 调试]
summary: >
  RAL 的三件套（adapter / predictor / mirror）各自干什么、边界在哪；
  前门访问与后门访问的取舍；以及「镜像与 DUT 失同步」这个几乎每个项目都会踩的坑。
applicable: |
  环境里要访问寄存器；寄存器有副作用（读清零、写触发）需要被跟踪；
  需要在 scoreboard / sequence 里用寄存器名而不是裸地址。
not_applicable: |
  想知道 UVM 组件分层本身怎么分 → `../UVM组件/UVM组件职责与边界.md`；
  想知道寄存器的具体协议时序（APB/AXI-Lite 怎么读写）→ `../../../verify/05_协议与VIP/AMBA/`；
  想知道寄存器模型文件（RDL/IP-XACT）怎么生成 → `../../../verify/04_工具与脚本/`。
prerequisites: [KB-DV-TECH-002]
references: [UVM 1.2 Register Layer (Chapter 15)；IEEE 1800.2]
related: [KB-DV-TECH-002]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# RAL 寄存器抽象层

> **一句话**：RAL 给寄存器配了一份「影子副本」（mirror），让你用**名字**访问、
> 还能**预测**读回来的值。它所有的价值和所有的麻烦，都来自这份影子副本 ——
> 影子一旦和 DUT 不一致，它就变成最贵的一份错误信息。

## 一、职责一览：三件套各干什么

| 组件 | 唯一职责 | 判据 |
|---|---|---|
| `reg_block`（模型） | 描述寄存器的结构、地址、复位值、域 | 纯描述，不含时序 |
| `adapter` | 把 `reg_item`（寄存器操作）**翻译**成总线 transaction（及反向） | 只做**类型转换**，不做检查 |
| `predictor` | 观察总线，**更新 mirror**，使影子副本跟随 DUT | 主动跟踪 DUT 实际写/读 |
| `mirror` | 寄存器模型的**影子值**（`m_mirror` / `get()` 返回） | 是状态，不是组件 |
| `reg_sequence` / `uvm_reg` 方法 | 发起读写（`write()` / `read()` / `update()`） | 激励层入口 |

**和 neighbor 的边界**：

| 该放 | 不该放 |
|---|---|
| `adapter` 里 `reg2bus` / `bus2reg` 只做字段搬运 | 在 adapter 里判断「这个写合不合法」 |
| `predictor` 里 `write()` 更新 mirror | 在 predictor 里驱动总线 |
| `reg_block` 里声明寄存器结构 | 在 reg_block 里写 `@(posedge clk)` |

---

## 二、adapter：只做翻译

```systemverilog
class my_reg_adapter extends uvm_reg_adapter;
  `uvm_object_utils(my_reg_adapter)

  function new(string name = "my_reg_adapter");
    super.new(name);
    provides_responses = 1;   // 读操作需要把响应拿回来更新 mirror
  endfunction

  // 寄存器操作 → 总线 transaction
  virtual function uvm_sequence_item reg2bus(const ref uvm_reg_bus_op rw);
    my_bus_item tr = my_bus_item::type_id::create("tr");
    tr.addr  = rw.addr;
    tr.write = (rw.kind == UVM_WRITE);
    tr.data  = rw.data;
    return tr;
  endfunction

  // 总线 transaction → 寄存器操作
  virtual function void bus2reg(uvm_sequence_item bus_item,
                                ref uvm_reg_bus_op rw);
    my_bus_item tr;
    if (!$cast(tr, bus_item)) begin
      `uvm_fatal("ADAPT", "bus_item 不是 my_bus_item，类型传错了")
      return;
    end
    rw.kind   = tr.write ? UVM_WRITE : UVM_READ;
    rw.addr   = tr.addr;
    rw.data   = tr.data;
    rw.status = tr.error ? UVM_NOT_OK : UVM_IS_OK;
  endfunction
endclass
```

**判据**：adapter 的每一行都应该只是「某字段 → 某字段」。
出现 `if (name == ...)` 的场景判断、出现计数器、出现延迟，就是放错了。

**常见误用**：`$cast` 不做检查直接强转。总线上跑的不止寄存器 transaction
（还有别的 agent 的流量），`$cast` 失败后 `tr` 为 null，访问空指针 —— `\`uvm_fatal` 是必须的。

---

## 三、predictor：mirror 的唯一正确更新路径

`predictor` 接在寄存器的 `bus` agent 的 **monitor analysis_port** 上，
观察每笔真实的总线读写，更新对应寄存器的 mirror。

```systemverilog
class my_reg_predictor extends uvm_reg_predictor #(my_bus_item);
  virtual function void write(my_bus_item tr);
    uvm_reg_bus_op rw;
    // predictor 内部：bus2reg -> 找寄存器 -> 更新 mirror
    super.write(tr);
  endfunction
endclass
```

**为什么必须挂 monitor 而不是挂 driver**：mirror 要反映的是「**DUT 实际收到了什么**」，
不是「我们想发什么」。挂 driver 的 predictor 在总线被阻拦、被重发、被其它 master 插队时，
mirror 会记成「我们发的东西」，而不是 DUT 的行为 —— 这正是失同步的来源之一。

**`auto_predict` 的取舍**：

| 方式 | 机制 | 何时用 |
|---|---|---|
| `predictor`（显式） | 从 monitor 观察更新 | **推荐**，多 master / 有副作用时唯一正确 |
| `set_auto_predict(1)` | adapter 的写直接进 mirror，不看总线 | 单 master、总线无干扰时可用，**但 monitor 必须仍存在**（否则覆盖率/检查会缺） |

**坑**：开了 `auto_predict` **又**挂 predictor，会重复更新 —— 有些寄存器没问题（幂等），
有副作用的寄存器（读清零）会**双倍递减**，mirror 直接错。

---

## 四、前门 vs 后门：取舍表

| | 前门（frontdoor） | 后门（backdoor） |
|---|---|---|
| 路径 | 走总线，经 adapter | 直接 `deposit` / `peek` 到 RTL 信号 |
| 耗时 | 真实总线时序，慢 | 零时间 |
| 副作用 | **触发**读清零、写触发等 | **不触发**任何副作用 |
| mirror 更新 | 会（`predictor` 观察） | **不会**（绕过了总线） |
| 适用 | 功能验证、协议合规、有副作用的寄存器 | 初始化、大配置、前后仿深寄存器 |

**判据**：

- 想验证**寄存器访问路径本身**（读写能否正确到达）→ 前门
- 想做**环境初始化**，且寄存器无副作用或副作用可接受 → 后门更快
- 寄存器**有副作用**（读清零、写 1 清中断）→ **只能用前门**，后门会跳过副作用，且 mirror 不同步

**后门的正确用法**：`uvm_reg::poke()` / `peek()` 后，**手动修正 mirror**（或用 `set()` 后
`update()` 前门写一遍），否则 mirror 和 DUT 从此刻起就开始漂移。

```systemverilog
// 后门初始化后，把镜像也设成同一个值
regmodel.ctrl.set(32'h0000_0001);       // 设期望
regmodel.ctrl.poke(status);             // 后门写 DUT（不动 mirror）
regmodel.ctrl.set(32'h0000_0001);       // 显式对齐 mirror
```

---

## 五、镜像与 DUT 失同步：四个来源

**这是 RAL 最高频、最难查的问题** —— 症状是「mirror 说这个域是 1，读出来是 0」，
或「check 全过，但功能错了」。

| 来源 | 为什么诱人 | 症状 | 修正 |
|---|---|---|---|
| 后门访问没补 mirror | 「后门是加速，不改变行为」 | 后门改过的域 mirror 没跟上 | 后门后手动 `set()` / `update()` |
| `auto_predict` + predictor 双更新 | 「都接上更保险」 | 读清零寄存器 mirror 值双倍递减 | 二选一，标准做法是只用 predictor |
| DUT 侧副作用未建模（读清零/写触发） | 「模型里没写这个属性」 | 每次读 mirror 和 DUT 差一个值 | 在 reg model 里声明 `uvm_reg_field` 的 volatile / access 属性 |
| 复位后没 reset mirror | 「复位是环境自动的」 | 复位后 mirror 还停在复位前的值 | `regmodel.reset()` 在 reset 序列里显式调用 |

**判据（最有用的一条）**：
`regmodel.get()` 返回的是 **mirror**，不是 DUT。
任何「我以为读的是 DUT 实际值」的地方，都要先确认 mirror 是否同步 ——
`reg.read()`（前门）会更新 mirror，`get()` **不会**去读 DUT。

**自检手段**：定期（或在每笔 test 末）用 `regmodel.mirror(status, UVM_CHECK)`
走前门读一遍 DUT、和 mirror 比对 —— 这是**唯一**能主动发现失同步的方法。

---

## 六、检查清单

| 检查项 | 问题 |
|---|---|
| adapter | `reg2bus` / `bus2reg` 只做字段搬运吗？`$cast` 有检查吗？ |
| predictor | predictor 挂的是 **monitor** 而不是 driver 吗？ |
| 双更新 | `auto_predict` 和 predictor **没有同时**开吧？ |
| 后门 | 每处 `poke` / `peek` 后都对齐 mirror 了吗？ |
| 副作用 | 读清零 / 写触发的域在模型里声明了吗？mirror 会正确预测吗？ |
| 复位 | reset sequence 里调了 `regmodel.reset()` 吗？ |
| 总线宽度 | adapter 处理多拍/窄总线（如 32 位总线访问 64 位寄存器）了吗？ |
| 自检 | 回归里有定期 `mirror(..., UVM_CHECK)` 吗？ |
| 多 master | 多个 master 读同一寄存器时，predictor 能区分谁写的吗？ |

## 七、坑

| 坑 | 为什么诱人 | 后果 |
|---|---|---|
| 用 `get()` 当「读 DUT」 | 方法名像「取值」 | 拿到的是 mirror，DUT 值根本没去读，测试虚过 |
| 后门改寄存器不管 mirror | 后门就是为省事 | 从这一刻起 mirror 与 DUT 永久漂移，后续所有 `get()` 都错 |
| `auto_predict` + predictor 并存 | 「两个都接更保险」 | 有副作用寄存器 mirror 双更新，越跑越偏 |
| predictor 挂 driver | 「driver 就在手边」 | 发出去但 DUT 没收到的写也进了 mirror，被阻拦/重发的场景全错 |
| 模型里漏声明读清零 | 「模型只管地址和复位值」 | 读一次 mirror 就和 DUT 差一个值，且每次读都差 |
| adapter 里加业务判断 | 「顺手在这检查」 | adapter 承担了 checker 职责，换总线要连检查一起改 |
| 复位后不 reset model | 「复位是 DUT 的事」 | mirror 停在旧值，复位后第一笔访问就可能误判 |
| 前门做大批量初始化 | 「前门才是真访问，更可信」 | 初始化就耗掉大半仿真时间，且暴露在总线 timeout 风险下 |

**最值钱的两条**：`get()` 当「读 DUT」、后门访问不补 mirror ——
它们让 mirror 静默漂移，而**漂移了没人知道**，直到某个 check 报出莫名其妙的失败。

---

## 八、出口

| 下一步 | 在哪 |
|---|---|
| 寄存器总线（APB / AXI-Lite）的协议时序 | `../../../verify/05_协议与VIP/AMBA/` |
| 环境里 agent / scoreboard 怎么装配 | `../UVM组件/UVM组件职责与边界.md` |
| 寄存器文件（RDL / IP-XACT）怎么变成 UVM 模型 | `../../../verify/04_工具与脚本/` |
| 寄存器访问的覆盖率怎么建 | `../../../verify/07_度量与报告/覆盖率模型/功能覆盖率建模.md` |
