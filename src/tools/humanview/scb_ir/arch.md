# Scoreboard 分解通用方法学视图

> 定位：从“功能契约/路径”出发，系统推导出 Scoreboard 检查项集合的通用方法。解决“SCB 凭经验写、只比对返回数据、资源账本和统计计数没人管、写完不知道全不全、写了但从未执行”的问题。与《SVA 分解通用方法学视图》配套使用：**SVA 管跨周期时序/协议/不变量，SCB 管“值对不对、账本平不平、统计准不准、残留有没有”。**

---

## 1. 核心思想

Scoreboard 分解不是“收到返回就比对一下数据”，而是**按比对对象和参考模型做正交分解**：

```
契约来源（5 类可比对契约）
   ├─ 数据正确性
   ├─ 顺序/匹配正确性
   ├─ 资源账本
   ├─ 统计计数
   ├─ 状态/现场/残留
        ↓ 按 5 类对象 × 5 种参考模型 × 4 个时机 展开
SCB 检查项集合（每项绑定：期望来源 + 实际来源 + 执行计数 + 覆盖格子）
        ↓ 按完整性准则判定
无遗漏契约、无未执行项、无孤立检查、账本平衡、结束无残留
```

**一句话**：每个 SCB 检查项都必须能回答“我从哪条契约来、比什么对象、期望值从哪来、在什么时机比、执行过几次、绑定哪个格子”。六个问题答不全的就是孤立检查项。

---

## 2. 分解的输入源：五类可比对契约

SCB 不处理“valid/ready 握手是否守约”这类纯时序契约（那是 SVA 的职责），只处理**有期望值、可比对**的契约：

| 契约来源 | 典型内容 | 期望值来源 | 例（CMD_SCH） |
|---|---|---|---|
| **C1 数据正确性契约** | 读回/写回/返回值与期望一致 | golden model / 预置数据 | `rd_lmem` 读回 SPAD 数据；RMW 写回值 |
| **C2 顺序/匹配契约** | tag/ID 匹配、依赖顺序、乱序不串包 | 事务记录 + 按 tag 匹配 | 多 xd=1 乱序返回按 tag 比对 |
| **C3 资源账本契约** | 占用/释放/在飞账本平衡、不泄漏不超限 | 影子账本 / 预测器 | SPAD tile、CIMC page、DRAM、MST slot |
| **C4 统计计数契约** | 寄存器计数与 monitor 统计一致 | monitor 累加器 | 并行度、各 MST 拥塞数、debug 计数 |
| **C5 状态/残留契约** | 现场保存正确、结束时队列/账本无残留 | 影子寄存器 / 预测器 | 中断现场保存；仿真结束 ISTB/队列为空 |

**分解第一步**：把 CDD/接口/资源规格/统计定义/中断规格里的可比对契约编号（C1-01、C3-04…），后续每个 SCB 必须回指契约编号。

---

## 3. 分解的五个正交维度

同一条契约可以从五个维度切出不同检查项，避免遗漏也避免重复：

| 维度 | 取值 | 切出什么 |
|---|---|---|
| **对象** | 数据 / 顺序 / 资源 / 计数 / 状态 | 比什么：字段值 vs 匹配关系 vs 账本 vs 计数 vs 现场 |
| **参考模型** | golden model / 事务记录匹配 / 影子寄存器 / 预测器 / monitor 累加器 | 期望值从哪来 |
| **时机** | 事务完成时 / 反压期间 / 排空时 / 周期采样 / 仿真结束 | 什么时候比 |
| **方式** | 等值 / 集合 / 顺序 / 不变量 / 账本平衡 / 残留检查 | 怎么比 |
| **粒度** | 字段级 / 事务级 / 资源级 / 统计级 | 比的颗粒度 |

**分解第二步**：每条契约按五维展开，问“比什么对象？期望值从哪来？什么时候比？用等值还是账本平衡？字段级还是事务级？”答完得到该契约的 SCB 候选集。

---

## 4. 五类 SCB 视角与检查项模板

把五维展开后的候选归入五类，每类有固定的“问题 → 模式 → 期望来源 → 模板”：

