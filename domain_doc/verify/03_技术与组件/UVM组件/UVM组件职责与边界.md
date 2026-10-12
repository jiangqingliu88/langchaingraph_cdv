---
id: KB-DV-TECH-002
title: UVM 组件职责与边界 —— 这段逻辑该放谁那
type: 组件卡
domain: 技术与组件
subdomain: UVM组件
tags: [UVM, SystemVerilog]
roles: [DV工程师, 架构师]
stages: [TB架构, 编码]
summary: >
  driver / monitor / sequencer / agent / env / test 各自该干什么、不该干什么。
  重点不是名词解释，而是「一段新逻辑该落在哪个组件」的判据，以及放错之后的典型症状。
applicable: |
  搭新验证环境时的组件划分；往已有环境加功能时判断「这逻辑该不该塞进 driver」；
  评审 TB 架构时发现某组件职责过载。
not_applicable: |
  想知道 transaction 的激励该覆盖什么、约束怎么写 → `../SystemVerilog/随机约束.md`；
  想知道「为什么用 UVM、分层的理论依据」→ `../../../verify/02_验证方法学/UVM/`；
  想知道寄存器访问怎么接 → `../RAL/RAL寄存器抽象层.md`。
prerequisites: [SystemVerilog 类与 OOP、工厂与 phase 基础]
references: [IEEE 1800.2 UVM LRM；UVM 1.2 User's Guide（Chapter 4–5）]
related: [KB-DV-TECH-001, KB-DV-TECH-004]
maintainer: 验证方法学组
version: 1.0
status: 草稿
created: 2026-10-12
updated: 2026-10-12
---

# UVM 组件职责与边界

> **一句话**：UVM 组件的划分不是「名字不同」，是**职责边界**不同。
> 判断一段逻辑放哪，只看一个问题：**它是在「产生激励」「观察行为」还是「判断对错」？**
> 这三件事必须住在三个不同的组件里，混在一起就再也没法复用和调试。

## 一、职责一览

| 组件 | 唯一职责 | 一句话判据 |
|---|---|---|
| `driver` | 把 transaction **变成** 引脚时序 | 只跟**信号**打交道，不跟**判断**打交道 |
| `sequencer` | 给 driver **排队** transaction | 只管顺序与仲裁，不认识信号，不认识对错 |
| `monitor` | 从引脚**观察**、还原成 transaction | **只读不写**，绝不动一根输出信号 |
| `agent` | 把 driver+sequencer+monitor **打包** | 只做装配与配置分发，不含时序逻辑 |
| `env` | 装配多个 agent + scoreboard + coverage | 只做**连接**，不含任何激励或检查逻辑 |
| `test` | 选 **sequence**、配 **config** | 只做「这一把测什么」，不实现测法本身 |
| `scoreboard` | 比较 **期望 vs 实际** | 只判断，不产生激励、不接触引脚 |

**这张表就是本卡的全部**。下面是把每条展开成「判据 + 反例」。

## 二、driver：只负责「变信号」

**职责**：从 sequencer 取 transaction，按协议把它展开成引脚上的时序波形。

```systemverilog
class my_driver extends uvm_driver #(my_item);
  virtual my_if vif;
  task run_phase(uvm_phase phase);
    forever begin
      seq_item_port.get_next_item(req);
      drive_one(req);                 // 只做「取值 → 按时序放到引脚」
      seq_item_port.item_done();
    end
  endtask

  task drive_one(my_item it);
    @(posedge vif.clk);
    vif.valid <= 1'b1;
    vif.data  <= it.data;
    do @(posedge vif.clk); while (!vif.ready);   // 握手：valid 保持到 ready
    vif.valid <= 1'b0;
  endtask
endclass
```

**不该干的**：

| 不该做的事 | 症状 | 该去哪 |
|---|---|---|
| 在 driver 里 `if (data == 期望) pass++` | driver 里出现 scoreboard 逻辑 | `scoreboard` |
| 在 driver 里 `foreach` 覆盖点采样 | driver 里出现 `covergroup` | `monitor` / `coverage collector` |
| 在 driver 里生成随机值 | driver 里出现 `randomize()` | `sequence` / `transaction` 约束 |
| 在 driver 里判断「协议违规就报错」 | driver 里出现 `\`uvm_error` | `monitor` + `checker`/`断言` |

> **判据**：driver 里除了「`req` 的字段 → 引脚时序」之外，任何 `if` / 计数 / 比较，
> 都要先问一句「这属于判断还是属于驱动」。属于判断的，搬走。

## 三、sequencer：只管排队

**职责**：维护 transaction 序列、响应 arbitration、支持 `seq_item_port` 的 request/grant。

**不该干的**：任何与信号、时序、检查有关的逻辑。
sequencer **不应该**有 `virtual interface`，它不认识引脚。

**常见误用**：为了「顺序可控」把协议时序塞进 sequence 的 `body()` 里 ——
sequence 里出现 `@(posedge vif.clk)` 就是信号层泄漏。**时序归 driver，sequence 只描述操作顺序。**

## 四、monitor：只读，且永远只读

**职责**：观察引脚（或 `virtual interface`），把信号还原成 transaction，
通过 `analysis_port` 广播给 scoreboard / coverage。

```systemverilog
class my_monitor extends uvm_monitor;
  uvm_analysis_port #(my_item) ap;
  virtual my_if vif;

  task run_phase(uvm_phase phase);
    forever begin
      my_item it;
      @(posedge vif.clk iff vif.valid && vif.ready);   // 采样点：握手成立那一刻
      it = my_item::type_id::create("it");
      it.data = vif.data;
      ap.write(it);                                     // 单向往外，不回头
    end
  endtask
endclass
```

**铁律**：monitor **不驱动任何信号**，不 `<=` 任何 `vif.xxx`。
一旦 monitor 写信号，它就从「观察者」变成了「参与者」，DUT 行为被观测者改变，
所有基于它的覆盖率与比较全部失去意义。

| 不该做的事 | 症状 |
|---|---|
| monitor 写 `vif` 任何信号 | 观察改变被观察对象 |
| monitor 做 pass/fail 判断 | 观测与判断绑死，无法只跑 coverage 不跑检查 |
| monitor 只在 `posedge clk` 裸采，不看 `valid/ready` | 采到无效周期，transaction 数是虚的 |
| monitor 用 `#10` 延迟采样 | 与时钟相位绑死，换频率就错 |

> **判据**：monitor 的每一根信号连接方向都是「读」。出现任何一次「写」，
> 就是设计错误，不是风格问题。

## 五、agent：只装配，不含逻辑

**职责**：按 `is_active` 决定是否例化 driver+sequencer；
把 monitor 的 `analysis_port` 暴露出去；把 `config` 分发给子组件。

**不该干的**：`connect_phase` 里 `if (...) begin ... end` 的时序逻辑、
`run_phase` 里的行为实现。agent 是「接线盒」，不是「行为体」。

**`is_active` 的语义**：`UVM_ACTIVE` = 又要驱动又要观察；`UVM_PASSIVE` = 只观察。
**一个 agent 被动化后，driver/sequencer 不该被例化**，而不是「例化了但不驱动」。

## 六、env：只连接

**职责**：例化 agent / scoreboard / coverage，用 `connect()` 把它们连起来。

| 该做 | 不该做 |
|---|---|
| `agent.mon.ap.connect(sb.imp)` | 在 env 里做 `if (data != exp)` |
| 例化并配置子组件 | 在 env 里写 `@(posedge clk)` |
| 把 `config_db` 分发下去 | 在 env 里实现激励 |

> **判据**：env 的 `run_phase` 应该是空的（或只有 `super.run_phase`）。
> 如果 env 的 `run_phase` 里有内容，几乎一定是某一层职责放错了位置。

## 七、test：选 sequence，不实现 sequence

**职责**：设置 `config_db` 配置、`raise/drop_objection`、
启动顶层 sequence（`uvm_sequence::start` 或 `default_sequence`）。

**不该干的**：在 test 里写协议时序、写检查、写激励生成循环。
test 的 `run_phase` 应当**短**：配好，起 sequence，等结束。

```systemverilog
class smoke_test extends base_test;
  `uvm_component_utils(smoke_test)
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    uvm_config_db#(uvm_object_wrapper)::set(
      this, "env.agt.sqr.run_phase", "default_sequence",
      smoke_seq::type_id::get());
  endfunction
