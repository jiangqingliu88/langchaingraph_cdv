以下是为您识别的 Markdown 文档内容，为您进行了排版和代码块格式化。

***

# npu_player 实现架构

本文档描述 `dv/npu_top_uvm/seq_lib/player/` 下 Player 组件的实现架构：它把一份 `commands.tsv`（可选 `commands.json` 元数据）变成一段**可预检、可观测、可中断**的仿真执行计划。范围覆盖 Player 自身（含 runtime 契约与内存 op），不重复 agent/monitor 内部文档；peer/env 集成见 `peer_integration.md` 与各 handler 文档。

---

## 1. 组件清单与依赖方向

| 文件 | 角色 | 主要导出 | 依赖 |
| :--- | :--- | :--- | :--- |
| `npu_player_value.svh` | tsv 字段位 | `npu_player_value` / `npu_player_value_parser` | SV 标准库 |
| `npu_player_program.svh` | 命令流容器 | `npu_player_action` / `npu_player_program` / `value` | |
| `npu_player_memory.svh` | direct memory op | `memory_player_action()` / `program.memory.pkg(en) 注入` | |
| `npu_player_runtime.svh` | 运行时类型 + 服务契约 | `npu_player_status` / `npu_player_receipt` / `npu_player_observation` / `npu_player_clock` (pure virtual) / `npu_player_event_bus` / `npu_player_runtime` / `npu_player_cfg` | `uvm_pkg` |
| `npu_player_trace_hook.svh` | trace facade 契约 | `npu_player_trace_hook.write_snapshot()` | - |
| `npu_tb_player.svh` | **核心协调器** | `npu_tb_player` / `runtime.program_memory.value` | |
| `npu_top_playback_vir_seq.svh` | 入口 sequence | `npu_top_playback_vir_seq (objection 持有者)` | `tb_player` |
| `npu_top_player_pkg.sv` | package 入口 | 上述全套 | `uvm_pkg` |

**依赖铁律**：所有 `svh` 文件允许向上（value → program → memory → runtime → tb_player）依赖。`npu_player_trace_hook` 反向独立：env 包的 facade 依赖它，而被 facade 注入的 Player 不依赖 env pkg——这是有意为之，让 `player` pkg 可以独立部署。

```text
      +-----------------------+
      | npu_top_playback_vir_seq |
      | vir_seq (objection)   |
      +-----------------------+
                 | play()/status
                 v
      +-------------------+        +----------------------+
      |  npu_tb_player    |<------>| npu_player_runtime   |
      | (core of this doc)|        | clock_service : pure |
      +-------------------+        | events        : ctr bus|
      | bind() / preflight/        +----------------------+
      | v save result /
      +-------------------+
                 | connect memory
                 v
      +-------------------+        +----------------------+
      | npu_memory_       |        | env facade impl      |
      | model (+owner)    |        | (npu_player_         |
      +-------------------+        |  trace_hook)         |
                                   +----------------------+
```

---

## 2. 关键抽象与边界

### 2.1 `npu_player_clock` (纯虚)

```systemverilog
pure virtual task wait_ready(output npu_player_receipt);
pure virtual task wait_cycles(longint unsigned, output npu_player_receipt);
pure virtual task tick(output npu_player_receipt);  // 不被 reset 打断
pure virtual function longint unsigned epoch();
```
*   **契约**：`tick()` 与 `wait_cycles()` 是两种节拍。
    *   `wait_cycles` 可以被 reset 中止（用于 `wait_cycles` / `wait_event` 等业务等待）；
    *   `tick` 不被 reset 中止，由独立者/时钟线消费（用于 `cfg.run_timeout` / `watchdog` 路径）。
    *   env 在装配阶段注入具体实现（见 `npu_top_player_clock_adapter.svh`），Player 不感知 posedge，不直接 `@(posedge clk)`。

### 2.2 `npu_player_event_bus`

*   计数事件，不是脉冲；`publish` 在 `wait` 之前发生仍可被消费。
*   两种 producer 显式分开：
    *   `declare_producer()` —— env/monitor 标注外部生产者；
    *   `declare_local_producer()` —— preflight 提交的本文件 `signal_event` 生产者。
