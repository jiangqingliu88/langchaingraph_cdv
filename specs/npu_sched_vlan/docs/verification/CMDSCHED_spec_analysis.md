# CMD_SCH 架构 Spec 分析

| 项 | 内容 |
|---|---|
| 来源 | `docs/specs/cmdsched.md`（CMD Scheduler Arch Spec） |
| 对象 | HM057 NPU_V2 CMD_SCH |
| 分析目的 | 把架构 spec 转成可执行的验证 feature 树、专题、测试点和契约候选 |
| 关联产物 | `CMDSCHED_features.csv`、`CMDSCHED_topics.csv`、`CMDSCHED_testpoints.csv`、`CMDSCHED_contracts.csv`、`CMDSCHED_matrix.md` |
| 状态 | **目标计划（target plan）**；测试点均为 `planned`，尚未接入真实执行证据 |

## 1. 变更需求（Spec 1.3）

| # | 需求 | 验证关注点 |
|---|---|---|
| 1 | 删除 CPU 读 CSR 的 rd_csr 指令；cfg 信息写入 core_reg | 非法编码、core_reg 读回、寄存器默认值 |
| 2 | 删除 CIMC 1x4，仅支持 2x2 | 形状编码/非法形状、CIMC page 资源 |
| 3 | 删除 creg_cmd_icg_en[5:0] 的分组件低功耗控制 | 各 master 自控；CMD 侧仅保留全局 ICG 相关配置 |
| 4 | 删除多组件访问同一 SPAD 的阻塞条件 | 由 xbar 做读写仲裁；CMD 只保证无 RAW/WAW/WAR 依赖 |
| 5 | 增加指令 ost=2 | master ins_fifo 深度 2；满时反压 cmd 分发 |
| 6 | 同组件两条 drv 指令无 SHazard 时不被阻塞；第三条阻塞 | SHazard/依赖边界；NIU 不能同时两条 store |
| 7 | 增加乱序发射 | 跳过阻塞 master，检查后续无 hazard 指令；窗口为 ins_buffer/ISTB_DP |
| 8 | 增加多 xd=1 指令下发 | 32bit 返回值、按 id/tag 乱序返回、同拍多返回仲裁 |
| 9 | SPAD 按 tile 切分，Tensor 按 tile 占用 | tile 数为 2 的幂、范围/冲突/释放 |
| 10 | GLSU/LLSU 同时调用 TMU | 无 DHazard 时先占先得；同时抢占 GLSU 优先 |
| 11 | cfg 配置信息存储到 core_reg | core_reg 读取一致性、默认值、非法访问 |
| 12 | tile 冲突只按起止地址范围；空洞也视为占用；tile_rls 释放 | 区间冲突、离散 tile、提前/延后释放 |
| 13 | DRAM 冲突按整块 dram | dram 整块占用/释放、跨块冲突 |

## 2. 微架构与数据流

```text
Ins Dispatcher
   │ cmd_vld / cmd_payload / cmd_rdy
   ▼
decode ── 解析 cfg/drv、地址、类型、精度
   │
   ├── scoreboard ── SHazard / DHazard 判断，记录在途指令
   │        │
   │        ├── 无 hazard → dsp_en → dispatch → master
   │        └── 有 hazard → store_en → cfg_buffer / drv_buffer（4 深）
   │
   └── ins_buffer / status0..3：按 id 顺序保存待发指令
                     │
                     └── master done / tile_rls → scoreboard 更新依赖
```

关键深度与反压链：

| 模块 | 深度 | 说明 |
|---|---|---|
| decode buffer | 2 | 指令握手成功后入 buffer |
| cfg/drv buffer | 4 | scoreboard store_en 写入，scoreboard_ren 读出 |
| master ins_fifo | 2 | ost=2；满时反压 cfg/drv buffer |
| 反压链 | master → cfg/drv → decode → Ins Dispatcher | 不允许丢指令 |

指令优先级：新指令最高；ins_buffer 内按 id 先后顺序分发；乱序发射只在 ins_buffer 窗口内跳过阻塞项。

## 3. 接口概览

| 接口组 | 内容 | 验证重点 |
|---|---|---|
| Ins Dispatcher | `disp_cmd_inst`（75bit：xd/xs1/xs2/func7/rs1val/rs2val）、`inst_flag`、`cmd_disp_rdy`、`disp_cmd_rsp_data`（32+3）、`inst_tag`（3bit） | 握手、payload 稳定、tag/返回值配对 |
| SPAD xbar | 1 读 + 1 写；512bit 数据；18bit 本地地址/44bit 读地址；2bit wstrb；DV 用 ID | 读写通道、地址范围、wstrb、响应 ID |
| NIU | start/done、rtile/wtile/page 释放、cfg 类型/位宽/维度/stride | load/store、tile/page 释放、配置传递 |
| GLSU | start/done、rtile/wtile/page/dram 释放、task_select（tld/ttld/gather/loadcimcexp/tensor dma/tst/storecimcexp） | task 编码、地址、gather、TMU |
| LLSU | start/done、rtile/wtile/page 释放、task_select（bc/vbc/trans_vbc/setCIMExp/getCIMExp/mov/trans） | 任务编码、stride、标量广播 |
| VPU | start/done、3 读 + 1 写通道释放、功能选择、精度/round/饱和/多项式配置 | 功能/精度编码、通道释放 |
| MPU | start/done、page/rtile/wtile 释放、base_addr、精度/累加/反量化配置 | CIMC 2x2、page/tile、精度 |
| 中断 | `creg_cmd_excep_en`、masked ints、`cmd_creg_int`、`cmd_creg_exce*` | 非法指令/地址、现场保存、清除恢复 |
| Debug/Perf | `cmd_creg_dbg0/1/2`、perf_en/start/pause/conti/end、`cmd_creg_perf_cnt`（96bit） | 计数器一致性、窗口统计 |
| CSR/LP | `creg_cmd_icg_en`、`creg_cmd_tile_rls_en`、`creg_cmd_spad_excl_en`、reserve | 默认值、ICG、tile 释放、独占 |

