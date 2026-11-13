# SVA 分解通用方法学视图

> 定位：从“功能契约/路径”出发，系统推导出 SVA 断言集合的通用方法。解决“SVA 凭经验一条条写、写多写少没标准、写完不知道全不全”的问题。

---

## 1. 核心思想

SVA 分解不是“想到什么写什么”，而是**按契约来源和性质维度做正交分解**：

```
契约来源（5 类输入）
   ├─ 接口协议
   ├─ 生命周期时序
   ├─ 数据完整性
   ├─ 资源不变量
   ├─ 配置一致性/活性
        ↓ 按 7 类视角分类
SVA 断言集合（每条绑定：触发条件 + 检查条件 + 覆盖格子 + cover property）
        ↓ 按完整性准则判定
无遗漏、无 vacuous、无孤立断言
```

**一句话**：每条 SVA 都必须能回答“我从哪条契约来、检查什么性质、绑定哪个格子、触发过没有”。四个问题答不全的 SVA 就是孤立断言。

---

## 2. 分解的输入源：五类契约

SVA 不是从信号清单出发，是从契约出发。先把模块的契约穷举成五类：

| 契约来源 | 典型内容 | 例（CMD_SCH） |
|---|---|---|
| **C1 接口协议契约** | valid/ready 握手、反压保持、数据稳定 | `cmd_valid && !cmd_ready` 时 payload 保持 |
| **C2 生命周期时序契约** | start/done/rls 顺序、依赖解除后发射、后启动先 done 限制 | `rls_vld` 不晚于 `done_vld` |
| **C3 数据完整性契约** | 反压时数据/tag 保持、按 tag 匹配、RMW 顺序 | `rsp_valid && !rsp_ready` 时 tag/data 稳定 |
| **C4 资源不变量契约** | slot/tile/page/DRAM 上限、互斥、one-hot | NIU 不能同时两条 store；tile 占用 ≤ 32 |
| **C5 配置/活性契约** | CSR 使能与行为联动、请求最终响应、反压最终解除 | `excep_en==0` 时无中断；`req` 最终 `rsp` |

**分解第一步**：把 CDD/接口文档里的每条契约编号（C1-01、C2-03…），后续每条 SVA 必须回指契约编号。

---

## 3. 分解的五个正交维度

同一条契约可以从五个维度切出不同 SVA，避免遗漏也避免重复：

| 维度 | 取值 | 切出什么 |
|---|---|---|
| **层次** | 接口级 / 模块内部 / 端到端 | 同一条契约在不同层次各写一条 |
| **时间** | 单拍 / 多拍窗口 / 最终（liveness） | 不变量 vs 有界响应 vs 最终响应 |
| **性质** | safety（坏事不发生）/ liveness（好事最终发生） | 互斥、one-hot、上限 vs 最终响应、最终解除 |
| **对象** | 控制 / 数据 / 资源 / 状态 | 握手信号 vs payload vs 计数 vs FSM |
| **条件** | 无条件不变量 / 触发蕴含 / 配置使能蕴含 | `always` vs `a \|-> b` vs `en \|-> ...` |

**分解第二步**：每条契约按五维展开，问“这条契约在接口级/模块级/端到端各是什么？是单拍还是多拍？是 safety 还是 liveness？管控制还是数据？是无条件还是有触发条件？”答完就得到该契约的 SVA 候选集。

---

## 4. 七类 SVA 视角与断言模板

把五维展开后的候选，归入七类视角，每类有固定的“问题 → 模式 → 模板”：

| 类 | 回答的问题 | 断言模式 | 模板 | 必须配 cover |
|---|---|---|---|---|
| **S1 协议/握手** | valid/ready 是否守约 | 反压保持 | `(v && !r) \|=> v && $stable(payload)` | 反压发生 |
| **S2 时序关系** | 事件顺序是否正确 | 蕴含 + 窗口 | `a \|-> ##[m:n] b`；`rls \|-> !done \|\| same_cycle` | 触发条件成立 |
| **S3 数据完整性** | 数据在传输中是否保持/匹配 | 稳定 + 匹配 | `(v && !r) \|=> $stable(d) && $stable(tag)` | 反压/乱序发生 |
| **S4 资源不变量** | 资源约束是否永远成立 | 无条件 safety | `always (!(cond1 && cond2))`；`always (cnt <= MAX)` | 接近上限/互斥场景 |
| **S5 安全性（safety）** | 非法状态是否永不出现 | 无条件 safety | `always (!illegal_state)`；one-hot；`!$isunknown(sig)` | 状态机遍历 |
| **S6 活性（liveness）** | 好事是否最终发生 | 有界最终 | `req \|-> ##[1:N] rsp`；`bp \|-> ##[1:N] !bp` | 请求/反压发生 |
| **S7 配置一致性** | CSR 配置是否生效 | 配置蕴含 | `en==0 \|-> ##[1:$] !effect`；`icg==1 \|-> idle 时无时钟` | 配置切换 |