*   `set_epoch()` / `reset` 推进 `epoch`、**清空计数**、保留 producer 注册。
*   这条总线是 preflight「静态死锁检测」与 `running` 动态等待**的公共数据源**。

### 2.3 `npu_player_receipt`：动作“可推进”的证据，不是“完成”

| 字段 | 语义 | 反模式 |
| :--- | :--- | :--- |
| `status` | 推进条件是否满足 | **DUT 已退休** |
| `handle` | 操作分配的事务 `id` | `action id`, 也不是 hardware tag |
| `phase` | 满足的相位：`cmd accept` / `rsp accept` / `dispatch local` / `event consumed` / `memory * complete` / `checkpoint` / `group marker` / `watchdog armed` / `event published` / `queued` | 绝不允许冒充 `cmd accept` |
| `epoch` | 动作推进时的 reset 代 | 必须等于 `consumer reset epoch`，否则升级为 `NP_EXEC_ERROR` |

Player 在 `run_actions()` 里对 hardware receipt 做显式 back-check（`npu_tb_player.svh:770`），防止 agent 用 `queued/acked` 等模拟相位冒充真正的 `cmd accept`。

### 2.4 `npu_player_cfg`

| 字段 | 默认 | 含义 |
| :--- | :--- | :--- |
| `commands_file` / `metadata_file` | `-` / `-` | 输入；metadata 可空 |
| `core_id` | 0 | 校验 `dispatch_skip` 与 metadata 归属 |
| `isa_revision_allow` / `address_schema_allow` | V1.4 | 允许的 bundle profile 白名单（append-only，与 `npu_memory_cfg` 同源）|
| `raw75_layout` | "unspecified" | 仅 `flag_msb` 允许 data75 形式 |
| `default_event_timeout_cycles` | 100000 | `wait event` 缺省超时 |
| `action_timeout` / `finish_timeout` / `run_timeout` | 1ms / 1ms / 1s | 三级熔断 |
| `max_file_bytes` / `max_actions` / `max_event_names` | 64MB / 1e6 / 4096 | 预算 |
| `trace_file` / `result_file` | `-` / `-` | `trace.tsv` 与 `result.json` |

---

## 3. 状态机

```text
build_phase()
  | config_db.get(cfg / runtime / optional memory)
  | optional: trace_file open + header    - v2 起
  v
[ IDLE ]
  | bind_sequence()/connect_memory()  (env.connect_phase)
  v
[ BOUND ]  bindings_sealed=0
  | preflight()
  v
[ READY ]  bindings_sealed=1, preflight_complete=1
  | play()
  v
[ RUNNING ]  playback_attempted=1, playback_active=1
  | run_actions -> request_stop_once -> finish_targets
  v
[ DONE ]   playback_active=0, status={NP_SUCCESS, NP_*}
             final_phase() 复查 report_server, 可能翻成 NP_EXEC_ERROR
```
*   one-shot：`playback_attempted/playback_active` 任一置位后再 `play()` 立即 `UVM_ERROR`。
*   re-bind：`bindings_sealed` 任一置位后再 `bind_sequence` 立即拒绝。
*   **重启**：要换命令流，必须 `new` 一个 Player（接口要求，无运行机制）。
*   `status` 枚举（来自 `npu_player_runtime.svh:4:5`）：
    `NP_SUCCESS / NP_INPUT_ERROR / NP_BLOCKED / NP_TIMEOUT / NP_EXEC_ERROR / NP_MODEL_LIMIT`。

---

## 4. preflight：四道扫描，**全部通过前不允许副作用**

这是整个文件**最重要的正确性性质**。四道顺序由 `npu_tb_player.svh:428` 的 `preflight()` 主循环给出：

