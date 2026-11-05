# 新一代 TP IR：多维验证语义模型（v2 设计）

> 状态：**P0 设计稿 + P1a/P2 部分落地**。属性模型（v1）原样保留；
> 行为域已能建模、校验并编译进 TP IR（执行后端 P1b 待接）；
> 断言已能绑定 TP 并进 `assertion_bindings`。
> 关联：根 `ARCHITECTURE.md` §7（case 建模 → TP IR）。

---

## 0. 一句话

**不是 v1 的方法学错了，而是 v1 把验证空间定义成了"静态属性取值"，
只覆盖了 CDV 的一部分。** v2 在保留 v1 的前提下，并列增加行为域与配置域，
统一挂到同一套 `tp_id` / 证据链上。

- **保留**：L1–L6 分层、`tp_id` 主键、TP IR 确定性投影、realization 注册表、
  取值点 ≠ 覆盖仓、StimulusPlan 作为后端前置层。
- **扩展**：Verification Domain（method / assertion 绑定 / legality）。
- **新增**：Behavioral Domain（状态 / 事件 / 迁移 / 序列 / 时序）、
  Configuration Domain（配置空间与可行性规则）。

**硬约束**：任何激励（人工、生成器或 AI 产出的）都必须先进入 TP IR，
再由编译器产出后端实现。**不允许**直接生成 UVM sequence 绕过主键与证据体系。

## 0.1 文档表导入（方案 B，已落地）

PM/DV lead 手工维护的 xlsx 测试点表**不当运行时真源**，而是导入视图：

```text
xlsx（该测什么） ──aivm_ir.bridge──► casemodel.yaml（怎么测，过 schema）
                                  └─ source_map.json（逐格出处 + 双哈希）
```

- 实现在 `src/tools/humanview/aivm_ir/bridge.py`；
- CLI：`vagent case-model import-xlsx` / `verify-import`；
- 映射规则、当前边界见 `src/tools/humanview/README.md`。
- 真实 xlsx 不自带维度轴 → 未给轴声明时组合格退化为**场景维度**（一格一仓，
  不冒充交叉）；给 `--axes`（`aivm_axes_v1` sidecar）后编译成真正的
  `cross_matrix` 显式仓。轴里多出来的取值记账并丢弃（表是真源）。

---

## 1. 总架构

```text
                     验证意图（spec / casemodel / config）
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────────┐
        │              Multi-dimensional TP IR                      │
        │                                                          │
        │  ┌───────────────┐   ┌───────────────┐   ┌────────────┐  │
        │  │ Attribute     │   │ Behavioral    │   │ Config     │  │
        │  │ Domain        │   │ Domain        │   │ Domain     │  │
        │  │ ─ v1 保留     │   │ ─ v2 新增     │   │ ─ v2 新增  │  │
        │  │ Object        │   │ State         │   │ config     │  │
        │  │ SubObject     │   │ Event         │   │ space      │  │
        │  │ Dimension     │   │ Transition    │   │ feasibility│  │
        │  │ Field/Value   │   │ Sequence      │   │ cross      │  │
        │  └───────┬───────┘   │ Temporal      │   └─────┬──────┘  │
        │          │           └───────┬───────┘         │         │
        │          └──────────┬────────┴─────────────────┘         │
        │                     ▼                                    │
        │          ┌───────────────────────────┐                   │
        │          │ Verification Domain       │                   │
        │          │ method / realization /    │                   │
        │          │ coverage / assertion /    │                   │
        │          │ check / legality          │                   │
        │          └─────────────┬─────────────┘                   │
        └────────────────────────┼─────────────────────────────────┘
                                 │  统一关联层
              TP ID ─── Provenance ─── Association ─── Evidence
                                 │  编译
          ┌──────────────────────┼───────────────────────┐
          ▼                      ▼                       ▼
   UVM 生成后端            StimulusPlan            Coverage 渲染
   (属性 test / 行为 test)  (generated / player)    (covergroup / cross)
```

设计要点：

1. **域是并列的，不是嵌套的** —— 行为/配置不是新的 field 类型，不塞进
   `dimensions`；否则属性模型会被时序语义污染，v1 的消费者全部要改。