**分解第三步**：每条候选 SVA 归入唯一主类（可有关联类），套模板，写 `property` + `cover property`。

---

## 5. 分解流程：六步漏斗

```
Step 1 契约提取
  从 CDD/接口/FSM/CSR 文档提取契约，编号 C1-xx ~ C5-xx
        ↓
Step 2 五维展开
  每条契约按 层次×时间×性质×对象×条件 展开成候选清单
        ↓
Step 3 归类套模板
  候选归入 S1~S7，套对应断言模板，写 property
        ↓
Step 4 触发条件 + cover
  定义 antecedent，写 cover property 统计触发，防 vacuous
        ↓
Step 5 绑定矩阵
  每条 SVA 绑定 格子/路径/Feat，写进 checker 矩阵
        ↓
Step 6 完整性检查
  用检查表判定：无遗漏契约、无 vacuous、无孤立 SVA、无重复
```

**关键在 Step 4**：没有 `cover property` 的 SVA 等于没写——antecedent 从未满足的 SVA 永远 pass，是 vacuous pass，必须视为未覆盖。

---

## 6. 分解树视图（以一条路径为例）

以 `P_STORED_ISSUED`（存 ISTB 后发射）为例，展示契约 → 类 → 断言的分解树：

```
P_STORED_ISSUED 路径
├─ C1 握手契约
│   ├─ S1: cmd_valid && !cmd_ready |=> payload 稳定      → SVA_CMD_HS_HOLD
│   └─ S1: rsp_valid && !rsp_ready |=> tag/data 稳定     → SVA_RSP_HOLD
├─ C2 时序契约
│   ├─ S2: 依赖未解除 |-> !start_valid                   → SVA_DEP_NO_ISSUE_BEFORE_READY
│   ├─ S2: start |-> ##[1:N] done                        → SVA_START_TO_DONE
│   ├─ S2: start_inst_id == done_inst_id                 → SVA_INST_ID_MATCH
│   └─ S2: rls_vld 不晚于 done_vld                        → SVA_RLS_BEFORE_DONE
├─ C3 数据契约
│   └─ S3: 乱序返回按 tag 匹配                            → SVA_TAG_STABLE
├─ C4 资源契约
│   ├─ S4: slot 占用 ≤ 2                                  → SVA_SLOT_LIMIT
│   └─ S4: 依赖解除前 ISTB 条目不被覆盖                    → SVA_ISTB_NO_OVERWRITE
├─ C5 活性契约
│   └─ S6: 依赖最终解除 |-> ##[1:N] start                 → SVA_DEP_EVENTUAL_ISSUE
└─ 配置契约
    └─ S7: excep_en==0 |-> 无 cmd_int                      → SVA_EXCEP_MASK
```

这棵树就是该路径的 SVA 分解结果，每条叶子绑定到 `DEP×P_STORED_ISSUED` 等格子。

---

## 7. 分解完整性判定

分解完不能靠“感觉够了”，用五个度量判定：

| 度量 | 定义 | 目标 |
|---|---|---|
| **契约覆盖率** | 有 ≥1 条 SVA 的契约数 / 契约总数 | 100% |
| **格子绑定率** | 有 ≥1 条 SVA 的适用格子数 / 适用格子数 | 100% |
| **非 vacuous 率** | antecedent 触发 >0 的 SVA 数 / SVA 总数 | 100% |
| **七类覆盖度** | 七类中每类至少有 SVA 且被触发（按契约需要） | 适用类 100% |
| **重复度** | 语义等价的 SVA 数 / SVA 总数 | 0 |

**判定规则**：
- 契约覆盖 < 100% → 有契约没断言，分解漏了；
- 格子绑定 < 100% → 有格子没 checker，证据链不完整；
- 非 vacuous < 100% → 有 SVA 是 vacuous pass，等于没验证；
- 七类覆盖度不足 → 该契约的性质维度没展开全（比如只写了 safety 没写 liveness）；
- 重复度 > 0 → 两条 SVA 检查同一件事，合并或删一条。

---

## 8. SVA 属性模板（分解输出必须带全）

每条 SVA 分解出来后，必须填全这张属性卡，否则视为未完成：