| 道 | 做 | 副作用 |
| :--- | :--- | :--- |
| ① 读+normalization | `playback.scan` + `attach metadata` + 对每条 action `normalize_raw` | 仅填字段，不改外部状态 |
| ② 静态 buffer 校验 | `case(op)`：字段数、batch 配对、两 stream `wait_event` 死锁、`dispatch` 校验 | 计数 `available_local_events`，但不提交 |
| ③ 外部 op `validate()` | `operation_sequence.validate()` (sequence 直接) / `validate_direct()` (direct op) | 必须 read-only |
| ④ declaration | `runtime.events.declare_local_producer(...)` 提交本文件 producer，置 `bindings_sealed / preflight_complete` | **首次副作用**，之前任意失败都干净 |

中途任何一步 0 共享 event bus。DUT、memory 均未被触碰。

### 4.1 normalize_raw() (`npu_tb_player.svh:405`)

两种合法容器：
*   `{cmddata[73:0], instr_flag}` —— 74 位 + 1 位 flag
*   `{data75[74:0]}` —— 仅当 `cfg.raw75_layout == "flag_msb"`，否则 `NP_BLOCKED`
不检查 opcode 合法性（归 ISA decoder agent）；仅检查容器宽度、互斥源与 `layout`。

### 4.2 向 stream `wait_event` 死锁检测（`:482-497`，`available_local_events` 计数-消耗）
仅当事件**无外部 producer** 时静态校验本文件前面是否已 `signal_event` 足够次数；
外部 producer 的事件不在此检查（没法静态判定其时机），由 `running` 时 `timeout_cycles` 兜底。

---

## 5. 运行期：`run_actions()` 的逐步契约

`npu_tb_player.svh:723`（`execute_one` 在 `:641`）：

```text
1. runtime.clock_service.wait_ready()          (env 就绪才允许起步)
   failure -> fail(NP_BLOCKED)
2. consumer_reset_epoch = clock_service.epoch()
   events.epoch() 必须 == consumer_reset_epoch, 否则 NP_BLOCKED
3. foreach playback_actions[i]:
   if clock.epoch != events.epoch -> fail (跨 action 的 reset 检测)
   action_started.write(action)
   -> trace START
   timed execute:
     fork { execute_one ; #(cfg.action_timeout) } join_any
     disable fork
     超时 -> NP_TIMEOUT，否则用 execute_one 的 receipt
   execute_one 三路分流:
     built-in                         -> execute_builtin
     外部 op + has_sequence_binding   -> make_sequence + start(sequencer), 取 receipt
     direct (mem init/mem_scrub /
           子类可覆写扩展, 如
           npu_top_peer_player 的
           peer_cfg)                 -> execute_direct (基类是 memory_player_action)
   hardware receipt 后置检查:
     NP_SUCCESS && kind==NP_HARDWARE ->
     phase == "cmd accept" && handle != "" && epoch == consumer_reset_epoch
     否则 -> NP_EXEC_ERROR("CMD executor must return actual cmd accept ...")
   action_observed.write(action, receipt),
   fail if receipt null/!=NP_SUCCESS -> return
   completed_actions++
   -> trace END
   action_finished.write(action)
```

注意 "completed actions" 的语义（`:24` 注释）：“reaching their own advancement conditions, not FU retirement count” —— 先 `accept` 即 +1，不代表 DUT 写完/退休。

---

## 6. built-in ops