## 4. Feature List（Spec 4）

| # | Feature | 验证含义 |
|---|---|---|
| 1 | 各功能组件信息配置和启动 | decode/dispatch/start/done 全链路 |
| 2 | 各 master 指令 outstanding=2 | master ins_fifo 深度与反压 |
| 3 | 指令间 sync 同步 | sync 与所有组件 SHazard，阻塞后续 |
| 4 | NIU 指令间同步 | noc_fence 对后续 noc 的 SHazard |
| 5 | CPU 读写 LMEM（SPAD） | 32bit 数据、32bit 地址对齐 |
| 6 | LMEM 与 LLSU 的 SHazard | wr/rd_lmem 与 LLSU 互斥 |
| 7 | GLSU load/store 并行 | 无 DHazard 时并行 |
| 8 | 当前接收指令的 data hazard 阻塞 | 覆盖 master 中与 ins_buffer 中的在途指令 |
| 9 | SPAD tile 切分 | tile 数可配、Tensor 按 tile 占用 |
| 10 | 多组件访问同一 SPAD | 无 RAW/WAW/WAR；xbar 仲裁 |
| 11 | 乱序发射 | 跳过阻塞项，窗口 ins_buffer/ISTB_DP |
| 12 | 多 xd=1 下发 | 乱序返回、同拍多返回仲裁 |
| 13 | GLSU/LLSU TMU 同时下发 | 无 DHazard、先占先得、GLSU 优先 |
| 14 | 删除各组件低功耗控制 | master 自控；CMD 只保留全局 ICG |

## 5. 约束（Spec 5、7）

- 指令组合、数据精度组合必须与 ISA 对齐。
- fence/sync 负责收集完成状态，并阻塞向下分发。
- ctrl：lmem 地址 32bit 对齐；rs1val 高 16bit 无影响；xd=1 的 rs1val 最多 1bit 非 0。
- noc：noc_dst/noc_src 必须配对；仅同 cluster 1 对 1；跨 cluster 不支持（待确认）。
- tld_tst：仅在 CIMC 地址下 cfg_exp_mode 有效；gather 类指令必须配 index 基地址/维度。
- tmu：bc 无 dim1/dim2 时使用输出配置。
- mpu/vpu：数据精度、op_mode、寄存器组合必须在有效范围。

## 6. 低功耗与复位（Spec 6）

- ICG 在“接收指令原语开始”时打开；在“指令 fifo 为空 && 所有 master 已 done”时关闭。
- cmd_int_perf 在中断/性能监控开启时打开。
- 各组件低功耗由 master 自己控制；CMD 不再分组件控制。
- 复位后 CSR 默认值、FIFO 空、计数器 0 需要断言/检查。

## 7. 异常与错误（Spec 8）

| 错误类型 | 触发条件 | 检测/上报 | 优先级 |
|---|---|---|---|
| 指令错误 | 配置/编码与 ISA 不匹配；lmem 目的地址非 SPAD | 译码逻辑/中断检查，core_reg 读取 | P0 |
| 协议错误 | 总线握手失败、非法响应、跨 SPAD 块访问 | 协议检查器/边界检测，错误中断 | P0 |
| 超时 | 执行超过看门狗；DMA 无响应 | WDT，致命中断 | P1 |
| 系统/硬件异常 | ECC/电压/时钟异常 | 监控单元，系统级复位 | P1 |

## 8. 性能与签核口径（Spec 9、10）

| 指标 | 口径 | 目标 |
|---|---|---|
| 典型分发吞吐 | 指令数 / 周期数；无 DHazard、小指令、轮询 master | 1 指令/cycle |
| 并行度 | 每周期同时执行的功能部件数，性能窗口累加 | 与 monitor/模型一致 |
| 拥塞 | 各功能部件在 ins_buffer 的数量、fifo 满占比 | 与 debug 计数一致 |
| 代码覆盖率 | statement / branch / condition / toggle | 100% |
| 功能覆盖率 | 基于 Feature List 的 covergroup | >95%，未覆盖逐条评审/豁免 |
| 断言覆盖率 | 所有植入断言至少触发一次 | 100% |
| 回归 | 全量回归通过率 | 100% |

## 9. 待决问题与风险

- NIU AXI ID function 待确认（Spec 1.3 备注）。
- 跨 cluster noc 指令不支持，需要确认。
- Spec 10.1 中 cfg/drv/pre 指令原语计数器有 TODO/负责人标记。
- Spec 11 待决问题表为空，需在评审中补齐决策人/截止时间。
- 低功耗/电源域/功耗估算在 Spec 6 只有框架，验证范围需与架构确认。
- 代码覆盖率 100% 与功能覆盖率 >95% 的签核口径需要在项目层面固化。

## 10. 对验证拆分的直接影响

- 黑盒 feature 树必须体现**路径 / 资源 / 并行 / 竞争 / 时序**，不能只按 RTL 模块分。
- 重点专题：SHazard/DHazard、地址范围冲突、tile/page/dram 资源、OST=2、乱序发射、xd=1 乱序返回、TMU 竞争、中断现场、ICG/复位。
- 大量行为依赖 scoreboard 的“在途指令表”，SCB 参考模型必须独立实现依赖/资源/优先级，不能复用 DUT 内部逻辑。
- 先落一个样板 case（建议 `TC_CMDSCHED_RSP_001`），把 VCS/UVM/urg/gate 全链路跑通，再扩到 10 批次。