```yaml
sva_id: SVA_DEP_NO_ISSUE_BEFORE_READY
name: 依赖未解除不发射
contract: C2-03                    # 回指契约编号
class: S2 时序关系                  # 七类之一
level: 模块内部                     # 接口/模块/端到端
time: 多拍窗口                      # 单拍/多拍/最终
nature: safety                      # safety/liveness
object: 控制                        # 控制/数据/资源/状态
condition: 触发蕴含                 # 无条件/触发/配置使能
antecedent: inst_in_istb && !dependency_ready
consequent: !start_valid
property: |
  (inst_in_istb && !dependency_ready) |-> !start_valid
cover_property: |
  (inst_in_istb && !dependency_ready)
bound_cells: [DEP×P_STORED_ISSUED]
bound_paths: [P_STORED_ISSUED]
bound_feats: [Feat-19]
severity: fatal
status: 未触发 | 已触发通过 | 已触发失败
hit_count: <antecedent 触发次数>
```

**完整性要求**：`contract / class / antecedent / consequent / cover_property / bound_cells` 六项缺一不可。

---

## 9. 示例：CMD_SCH 的 SVA 分解片段

| SVA ID | 契约 | 类 | 性质 | Antecedent | Consequent | 绑定格子 |
|---|---|---|---|---|---|---|
| SVA_CMD_HS_HOLD | C1-01 | S1 协议 | safety | `cmd_valid && !cmd_ready` | `cmd_valid && $stable(payload)` | 所有路径×ITYPE |
| SVA_DEP_NO_ISSUE_BEFORE_READY | C2-03 | S2 时序 | safety | `inst_in_istb && !dep_ready` | `!start_valid` | DEP×P_STORED_ISSUED |
| SVA_START_DONE_ID | C2-05 | S2 时序 | safety | `start_valid` | `##[1:N] done && done_id==start_id` | ISSUE×P_DIRECT_FULL 等 |
| SVA_RLS_BEFORE_DONE | C2-07 | S2 时序 | safety | `rls_vld` | `!done_vld \|\| same_cycle` | ISSUE×P_EARLY_RLS |
| SVA_RSP_HOLD | C3-01 | S3 数据 | safety | `rsp_valid && !rsp_ready` | `$stable(data) && $stable(tag)` | RSP×P_OOO_RSP |
| SVA_NIU_NO_DUAL_STORE | C4-02 | S4 资源 | safety | `always` | `!(niu_store0 && niu_store1)` | UNIT×P_PARALLEL |
| SVA_TILE_NO_LEAK | C4-05 | S4 资源 | safety | `always` | `tile_occ ≤ 32 && 释放后归零` | MEM×P_EARLY_RLS |
| SVA_EXCEP_MASK | C5-01 | S7 配置 | safety | `excep_en==0` | `##[1:$] !cmd_int` | CSR×EXCP |
| SVA_DEP_EVENTUAL_ISSUE | C5-03 | S6 活性 | liveness | `dep_ready` | `##[1:N] start_valid` | DEP×P_STORED_ISSUED |

每条都有 `cover_property` 统计 antecedent，进入 checker 矩阵的“触发次数”列。

---

## 10. 评审检查表

- [ ] 每条 SVA 是否回指契约编号（C1~C5-xx）？
- [ ] 每条契约是否至少一条 SVA？（契约覆盖 100%）
- [ ] 每条契约是否按五维展开过（层次/时间/性质/对象/条件）？
- [ ] 是否只写了 safety 漏了 liveness，或反之？
- [ ] 每条 SVA 是否归入 S1~S7 唯一主类？
- [ ] 每条 SVA 是否有 `cover property` 统计 antecedent？
- [ ] 是否存在 antecedent 从未触发的 vacuous SVA？
- [ ] 每条 SVA 是否绑定格子/路径/Feat？
- [ ] 是否存在语义重复的 SVA？
- [ ] 资源类契约是否 SVA + SB 双覆盖（SVA 卡不变量，SB 卡具体值）？
- [ ] `illegal_bins` 与 safety SVA 是否职责清晰、不重复不遗漏？

---

## 11. 一句话总结

**SVA 分解的通用方法学 = 五类契约输入 × 五维正交展开 × 七类断言模板 × 六步漏斗 × 五项完整性度量。** 每条 SVA 必须能回答“从哪条契约来、检查什么性质、绑定哪个格子、触发过没有”；答不全就是孤立断言，antecedent 没触发就是 vacuous pass。分解的终点不是“写了一堆断言”，而是“契约覆盖 100%、格子绑定 100%、非 vacuous 100%、零重复”。