| op | 类别 | 副作用 / receipt.phase |
| :--- | :--- | :--- |
| `wait_cycles(n)` | clock | `clock.wait(n)` 返回 receipt |
| `nop` | clock | `clock.wait(1)` |
| `signal_event(event)` | event | 通过 `runtime.events.publish`，失败 (unregistered producer/stale epoch) -> `NP_EXEC_ERROR`；成功 `phase=event_published` |
| `wait_event(event, count, timeout_cycles)` | event | 循环 `clock.wait(1)`，连控检查 `events.count >= count`，超时 `NP_TIMEOUT`；epoch 不一致 `NP_EXEC_ERROR`；成功 `phase=event_consumed` |
| `checkpoint(tag/shared_region)` | 控制标记 | `phase=group_marker`，运行期 no-op，成对语义在 preflight 拒绝 |
| `watchdog(deadline, timeout_cycles)` | 计数登记 | 注册 `watchdog_deadline_by_action[id]` = `command_clock_ticks + n`；**不** fork；由 `cycle_watchdogs` 异步判，`phase=watchdog_armed` |
| `checkpoint` / `phase=checkpoint` | 不阻塞, 无硬件语义, 异步 bundle 用 | `status=SUCCESS` |
| `dispatch_mask(mask)` | 编译器 | 仅校验 16bit 字段；运行期 `phase=dispatch_local` |
| `dispatch_skip(core_id, target_mask)` | 编译器 | 校验 `core_id == cfg.core_id` 且 `target_mask[core_id]==0` 则 skip 不命中本核 |
| `raw_cmd {cmddata + instr_flag}` | 硬件 | normalize 后 `kind=NP_HARDWARE`，走 sequence 路径 |
| `mem_init / mem_scrub` | direct | 走 `execute_direct` -> memory_player_action，`phase=memory_*_complete` |
| `validate_direct` / `execute_direct` | 是 virtual 扩展点 (`npu_tb_player.svh:155`)：子类先判自家 op，未命中回退 `super.*`。当前唯一子类扩展是 `npu_top_peer_player` 的 `peer_cfg`（见 §10）。 |

---

## 7. watchdog 与三个时基

```text
command_clock_ticks    : 单源，reset 不清 (cycle_watchdogs 私召)
clock_service.epoch()  : reset 推进的代, run_actions 起点强制 consumer_reset_epoch
events.epoch()         : 必须始终等于 clock.epoch，否则任何动作立刻 fail
```
`cycle_watchdogs()` (`:788`) 每拍：
1.  `clock_service.tick(clk receipt)` 阻塞等下一拍；receipt null/!=NP_SUCCESS -> fail
2.  **反卡死检查**：连续两次 `tick realtime` 不前进 -> `NP_EXEC_ERROR("clock tick did not advance simulation time")`（捕捉 `clock_adapter` 不迭代即返回死循环）
3.  `#0` 回读 `epoch`，与捕获时不一致 -> `NP_TIMEOUT`/fail
4.  对每个 `watchdog_deadline_by_action[id]` 判定 `current >= deadline` -> `NP_TIMEOUT`

`watchdog` 与 `cfg.action_timeout`（per-action 熔断）、`cfg.run_timeout`（全局熔断）是三层独立防线，不存在优先级问题：任何一层先到即发一个 `fail()`。

---

## 8. 关闭协议 (shutdown)：`stop -> drain-all -> finish-all`

`finish_targets()` (`:685`) 刻意两阶段而非 "per-target drain+finish"：

*   阶段 0：对每个 target 调 `drain_target(id, receipt)`；
*   阶段 1：对所有 target 调 `finish_target(id, receipt)`；
*   这样 checker 的 `finalize()`（统计响应）**不可能**早于任一 agent 的 drain。
*   每次调用被 `#(cfg.finish_timeout)` 的循环包裹，`drain invoked by target` 的 `final check invoked by target` 防止同一槽用被打破时重复**注入**（可能已有部分副作用）。
*   `request_stop_once()` (`:660`) 用 `stop_requested` 把 stop 幂等化；
    *   `status=NP_SUCCESS`：reason="EOF; stop new background work"
    *   否则：reason="error"（原始失败原因）
*   基类 `stop_target/drain_target/finish_target`（`:194-200`）是 stub，直接 fail；
*   **子类契约**（例：`npu_cmd_tb_player`）通过 `cmd_agent.stop.new_commands / drain / finish_ok` 实现。`validate_shutdown_target()` 在 preflight ④前被逐一遍历，防止“能力迟到才发现缺失”。

---

## 9. trace 系统