| 类 | 回答的问题 | 期望来源 | 检查方式 | 必须记录 |
|---|---|---|---|---|
| **SB1 数据比对** | 值是否与期望一致 | golden model / 预置数据 | 等值比对 | expected、actual、mismatch 计数 |
| **SB2 顺序/匹配** | 事务是否匹配正确、顺序是否符合契约 | 事务记录 + tag/ID 匹配 | 按 key 匹配、顺序序列比对 | pending 表、匹配/未匹配计数 |
| **SB3 资源账本** | 占用/释放是否平衡、是否超限/泄漏 | 影子账本 / 预测器 | 账本平衡、上限、互斥 | alloc/release/outstanding、峰值 |
| **SB4 统计计数** | 寄存器计数是否与 monitor 统计一致 | monitor 累加器 | 周期/结束时比对 | 期望计数、实际计数、偏差 |
| **SB5 状态/残留** | 现场是否正确、结束是否无残留 | 影子寄存器 / 预测器 | 状态比对、排空检查 | 现场快照、pending 表、残留计数 |

### 4.1 SB1 数据比对模板

```systemverilog
// SB_RD_LMEM_DATA
// class: SB1 数据 | model: golden | timing: 事务完成 | granularity: 事务级
// bound: RSP×P_OOO_RSP, Feat-4
task check_rd_lmem(rsp_item rsp);
  sb_execute_count++;
  exp_t exp = mem_model.read(rsp.addr);          // 期望来源：golden model
  if (rsp.data !== exp) begin
    sb_fail_count++;
    `uvm_error("SB_DATA", $sformatf("addr=%0h exp=%0h act=%0h", rsp.addr, exp, rsp.data))
  end else sb_pass_count++;
endtask
```

**要求**：每次比对维护 `execute_count/pass_count/fail_count`；期望值来源必须显式（golden model / 预置表 / 上游事务），不能“拿 DUT 输出自己比自己”。

### 4.2 SB2 顺序/匹配模板

```systemverilog
// SB_TAG_MATCH
// class: SB2 顺序 | model: 事务记录匹配 | timing: 事务完成 | granularity: 事务级
// bound: RSP×P_OOO_RSP, Feat-20
task check_tag_match(rsp_item rsp);
  sb_execute_count++;
  if (!tag_pending.exists(rsp.tag)) begin
    sb_fail_count++; `uvm_error("SB_TAG", $sformatf("unexpected tag %0d", rsp.tag))
  end else if (tag_pending[rsp.tag].data !== rsp.data) begin
    sb_fail_count++; `uvm_error("SB_DATA", "tag matched but data mismatch")
  end else begin
    sb_pass_count++; tag_pending.delete(rsp.tag);
  end
endtask
```

**要求**：pending 表必须维护“已下发未返回”集合；返回时按 key 匹配，匹配不上是错、重复返回是错；结束时 pending 表必须为空（与 SB5 残留检查联动）。

### 4.3 SB3 资源账本模板

```systemverilog
// SB_TILE_OCC
// class: SB3 资源 | model: 影子账本 | timing: 周期采样 + 排空 | granularity: 资源级
// bound: MEM×P_EARLY_RLS, Feat-22
class tile_ledger;
  int unsigned alloc_cnt, release_cnt, outstanding;
  bit [31:0] occ_bitmap;   // 8 SPAD × 4 tile
  int unsigned peak;

  function void on_alloc(int tile_id);
    if (occ_bitmap[tile_id]) begin
      sb_fail_count++; `uvm_error("SB_TILE", $sformatf("double alloc tile %0d", tile_id))
    end
    occ_bitmap[tile_id] = 1; alloc_cnt++; outstanding++;
    peak = (outstanding > peak) ? outstanding : peak;
  endfunction

  function void on_release(int tile_id);
    if (!occ_bitmap[tile_id]) begin
      sb_fail_count++; `uvm_error("SB_TILE", $sformatf("release unalloc tile %0d", tile_id))
    end
    occ_bitmap[tile_id] = 0; release_cnt++; outstanding--;
  endfunction

  function void check_balance();
    sb_execute_count++;
    if (outstanding != 0) begin
      sb_fail_count++; `uvm_error("SB_TILE", $sformatf("leak: outstanding=%0d", outstanding))
    end else sb_pass_count++;
  endfunction
endclass
```