2. **统一主键在关联层**：三个域最终都产出 `tp_id`，走同一套 TP 矩阵、
   归因、证据包。
3. **分区编译**：属性域按现有流水线编译；行为域与配置域各自有编译器，
   在 TP IR 合并成 task 图。

---

## 2. 各域定义

### 2.1 Attribute Domain（保留，v1 原样）

`Object → SubObject → Dimension → Field → ValuePoint`；`relation` 表达字段取值
的 independent / linkage / exclusive。

语义：**"某个功能点有哪些属性取值，是否都打到"**。这一层不动，已有 63 条 TP
的 `tp_id`、覆盖仓、证据全部保持。

### 2.2 Behavioral Domain（新增）

> 语义：**"在什么状态、经过什么事件与迁移、满足什么时间约束，才算被验证"**。

```yaml
behavior:
  id: BEH-QUEUE-001
  name: 队列水位迁移
  clock: clk
  reset: {signal: rst_n, active_low: true}

  states: [EMPTY, LOW, HIGH, FULL]
  events: [enqueue, dequeue, reset]

  transitions:
    - {id: TR-001, from: EMPTY, event: enqueue, to: LOW}
    - {id: TR-002, from: LOW,   event: enqueue, to: HIGH}
    - {id: TR-003, from: HIGH,  event: enqueue, to: FULL}
    - {id: TR-004, from: FULL,  event: dequeue, to: HIGH}

  sequences:
    - id: SEQ-001
      steps:
        - {event: enqueue, repeat: 3}
        - {event: dequeue, repeat: 2}
      expects: [no_overflow, occupancy_consistent]

  temporal:
    - id: TMP-001
      trigger: enqueue
      condition: {queue_full: true}
      response: {backpressure: true}
      within: {cycles: 1}
      reset_policy: abort            # abort | hold | ignore
```

编译产物（每个节点一条 TP，沿用同一主键前缀）：

| 节点 | TP 形态 | 覆盖口径 |
|---|---|---|
| 状态 | `TP-<obj>-STATE-<state>` | 状态到达 |
| 迁移 | `TP-<obj>-TR-<id>` | 转移覆盖（边覆盖） |
| 序列 | `TP-<obj>-SEQ-<id>` | 步骤 + 期望检查点 |
| 时序性质 | `TP-<obj>-TMP-<id>` | 触发-响应命中 / 违例 |

**边界（第一版刻意克制）**：

- 不做通用状态机 DSL（层次态、并行态、伪态先不做）；
- 序列是**线性步骤列表**（repeat + after），不做任意正则/时序逻辑；
- `temporal` 只支持 `trigger → within N cycles → response` 这一类 SVA 可表达的形式；
- 每个行为节点**必须**能落到一个具体的 `check` 或断言，否则不许进 TP
  （"走过边"不等于"验过"）。

### 2.3 Configuration Domain（新增）

> 语义：**"功能在哪些 DUT/特性配置下成立"**。配置改变功能空间，不是运行环境。

```yaml
config_space:
  dimensions:
    - {name: queue_depth,   values: [8, 16, 32]}
    - {name: dma_channels,  values: [1, 2, 4]}
    - {name: gemm_enable,   values: [true, false]}
  cross_groups:
    - {id: XG-CFG-01, dimensions: [queue_depth, dma_channels], level: required}
  feasibility:                 # 非法组合不是覆盖率缺口，是不该跑
    - id: CFG-RULE-01
      when: {gemm_enable: false}
      then: {disable_tps: ["TP-NPU-GEMM-*"]}
```

- 配置维度参与 `tp_id` 的**实例化**（同一 TP × 配置组合 = 一个执行实例），
  但不改 TP 本身的编号；
- 配置可行性规则在**编译期**求值：不可行组合直接不生成实例，且要进
  `notes` 记账（不能让它悄悄消失）；
- 工具版本 / seed / 平台参数仍属于运行上下文，**不**进配置空间。

### 2.4 Verification Domain（扩展）