*   **单写者**：Player 独占 `trace_file.handle`，外部 subscriber(monitor) 通过 `trace_event(tag, details)` 在同一时间轴上插入 `MON` 行，不允许第二个组件 `$fdisplay` 同一文件。
*   **打开时机**：`build_phase` 打开（不是首次 `play()`），这样 reset 期间的 observer MON 行不会丢失（`:65`）。
*   **行格式**（由 2026-11-07 冻结格式约定）：
    *   三列：`<time(fs)>\t<agent_EVENT>\t<key=val ...>`
    *   `env.START` / `env.END` / `SECONDARY_FAILURE` 由 Player 自己写
    *   `norm_tag()` 把外部 subscriber 的 tag family 拆成菱形：
        *   `disp:disp_obs.m:disp_K`、`m:TMU_K`、`tmu_tmu_obs.m:TMU_K = tmu.m_K`、`xbar: ... > xbar.M_K`、`axi1lane:AXI_K = axi1lane.K`、
        *   `glsu_local` = `glsu.axi.K`、`mem::mem<WRITE|INIT|SCRUB|READ>`、
        *   `f:...`（不识别）、`[warn]` 仍不 drop 掉 `context` / `cmd.K` / `event = cmd.K`
*   **未映射字段剥离**：`fan_util` 不接收；`normalize_tag()` 失败（`fail()`）写 `SECONDARY_FAILURE` 行；**之前所有 pre-lane 最高事件写到同一文件**，player pkg 不依赖 env pkg，反向契约需在 `npu_player_trace_hook.svh`。
*   **结果落盘**：`save_result()` 在 `play()` 出口写一行 JSON：
    `{"status":"<NAME>", "completed_actions":N, "error":"<str>"}`（`:843`）。
    `final_phase()` 再做一次 UVM 报错即 `NP_EXEC_ERROR` 的兜底（`:861`），防止早 PASS 掩盖后续 UVM_ERROR/FATAL。

---

## 10. 与测试/env 的集成面

*   `npu_top_playback_vir_seq`：`player == null` -> `UVM_FATAL`；`preflight()` 失败 -> `UVM_FATAL`；`play()` 返回后若 `status != NP_SUCCESS` -> `UVM_ERROR`。
*   它**不**持有任何 agent sequencer 的引用——所有 agent 装配在 env。
*   env 职责（`npu_top_player_env.build.svh`、`npu_top_player_env.members.svh`）：
    *   创建 `npu_player_cfg / npu_player_runtime_config_db` 注入 Player；
    *   创建 `clock_adapter`，把 `clock_service` 放进 runtime；
    *   启动 `monitor`，向 `runtime.events` `declare_producer`；
    *   创建 `agent`，在 `connect_phase` 用 `bind_sequence`（per op）；
    *   注入共享 `npu_memory_model` / `npu_memory_owner`（可选）；
    *   把 `npu_player_trace_hook` 的 facade 实现递给 Player（可选）。
*   `npu_top_peer_smoke_test` 的三件套就是 `tests/peer/peer_smoke_bundle/commands.tsv` 单流一样，**唯一进入点**：Player 中流执行。
*   装配方式刻意覆盖 Player 的三路分流：
    *   `csr_write/csr_read`（外部 op + sequence 绑定）：`npu_cmd_tb_player.connect_csr` 用 `bind_sequence` 挂到 `csr_agent.sequencer`（`npu_cmd_tb_player.svh:22-28`）。
    *   `AXI-Lite 写穿` DUT（peer bundle 用它并 `noc_slave_cfg@0x2E0` 使能 NIU slave 入口）；
    *   `peer_cfg`（direct 子类扩展）：`npu_top_peer_player` 覆写 `validate_direct/execute_direct`（`env/player/npu_top_peer_player.svh:84/115`）。
    *   `preflight` 校验 `inst` 白名单（`peer_inst_kind`）与 `rs1val/rs2val` ≤48bit；
    *   `execute` 时组装 `npu_core_cmd_frame {t{kind, tag, rs1_val, rs2_val}`，先按 `context B` 用 `include/npu_hm057_noc_isa.svh` 的 `enc74` 打印 74-bit 等效 16 进制（ISA ENC 码，编码不落盘——encoder 是唯一常量源，bundle 内只存语义常量），再 `blocking_frontend_inst.put(frame)`；同步 `put` 的返回值即 `decode 完成`，点表后行与真实 `cfg.excep/load/end_fence` 链对齐；`decode` 则 `tail` 计数双重确认 `receipt` 翻 `NP_EXEC_ERROR`（peer decode_error）成功 `phase=peer_exec_done`。
    *   `test run phase`：负责新放前面 tag，先经 `peer_env.vseqr.peer_corel.mem_backdoor_write` 把 `PUSH_T` 源数据写入 peer SPAD 窗口（IR `mem_init{path=backdoor}` 的 peer 侧投影），再 `env.play()`。