**要求**：账本必须检查四件事——**不重复占用、不释放未占用、上限不越界、结束时归零**。只比对 outstanding 总数不够，要检查具体资源 ID 的 bitmap。

### 4.4 SB4 统计计数模板

```systemverilog
// SB_PERF_CNT
// class: SB4 计数 | model: monitor 累加器 | timing: 结束/窗口关闭 | granularity: 统计级
// bound: PERF×P_PARALLEL, Feat-36
task check_perf_cnt();
  sb_execute_count++;
  foreach (perf_reg[i]) begin
    if (perf_reg[i] !== mon_acc[i]) begin
      sb_fail_count++;
      `uvm_error("SB_PERF", $sformatf("reg[%0d] exp=%0d act=%0d", i, mon_acc[i], perf_reg[i]))
    end
  end
  sb_pass_count++;
endtask
```

**要求**：期望值来自 **monitor 独立累加器**，不能从 DUT 寄存器读回来再比（那是自己比自己）；比对时机在性能窗口关闭或仿真结束时。

### 4.5 SB5 状态/残留模板

```systemverilog
// SB_RESIDUAL
// class: SB5 状态 | model: 预测器 | timing: 仿真结束 | granularity: 事务级
// bound: 全局, Feat-19/28
function void check_final_state();
  sb_execute_count++;
  if (istb_pending.size() != 0) begin
    sb_fail_count++; `uvm_error("SB_RES", $sformatf("ISTB residual %0d", istb_pending.size()))
  end
  if (tag_pending.size() != 0) begin
    sb_fail_count++; `uvm_error("SB_RES", $sformatf("tag residual %0d", tag_pending.size()))
  end
  if (int_info_snapshot.first_int_saved !== 1) begin
    sb_fail_count++; `uvm_error("SB_RES", "first int info not saved")
  end
  sb_pass_count++;
endfunction
```

**要求**：仿真结束时必须检查**所有 pending 表、所有账本、所有现场快照**，残留即 fail。

---

## 5. 分解流程：六步漏斗

```
Step 1 契约提取
  从 CDD/数据通路/资源规格/统计定义/中断规格提取可比对契约，编号 C1-xx ~ C5-xx
        ↓
Step 2 五维展开
  每条契约按 对象×参考模型×时机×方式×粒度 展开成候选清单
        ↓
Step 3 归类套模板
  候选归入 SB1~SB5，选参考模型，写检查任务/类
        ↓
Step 4 期望来源 + 执行计数
  明确期望值来源，每个检查项维护 execute_count/pass/fail
        ↓
Step 5 绑定矩阵
  每个检查项绑定 格子/路径/Feat，写进 checker 矩阵
        ↓
Step 6 完整性检查
  用检查表判定：无遗漏契约、无未执行项、无孤立检查、账本平衡、结束无残留
```

**关键在 Step 4**：期望来源必须独立于被测路径（golden model / 预置表 / 上游事务 / monitor 累加器）；检查项必须有 `execute_count`，写了但从未执行等于没写。

---

## 6. 分解树视图（以一条路径为例）

以 `P_OOO_RSP`（多 xd=1 乱序返回）为例：

```
P_OOO_RSP 路径
├─ C1 数据契约
│   ├─ SB1: 每条 rd_lmem 返回数据 == golden model        → SB_RD_LMEM_DATA
│   └─ SB1: 每条 V_S 返回标量 == VPU 预置值              → SB_VS_DATA
├─ C2 顺序/匹配契约
│   ├─ SB2: 返回 tag 在 pending 表中                     → SB_TAG_MATCH
│   ├─ SB2: 同一 tag 不重复返回                          → SB_TAG_NO_DUP
│   └─ SB2: 乱序返回时 tag/data 同拍保持                  → （SVA 负责，SB 不重复）
├─ C3 资源契约
│   └─ SB3: xd=1 指令在飞计数 == pending 表大小           → SB_XD_LEDGER
├─ C4 计数契约
│   ├─ SB4: 返回条数 == 下发 xd=1 条数                    → SB_RSP_CNT
│   └─ SB4: debug2 发射数 == monitor 发射计数             → SB_DBG2_CNT
├─ C5 状态/残留契约
│   ├─ SB5: 结束时 tag_pending 为空                       → SB_TAG_RESIDUAL
│   └─ SB5: rsp_fifo 各级 fifo 为空                       → SB_FIFO_RESIDUAL
└─ 配置契约
    └─ SB5: 中断现场首次保存后不被覆盖                     → SB_INT_INFO
```