| 项 | v1 | v2 |
|---|---|---|
| method | 枚举 + 文字约定 | **策略注册表**（见 §4） |
| realization | 注册表（4 种） | 新增 `behavior`（序列驱动的复用） |
| coverage | 取值/bin/cross | 增加 transition / sequence / temporal 覆盖类型 |
| assertion | 信号级 | **`tp_bindings`：一对多 + primary/supporting** |
| legality | forbidden cross + illegal bins | 统一 Legality Model，保留两类语义（见 §5） |

断言绑定示例：

```yaml
assertions:
  - id: ASSERT-APB-001
    name: p_apb_stable
    expr: "psel && penable && !pready |=> $stable({paddr,pwrite,pwdata})"
    signals: [{name: paddr, width: 32}, ...]
    tp_bindings:
      - {tp_id: TP-APB-001, role: primary}
      - {tp_id: TP-APB-003, role: supporting}
    failure_policy: {severity: error}
```

注意：**绑定是关联，不是归因**。断言失败时报告"受影响 TP"，
真正归因仍需 run / sequence / 时间窗口 / 激励上下文证据。

### 2.5 统一关联层（不变）

`tp_id` / `docs/provenance.jsonl` / `coverage/association_report.json` /
`signoff_evidence/`。v2 新增的 TP 与 v1 共用同一套矩阵与证据包格式。

---

## 3. 保留 / 扩展 / 新增

| 能力 | 处置 | 兼容要求 |
|---|---|---|
| L1–L6 属性模型、`tp_id` 生成规则 | **保留** | v1 casemodel 不写新字段必须照样通过 |
| TP IR 字段与序列化（`serialize.py`） | **保留** | 新增域用**并列顶层键**，不改 `testpoints[]` 条目 |
| realization 注册表 | **扩展** | 新 kind 只注册策略，不改核心阶段 |
| StimulusPlan 格式 | **保留** | 新增 behavior 条目后仍确定性可哈希 |
| coverage / bin / cross | **扩展** | 新增覆盖类型用独立 section |
| assertion | **扩展** | `tp_bindings` 可选；不写时行为与 v1 相同 |
| method | **替换实现** | 枚举与模型格式不变，映射从文字变策略 |
| 状态 / 时序 / 配置 | **新增** | 独立顶层键；没有就不编译该域 |
| Workbench / CLI / 证据包 | **不动** | 只消费 TP IR 与证据文件 |

---

## 4. Method 从枚举变成策略

```python
class MethodStrategy(Protocol):
    id: str                       # D / RND / G / RPLY / SPCL
    def compile(self, tp, ctx) -> StimulusSpec: ...
    def feedback(self, plan, coverage) -> Optional[Replan]: ...  # G 用
```

| method | 执行语义 | 落地方式 |
|---|---|---|
| D | 精确输入与条件 | 固定取值 + 定向 sequence |
| RND | 受约束随机 | constraint + seed 实例化 |
| G | 目标导向搜索 | 读覆盖缺口 → 下一轮取值/配置 |
| RPLY | 重放历史执行 | 读 plan + 记录的事务流 |
| SPCL | 专用协议/场景生成器 | 按行为模型编译序列 |

判断标准：**方法必须在编译产物里有可观察差异**，不能只是文字备注。
（现状：只有 `RND → random`、其余 `cycle`，见 P5。）

---

## 5. Legality Model

两类语义分开、统一管理：

```yaml
legality:
  field_rules:            # 字段自身不合法（非法值）
    - {field: operation, illegal_values: [INVALID]}
  combination_rules:      # 各自合法，组合不合法
    - {forbidden: {operation: READ, mode: DEBUG}}
```

- `field_rules` 影响取值空间与 bin 统计（非法值不计入普通覆盖）；
- `combination_rules` 影响 TP 生成（禁止组合不产 test，进 `notes` 记账）；
- 两者都给 error 级静态检查，不许等到仿真。

---

## 6. 静态语义检查（编译期）