---

## 11. 设计取舍与已知边界

1.  **`sequence` 而非 `sequencer` 是绑定单位**：`bind_sequence` 同时收 `sequencer` 和 `sequence_type, factory 创建`。这让 Player 不需要管 agent 的 `item 类型`（item 由 `sequence` 内部 `new`），兼容任何 agent。
2.  **Player 不信任 agent 自报完成**：用 `phase=="cmd accept" && handle!="" && epoch` 三件套后置复查，而不是看 `sequence` 返回的 `status`。
3.  **`preflight` 的 read-only 是契约不是机制**：如果某个 `sequence` 在 `validate()` 里发 `item` 或改 `model/capability-before-submission`，会被悄悄破坏，代码评审时需把这条作为硬性约定核对。
4.  **`tick()` 不保证相位是** 的**：失败第一次是在 `realtime` 不前进时才发现，之前可能已推送一段 `cfg.run_timeout`。
5.  **`watchdog` 只买 `cycle-scoped`**，其它 scope 换掉 `NP_INPUT_ERROR`。这是当前能力边界，不是缺陷；以后引入新 scope 要在 `preflight` 与 `cycle_watchdogs` 同步扩展。
6.  **跨 Player 的资源仲裁由 `env` 负责**：两个 Player 同时挂同一 `memory model` 不会报（Player 自检发现：`env` 必须只创建/装配一次）。
7.  **`trace` 文件路径冲突**：同 `case` 多次 `play()`（不同 Player 实例）指向同一 `cfg.trace_file` 时，后者会**覆盖**前者；回归脚本应保证一 `case` 一 `player`。

---

## 12. 文件级索引

| 关注点 | 函数 / 成员 | 位置 |
| :--- | :--- | :--- |
| 配置 | `npu_player_cfg` | `npu_player_runtime.svh:103` |
| 状态码 | `npu_player_status` | `npu_player_runtime.svh:4` |
| `Receipt / Observation / Clock / EventBus / Runtime` | 两者 class | `npu_player_runtime.svh` |
| `trace facade` 契约 | `npu_player_trace_hook` | `npu_player_trace_hook.svh` |
| 核心协调器 | `npu_tb_player` | `npu_tb_player.svh` |
| 入口 | `npu_top_playback_vir_seq` | `npu_top_playback_vir_seq.svh` |
| 工艺实例 (CMD+CSR) | `npu_cmd_tb_player` | `seq_lib/cmd/npu_cmd_tb_player.svh:4` |
| CSR 绑定 | `connect_csr()`（bind_sequence x2） | `seq_lib/cmd/npu_cmd_tb_player.svh:22-28` |
| peer 工艺实例 (direct 扩展) | `npu_top_peer_player` | `env/player/npu_top_peer_player.svh:25` |
| peer cfg 校验 / 执行 | `validate_direct() / execute_direct()` | `env/player/npu_top_peer_player.svh:84 / :115` |
| 74-bit 常量源 (contract B) | `npu_hm057_noc_isa` | `include/npu_hm057_noc_isa.svh` |
| preflight 主循环 | `preflight()` | `npu_tb_player.svh:428` |
| 运行主循环 | `run_actions()` | `npu_tb_player.svh:723` |
| 关闭两阶段 | `finish_targets()` | `npu_tb_player.svh:685` |
| 看门狗钩子 | `cycle_watchdogs()` | `npu_tb_player.svh:788` |
| trace 折叠 | `norm_tag() / trace_event()` | `npu_tb_player.svh:325 / :231` |
| 结果落盘 | `save_result() / final_phase()` | `npu_tb_player.svh:843 / :861` |