每条叶子绑定到 `RSP×P_OOO_RSP` 等格子。

---

## 7. SCB 与 SVA 的分工边界

分解时必须明确“这条契约归 SVA 还是归 SCB”，避免重复或遗漏：

| 契约性质 | 归 SVA | 归 SCB | 说明 |
|---|---|---|---|
| valid/ready 握手保持 | ✓ | — | 跨周期时序 |
| 反压时数据/tag 稳定 | ✓ | — | 跨周期时序 |
| start/done/rls 顺序与 ID 匹配 | ✓ | — | 跨周期时序 |
| 返回数据值是否正确 | — | ✓ | 有期望值 |
| tag 是否匹配、是否重复返回 | — | ✓ | 事务匹配 |
| 资源不超上限、不互斥 | ✓ | ✓ | SVA 卡不变量，SB 卡账本值 |
| 资源占用/释放账本平衡 | — | ✓ | 账本 |
| 统计寄存器计数 | — | ✓ | 计数 |
| 仿真结束无残留 | — | ✓ | 排空检查 |
| 中断现场保存正确 | — | ✓ | 状态比对 |

**重叠区处理原则**：资源上限类契约，SVA 卡“永远不超过上限”，SB 卡“每次占用/释放后账本值与 bitmap 正确”。两者职责不同，不算重复。

---

## 8. 分解完整性判定

分解完不能靠“感觉够了”，用六个度量判定：

| 度量 | 定义 | 目标 |
|---|---|---|
| **契约覆盖率** | 有 ≥1 个 SCB 的可比对契约数 / 可比对契约总数 | 100% |
| **格子绑定率** | 有 ≥1 个 SCB 的适用格子数 / 适用格子数 | 100% |
| **执行率** | execute_count > 0 的检查项数 / 检查项总数 | 100% |
| **五类覆盖度** | SB1~SB5 每类至少有检查项且被执行（按契约需要） | 适用类 100% |
| **重复度** | 语义等价的 SCB 数 / SCB 总数 | 0 |
| **账本平衡率** | 结束时 outstanding == 0 且无残留的账本数 / 账本总数 | 100% |

**判定规则**：
- 契约覆盖 < 100% → 有契约没检查项，分解漏了；
- 格子绑定 < 100% → 有格子没 checker，证据链不完整；
- 执行率 < 100% → 有检查项从未执行，等于没写；
- 五类覆盖度不足 → 只比了数据没比资源/计数/残留；
- 重复度 > 0 → 两条检查项检查同一件事，合并或删一条；
- 账本不平衡 → 资源泄漏或重复释放，要么是 DUT bug，要么是账本没建对。

---

## 9. SCB 属性模板（分解输出必须带全）

每个检查项分解出来后，必须填全这张属性卡：

```yaml
scb_id: SB_TAG_MATCH
name: 乱序返回 tag 匹配
contract: C2-01                    # 回指契约编号
class: SB2 顺序/匹配                # SB1~SB5 之一
object: 顺序                       # 数据/顺序/资源/计数/状态
model: transaction                 # golden/transaction/shadow/predictor/accumulator
timing: 事务完成                   # 事务完成/反压/排空/周期/结束
method: 按 key 匹配                # 等值/集合/顺序/不变量/账本平衡/残留
granularity: 事务级                # 字段/事务/资源/统计
check_object: rsp.tag / rsp.data
expected_source: tag_pending 表    # 期望值来源，必须独立
actual_source: rsp_item
execute_count: 856
pass_count: 856
fail_count: 0
bound_cells: [RSP×P_OOO_RSP]
bound_paths: [P_OOO_RSP]
bound_feats: [Feat-20]
severity: error
status: 未执行 | 已执行通过 | 已执行失败
```