| 检查 | 级别 | 状态 |
|---|---|---|
| 每个覆盖仓至少一个取值点可达 | error | ✅ 已有 `cover_bin_unreachable` |
| **每个取值点至少落进一个仓** | error | ✅ 本轮新增 `value_point_unmapped` |
| **仓之间取值重叠** | warning | ✅ 本轮新增 `cover_bin_overlap` |
| 非法值不得计入普通仓 | error | 待做 |
| forbidden 组合不得进入合法 TP | error | 待做 |
| 断言绑定的 tp_id 必须存在 | error | ✅ 本轮新增 `assertion_tp_unknown` |
| 已启用绑定的模型里，断言不得漏绑 | warning | ✅ 本轮新增 `assertion_unbound` |
| 行为节点的每条迁移/序列至少一个 check | error | 待做（v2 行为域） |
| 配置不可行组合不得生成实例 | error | 待做（v2 配置域） |

原则：**能在建模期判死的，不在仿真期发现。**

---

## 7. Seed 与 Run 绑定

```text
Test Definition → StimulusPlan（模板，确定性）
        └─ Run Instance（seed 属于实例，不属于模板）
              seed.requested / seed.effective / rng 版本 / 执行顺序上下文
```

- plan 的 `sha256` 只描述**计划**；可复现性由 run 级 `{plan_id, seed,
  rtl_hash, config_hash, tool_version}` 保证；
- 只记录 seed 并不足以重建随机流：需要 RNG 实现/版本与调用顺序。
  报告里如实标注"可复现"与"仅记录 seed"的区别。

---

## 8. 验收标准（v2 完成时）

1. 一个 TP 可以表达静态属性，也可以表达状态迁移；
2. 一个 TP 可以关联多个断言；
3. 一个 TP 可以在不同 DUT 配置下实例化；
4. 一个 sequence 可以生成可统计的行为覆盖；
5. 一个 run 可以完整重建其 StimulusPlan、seed 与执行上下文；
6. 每个覆盖仓都有合法来源；
7. 每个取值点都有明确覆盖归属；
8. 签核结论可以追溯到实际执行证据。

验证载体：`npu_sched`（状态+迁移+并发）、`apb_uart`（协议时序+断言）、
GEMM/DMA（配置+地址关系+并发）。

---

## 9. 演进顺序与守门判据

| 阶段 | 内容 | 守门判据（必须全绿才进下一阶段） |
|---|---|---|
| **P0** | 本文 + 边界定义 | 文档与代码事实一致；v1 全量测试绿 |
| **P1** | Behavioral：State/Transition/Sequence/Temporal | **P1a 完成**：schema / 解析 / 三条静态检查 / 行为 TP 进 IR；`tp_matrix` 已接入（`PENDING_BACKEND` 单列，不进覆盖率分母）；**执行后端仍在 P1b**；v1 产物字节不变 |
| **P2** | Assertion → TP 绑定 | **部分完成**：schema + 解析 + 反向索引（`assertion_bindings`）+ 两条静态检查已落地；失败报告列出受影响 TP 待接 run 证据 |
| **P3** | Configuration 轴 | **P3a/P3b 完成**：schema / 解析 / 四条校验 / 组合可行性；每条 TP 挂 `config_instances`（可行组合，`disable_tps` 按组合生效），摘要带 `instances_total`；`tp_id` 不分叉。**按配置切换编译/执行**仍未做 |
| **P4** | 静态一致性（双向检查、legality） | ✅ 双向检查已落地；剩余见 §6 |
| **P5** | Method Registry | **完成**：`framework/methods.py` 单一真相（策略名后缀 / 组合器模式 / 赋值方式）；`associate` 两张表与约束编译器都从它派生，产物字节不变。G 的反馈闭环（读缺口 → 下一轮）仍未实现 |
| **P6** | StimulusPlan / seed / run 绑定 | 同一 run 可重建 plan + 随机流上下文 |

**兼容纪律**：每个阶段都必须满足"v1 模型不改一行仍通过全量测试"。

---

## 10. 不做的事

- 不把 State/Temporal 塞进 `dimensions`；
- 不重排既有 `tp_id`；
- 不做通用状态机 DSL / 时序逻辑语言；
- 不让 AI 直接生成最终 UVM sequence 绕过 TP IR；
- 不一次性扩 schema：每个域独立开关、独立编译、独立验收。
