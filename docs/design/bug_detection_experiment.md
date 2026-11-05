# 缺陷检出实验 —— 往 npu_sched 注入 3 个 corner bug，看流程拦不拦得住

> 日期：2026-11-04 · run：`output_e2e_bug1_jiang_20261104_231358`
> 目的：验证"签核前的缺陷检出"不是口头承诺。同一份 casemodel / 回归 / 判据，
> 只改 RTL，看流程在哪一级停下、证据指向哪条规则、耗时多少。

## 1. 注入的缺陷（`specs/npu_sched_bug/npu_sched.sv`）

| # | 位置 | 改动 | 期望被谁抓到 |
|---|---|---|---|
| BUG-A | 发射决策 | 屏障命中分支改为恒假（`if (1'b0) → FLUSHED`） | 断言 `barrier_flushes` + DUT 检查组逐拍规则 |
| BUG-B | 发射决策 | RAW 真依赖分支改为恒假（`if (1'b0) → STALLED`） | 断言 `raw_never_issues` / `issued_needs_no_blocker` |
| BUG-C | 队列满判定 | `full` 阈值从 32 改为 63（"永不满"） | `queue_level_within_depth`（本轮**未触发**：种子没有把队列压到 33+） |

注入仅改 `specs/npu_sched_bug/npu_sched.sv`；casemodel / 回归 / 策略一行未动。

## 2. 结果

```text
loopback   4/4   PASS     ← 环境自检仍然过（缺陷不在环境，在 DUT 行为）
p0        38/52  FAIL  ← 分级门控在这里停下（14 条失败）
p1..p3    未运行        ← 前一级不过就不进下一级
audit     NEEDS_FIX / REJECTED
```

**证据（`test_npu_sched_D_ADDR_0` 的 `sim_vsim.log`）**：

```text
[DUT_CHK] 规则 barrier_flushes 违规 144 次：屏障命中时必须冲刷（barrier_type!=NONE → issue_decision==FLUSHED）
[DUT_CHK] 规则 issued_needs_no_blocker 违规 121 次：发射的三个前提：队列非空、无屏障、无 RAW 真依赖
[DUT_CHK] [SCB_DUT] total=596 matched=331 mismatched=265 unverified=0
[DUT_CHK] [SCB SB-NPU-DUT] total=596 matched=331 mismatched=265
```

- 失败用例 **14 条**（p0 中真正走到"发射决策"的用例）：`D_ADDR_*` 4 条、
  `case_basic`、`reset`、`dtype` 4 条、`type` 4 条；
- 停级别 **p0**，阻断原因 `p0: failed=14 unknown=0`（unknown 也不放行）；
- 整个 ops（loopback → build → p0 → 拦下）**182 s**；
- 签核 **REJECTED**，签核包只收已产生的 45 份材料（没有假装跑完后半段）。

## 3. 结论与边界

1. **拦得住**：DUT 行为缺陷在 p0 就被断言 + 逐拍规则抓到，且**带规则名与次数**，
   不是"某条用例 fail"这种只能回去翻日志的结论。
2. **归因到规则**：`barrier_flushes` / `issued_needs_no_blocker` 直接指向被改的
   两个分支；`[SCB_DUT]` 与逐条 `[SCB SB-NPU-DUT]` 同一口径（265 mismatch）。
3. **loopback 全过并不代表 DUT 对**：它只证明环境自洽；这正是分级门控要分开的
   两件事。
4. **BUG-C 未触发**说明现有种子没有把队列压到 33+：这是**用例/种子覆盖缺口**，
   不是检出机制失效 —— 它正好回答了"覆盖率 95.2% 之外还差什么"。
5. 本轮参考模型是占位（body 含 TODO，按设计**不接 scoreboard**），所以检出
   来自 SVA + DUT 逐拍规则；参考模型实现后，同一批缺陷还会多一层 expected/actual 比对。

## 4. 复现

```bash
python -m src.cli.commands verify --rtl specs/npu_sched_bug -o output_e2e_bug1 \
  --target 95 --max-rounds 1 --no-manual-gate --approval auto --summary
```

判据：`regression_stages.json` 的 `blocked_at == "p0"`，且失败用例日志里出现
`规则 barrier_flushes 违规` / `mismatched=265`。