**完整性要求**：`contract / class / model / expected_source / execute_count / bound_cells` 六项缺一不可。

---

## 10. 示例：CMD_SCH 的 SCB 分解片段

| SCB ID | 契约 | 类 | 参考模型 | 时机 | 检查对象 | 绑定格子 |
|---|---|---|---|---|---|---|
| SB_RD_LMEM_DATA | C1-01 | SB1 数据 | golden model | 事务完成 | `rsp.data` vs SPAD 模型 | RSP×P_OOO_RSP |
| SB_WR_LMEM_RMW | C1-03 | SB1 数据 | golden model | 事务完成 | 先读后写回值 | RSP×P_RMW |
| SB_TAG_MATCH | C2-01 | SB2 顺序 | 事务记录匹配 | 事务完成 | tag 在 pending、data 匹配 | RSP×P_OOO_RSP |
| SB_HAZARD_ORDER | C2-04 | SB2 顺序 | 预测器 | 事务完成 | 依赖顺序 | DEP×P_STORED_ISSUED |
| SB_TILE_OCC | C3-01 | SB3 资源 | 影子账本 | 周期 + 排空 | tile bitmap、outstanding | MEM×P_EARLY_RLS |
| SB_SLOT_OCC | C3-04 | SB3 资源 | 影子账本 | 周期 + 排空 | MST slot 占用 | UNIT×P_PARALLEL |
| SB_PARAL_CNT | C4-01 | SB4 计数 | monitor 累加器 | 窗口关闭 | `perf_paral` 寄存器 | PERF×P_PARALLEL |
| SB_DBG2_CNT | C4-05 | SB4 计数 | monitor 累加器 | 仿真结束 | `debug2` 发射计数 | PERF×全局 |
| SB_INT_INFO | C5-02 | SB5 状态 | 影子寄存器 | 中断发生时 | 现场首次保存 | EXCP×P_ILLEGAL_BLOCK |
| SB_RESIDUAL | C5-05 | SB5 残留 | 预测器 | 仿真结束 | pending 表/账本全空 | 全局 |

每个检查项维护 `execute_count/pass/fail`，进入 checker 矩阵的“执行次数”列。

---

## 11. 评审检查表

- [ ] 每个 SCB 是否回指契约编号（C1~C5-xx）？
- [ ] 每个可比对契约是否至少一个 SCB？（契约覆盖 100%）
- [ ] 是否按五维展开过（对象/参考模型/时机/方式/粒度）？
- [ ] 是否只比了数据漏了资源账本、统计计数、残留检查？
- [ ] 每个 SCB 是否选对参考模型，期望来源是否独立于被测路径？
- [ ] 每个 SCB 是否维护 `execute_count/pass/fail`？
- [ ] 是否存在从未执行的检查项？
- [ ] 每个 SCB 是否绑定格子/路径/Feat？
- [ ] 是否存在语义重复的 SCB？与 SVA 是否职责清晰、不重复不遗漏？
- [ ] 资源账本是否检查“不重复占用、不释放未占用、不超限、结束归零”四件事？
- [ ] 统计计数期望是否来自 monitor 独立累加器，而非读回 DUT 寄存器？
- [ ] 仿真结束是否检查所有 pending 表、账本、现场快照无残留？
- [ ] 是否存在“拿 DUT 输出自己比自己”的伪比对？

---

## 12. 一句话总结

**SCB 分解的通用方法学 = 五类可比对契约输入 × 五维正交展开（对象/参考模型/时机/方式/粒度）× 五类检查项模板（数据/顺序/资源/计数/状态）× 六步漏斗 × 六项完整性度量。** 每个 SCB 必须能回答“从哪条契约来、比什么对象、期望值从哪来、什么时机比、执行过几次、绑定哪个格子”；期望来源必须独立，写了必须执行，结束时账本必须平、残留必须空。分解的终点不是“写了一堆比对”，而是“契约覆盖 100%、格子绑定 100%、执行率 100%、五类覆盖、零重复、账本平衡、结束无残留”。