endclass
```

## 八、边界速查：一段新逻辑放哪

| 这段逻辑是什么 | 放哪 | 为什么不放邻居 |
|---|---|---|
| 「READ 命令要拉 2 拍 valid」 | `driver` | 这是引脚时序，sequence 不认识引脚 |
| 「先发 3 个 READ 再发 1 个 WRITE」 | `sequence` | 这是操作顺序，driver 不认识「操作」概念 |
| 「拍到的 data 和模型对不上」 | `scoreboard` | 这是判断，monitor 只观察不判断 |
| 「这个 coverpoint 在 valid&&ready 时采样」 | `monitor` 外挂 coverage | 采样点必须是观察点，不能是驱动点 |
| 「本用例只跑 passive agent」 | `test` | 这是本次运行的选择，不是环境结构 |
| 「这两个 agent 的 mon 都要接同一个 sb」 | `env` | 这是装配关系 |
| 「复位期间不采覆盖」 | `coverage` 的 `disable iff` | 不是 monitor 的责任（monitor 照常观察，只是不采样） |

## 九、常见写错

| 写错 | 为什么诱人 | 后果 |
|---|---|---|
| driver 里做检查 | 「值就在手边，顺手比一下」 | driver 变胖，检查无法独立开关；只跑 coverage 时必须连检查一起跑 |
| monitor 驱动信号 | 「差点激励，monitor 里补一下最方便」 | 观测改变 DUT，覆盖率与比对全部失真 |
| sequence 里 `@(posedge vif.clk)` | 「顺序要精确控制」 | 信号层泄漏进激励层，换协议要重写 sequence |
| agent 被动化却仍例化 driver | 「反正不驱动，留着不影响」 | driver 的 `run_phase` 可能仍取 item，悬空的 sequencer 让调试困惑 |
| env 里有 `run_phase` 行为 | 「连接都在 env，逻辑也放这」 | 装配层承担行为，环境无法被复用成不同 test |
| test 里写大段时序 | 「这样最省事」 | 用例不可参数化，每个场景都要复制一份 test |
| scoreboard 产生激励 | 「需要回环激励」 | 判断层与激励层耦合，激励改了检查也得改 |
| 所有组件用同一个 `virtual interface` 指针却各自驱动 | 「省一个 interface」 | 多个 driver 抢同一组引脚，行为不可预测 |

**最值钱的两条**：monitor 写信号、driver 做检查 ——
前者污染观测，后者把「测到了」和「测对了」搅成一团。

## 十、出口

| 下一步 | 在哪 |
|---|---|
| 激励的约束与分布怎么写 | `../SystemVerilog/随机约束.md` |
| 覆盖率在哪里采样、采样什么 | `../../../verify/07_度量与报告/覆盖率模型/功能覆盖率建模.md` |
| 寄存器的前门/后门访问怎么接进环境 | `../RAL/RAL寄存器抽象层.md` |
| UVM 为什么这么分层 | `../../../verify/02_验证方法学/UVM/` |
