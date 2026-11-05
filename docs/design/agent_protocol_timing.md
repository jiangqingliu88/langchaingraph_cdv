# Agent 协议时序：怎么生成、怎么自检、错了怎么查

> 2026-11-05 · 起因：`npu_sched` 的 driver 不发 `valid`、monitor 每拍采样，
> 导致 driver / monitor 的"事务"对不上，loopback 还在空比一场（全输入 agent
> 的 `compare_fields` 没有可比的输出字段 → 20 笔全 match 的**假绿**）。

## 1. 问题不是"某一条 test 挂了"，是**四层语义都没写死**

| 层 | 原来的行为 | 后果 |
|---|---|---|
| 驱动 | `valid` 是随机事务字段，`1'b0` 也照样发 | 总线上"没有事务"，monitor/SCB 全错位 |
| 采样 | monitor 每个时钟沿都采 | idle 拍被当成事务；多测出根本不存在的交易 |
| 自检 | loopback 只比"驱动侧 output 字段 vs 监控侧" | 全输入 agent 没有 output 字段 → **空比对恒真** |
| 判据 | 只认旧版 `UVM_ERROR : 3` | 新版 Questa 的逐条 `UVM_ERROR file(line)` 全漏（实测 139 条） |

## 2. 四道防线（生成侧就已经写进模板）

### 2.1 驱动语义：`valid` 由事务驱动置起

`driver_master.sv.j2` / `driver_slave.sv.j2` 会识别 **output/input 侧以
`valid` 结尾的端口**：

```systemverilog
// master：发送事务时必然置 valid；有 ready 时保持 payload 稳定直到握手
req.<valid> = 1'b1;
vif.master_cb.<valid> <= 1'b1;
do @(vif.master_cb); while (vif.master_cb.<ready> !== 1'b1);   // 有 ready 才等
@(vif.master_cb);
vif.master_cb.<valid> <= 1'b0;
```

- 形态判定：**output 有可驱动端口 → master 驱动；全输入 agent → slave 驱动**
  （loopback env / test / scb 三处同一口径，不再固定 master→slave）。
- 复位释放后，从端先把 input 端口压到 `0`（合法空闲值），避免 `'z` 经
  `assign` 解成 X。

### 2.2 采样语义：只在**有效事务**上采

`port_monitor.sv.j2`：

```systemverilog
do begin
  @(vif.mon_cb);
  if ($isunknown(vif.<valid>))
    `uvm_error("PROTO", "<valid> 为 X —— 采样时序无法判定")
  if (++guard > 10000)
    `uvm_fatal("PROTO", "<valid> 10000 拍内从未置起 —— driver 时序错误")
end while (vif.<valid> !== 1'b1);
// 有 ready 时等握手完成再采
```

idle 拍不再产生事务；"valid 永远不置起"从"悄无声息"变成 **fatal**。

### 2.3 接口断言：与采样独立的第二执行点

`interface.sv.j2` 在 `*valid` 存在时自动生成 concurrent assertions：

```systemverilog
assert property (@(posedge clk) disable iff (!rst_n) !$isunknown(valid))
  else $error("[PROTO] valid 为 X —— 事务时序不成立");

// 有 ready 时另加：
assert property (@(posedge clk) disable iff (!rst_n)
                 (valid && !ready) |=> (valid && $stable(payload...)))
  else $error("[PROTO] valid 等待 ready 期间撤销或 payload 变化");
```

这是**协议规则的 SVA 侧**；monitor 的 `[PROTO]` 是采样侧。两处同口径，
任何一处失效，另一处仍能在回归里拦下。

### 2.4 判据与门禁：错误不许被吞

- 回归 `run_cmd` 同时识别 Questa 的**旧/新** `UVM_ERROR` 格式
  （`UVM_ERROR : 3` 与 `UVM_ERROR file(line)`），并保留 `Fatal/Errors:`；
- loopback 在 p0 之前；loopback 不过 → `blocked_at=loopback`，不进 DUT 功能级；
- 签核层：任何 `UVM_ERROR` → 用例 fail → 分级门控 → `NEEDS_FIX`，
  不会出现"时序错但签核 CONDITIONAL"。

## 3. 已经踩过、并修掉的三个具体坑

1. **全输入 agent 的 loopback 是空比对**：`compare_fields` 只比 output 端口，
   而该 agent 全是 input → 没有字段可比，恒 PASS。
   修法：驱动侧按端口方向自动选择（master 或 slave），expected 取**真正驱动
   方**的 `driven_ap`，actual 取**真正采样方**的 monitor。
2. **ACTIVE slave sequencer 与 UVM 内部 `req_fifo` 重名**：UVM 的
   `uvm_sequencer_base` 自己有一个叫 `req_fifo` 的 child；自定义事件 FIFO 若
   也叫这个名，build 直接 `UVM_FATAL [CLDEXT] Cannot set 'req_fifo' as a child`。
   修法：成员名不变，实例名改 `mon_req_fifo`。
3. **复位后 bus 是 `'z` → X**：从端 idle 不驱动，monitor 的 valid 检查在第一笔
   事务前就报 X。修法：复位释放后把从端负责的 input 端口压 `0`。

## 4. 出了问题时怎么查（按这个顺序）

1. `grep "\[PROTO\]" sim_vsim.log` —— 先分清是 **X** 还是 **valid 不置起**；
2. `grep "\[DRV\]\|\[MON\]" sim_vsim.log` —— 看驱动侧发了什么、采样侧看到了
   什么，按 `sprint()` 的字段逐项对；
3. 若 `[DRV]` 有、`[MON]` 没有：看 monitor 的 valid 等待条件与 driver 的
   `valid` 置起时机（含 `ready` 握手）；
4. 若 loopback 只有"空拍"或 `total=0`：先看驱动方向是否选对（全输入 agent
   必须由 slave 驱动）；
5. 最后才怀疑 DUT：`[SCB_DUT]` / `[SCB]` 的 mismatch 才是功能问题。

## 5. 边界

- 只对**按命名可识别**的握手信号生效：`*valid` / `*ready`。自定义协议若用了
  别的名字，请改成这两个后缀，或在 callback `post_drive/post_sample` 里加检查。
- APB / AXI 走各自已有的协议时序（`agent.protocol == 'apb'` 等），不被通用
  规则覆盖。
- `$stable(payload)` 只覆盖**驱动侧的 output 字段**；从端驱动的 payload 稳定性
  由 monitor 侧同口径检查，后续可加。
