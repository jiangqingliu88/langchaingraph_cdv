现在这份 Architecture 4.0，比之前的版本成熟了不少。尤其是你补充了 Architecture Guard 2.0 的原则、已知限制、C Model 的 Golden 状态管理，以及 Provenance 和自主恢复问题。

但我想给你一个更重要的判断：

SignOffAI 现在已经从架构迁移阶段，进入了架构治理与核心能力闭环阶段。下一步不应该继续追求目录上的完整，而应该证明八个平面能够真正协同工作。

我分几个方面讲。

# 一、现在的 SignOffAI 到底是什么架构？

Architecture 4.0 逻辑架构

我建议保留八个平面的逻辑架构，不再增加新的顶层架构概念。

Interfaces Plane

CLI · Workbench · API · Human Interaction

Agent Plane

理解 · 规划 · 专家分析 · 修复建议

Orchestration Plane

任务分解 · 调度 · 状态机 · 闭环控制

Generation Plane

RTL / UVM / SVA / CModel

Engine Plane

编译 / 仿真 / 检查 / 裁决

IR Plane

Intent · Execution · Resource · Interaction · Evidence

Knowledge Plane

协议 · 规范 · IP 知识

Experience Plane

历史失败 · 修复经验

Runtime Plane

进程 · EDA · 沙箱 · 权限 · 工作区 · 资源管理

这里有一个重要区别：

- 八个平面是职责划分。
- Intent / Execution / Evidence 是端到端责任链。
- Agent / Engine / IR / Evidence 是核心协作机制。

它们不是三套互相竞争的架构。

另外，你文档末尾的「四个平面」与前面的八平面存在口径不一致。建议统一表述：八个职责平面是整体架构，Agent、Engine、IR、Evidence 是核心可信协作体系，不要再把它们称为另一套四平面架构。

# 二、现在最值得肯定的五个升级

| 升级                 | 实际意义                  |
| ------------------ | --------------------- |
| Agent 与 Engine 分离  | AI 不再自行宣布验证通过         |
| IR 统一语义            | 减少 Agent、生成器、执行器之间的耦合 |
| Evidence 驱动签核      | 结果能够追溯，而不是只看 LLM 总结   |
| Provenance         | 建立输入、产物、执行和结果的关系      |
| Architecture Guard | 防止系统随着功能增长逐渐失控        |

其中我认为最重要的是第三点。

传统 AI 验证工具容易出现：

```
AI 生成代码
    ↓
AI 分析日志
    ↓
AI 认为通过
    ↓
输出成功
```

你的目标架构应该是：

```
AI 生成候选代码
    ↓
确定性 Engine 执行
    ↓
检查器验证结果
    ↓
Evidence 收集
    ↓
Audit 检查证据完整性
    ↓
Signoff Gate 裁决
    ↓
PASS / FAIL / INCOMPLETE
```

这才是 SignOffAI 真正应该建立的技术壁垒。

# 三、但是目前存在四个架构问题

这部分我认为比继续增加 Agent 更重要。

## 1. 八平面与实际目录需要统一

你提供的目标目录已经变成：

```
src/
├── agent_plane/
├── orchestration_plane/
├── generation_plane/
├── engine_plane/
├── ir_plane/
├── knowledge_plane/
├── experience_plane/
├── runtime_plane/
└── workbench/
```

这很好。

但注意，你之前的 `src/core/` 并不是完全消失，而是被规划迁移到了：

```
runtime_plane/
└── core/
```

这意味着 core 从系统核心业务容器，变成了 Runtime 内部实现。

这是合理的方向，但要确保其中没有残留决策、签核、验证业务逻辑。

尤其是：

- decision 不应该因为迁移方便就全部塞入 Runtime。
- provenance 不应该与普通运行时日志混为一谈。
- contracts 不应该形成一个没有边界的全局公共包。

## 2. Architecture Guard 需要升级到新架构

优先级最高

这是我从你之前贴出的 Guard 代码中发现的一个实际问题。

之前代码的 `_ZONES` 仍然识别：

```
("src/core/", "core")("src/engine/", "iface")("src/agent/", "iface")("src/ir/", "ir")("src/runtime/", "runtime")
```

但是现在的架构已经迁移到：

```
src/agent_plane/
src/engine_plane/
src/mental_ir_plane/
src/runtime_plane/
src/orchestration_plane/
src/generation_plane/
src/knowledge_plane/
src/experience_plane/
```

如果你贴出的 Guard 还是当前运行版本，那么它的依赖扫描就没有真正覆盖新平面。

例如：

```
src/agent_plane/planner/foo.py
```

当前 `_zone_of()` 找不到对应 zone，会返回空字符串。

最终：

```
if not src_zone:    continue
```

这个文件直接被跳过。

也就是说，可能出现架构依赖违规，但 Guard 显示没有违规的情况。

还有一个更隐蔽的问题：

```
def write_baseline(...):    data = {        k: v        for k, v in complexity_map().items()        if v > threshold    }
```

它直接覆盖 baseline，而不是执行债务递减检查。

这与「基线是债务清单」的原则不完全一致。

另外，当前圈复杂度计算存在两个技术问题：

- `ast.walk()` 会把嵌套函数的分支也计算进外层函数。
- `path::function_name` 无法区分类中的同名方法和嵌套函数。

建议 Guard 2.0 必须解决这些问题。

## 3. Evidence 和 Provenance 需要真正闭环

你现在已经把：

```
Intent
  ↓
Plan
  ↓
Generation
  ↓
Execution
  ↓
Coverage
  ↓
Signoff
```

作为目标。

但还需要回答一个关键问题：

任何一个 PASS，能不能追溯到它依赖的所有输入和执行事实？

例如：

- RTL 版本是什么？
- UVM 版本是什么？
- IR 版本是什么？
- 使用哪个随机种子？
- 编译工具版本是什么？
- 仿真参数是什么？
- Coverage 数据来自哪次运行？
- 哪些 Evidence 支撑了最终结论？

这里还需要把 Evidence 完整性、有效性、可信度分开。

不能因为 Evidence 文件存在，就认为 Evidence 有效。

## 4. Autonomous Recovery 还需要一个严格边界

自主修复不能只是：

```
Agent 发现错误
    ↓
Agent 修改文件
    ↓
Agent 再次运行
```

应该是：

```
Failure
   ↓
Diagnosis
   ↓
Repair Proposal
   ↓
Permission Gate
   ↓
Staging Workspace
   ↓
Deterministic Verification
   ↓
Evidence Comparison
   ↓
Accept / Reject
```

特别是不能允许 Agent 修改签核规则、绕过检查器或者自行修改 Evidence 来获得 PASS。

# 四、现在应该进入什么开发阶段？

我的判断是：

# Architecture 4.0 · Engineering Maturity

架构与目录迁移

已报告完成

根据你提供的 11 月 13 日迁移说明，并非独立代码审计。

架构治理

正在升级

Guard 2.0、依赖边界、复杂度预算。

统一 IR

持续演进

UVM IR 迁移、Resource / Interaction IR。

自主验证闭环

尚需真实任务证明

DMA 验证、Agent 修复、重新执行和签核。

生产级可信签核

仍有已知限制

Provenance DAG、三态签核、Golden Reference Model 等。

注意：1249 passed 证明当前测试集通过，不等于上述所有能力都已达到生产级成熟度。

# 五、我建议接下来做这五件事

我会严格按照依赖关系安排。

M0

Architecture Guard 2.0

先让架构守卫真正认识八个新平面，建立依赖矩阵、复杂度预算和债务递减机制。

验收：所有新平面均被扫描，新增逆向依赖能够稳定触发失败。

M1

IR 统一语义升级

重点建设 Resource IR、Interaction IR，并完成 UVM IR 迁移。

验收：DMA 与 GEMM 的资源冲突能够被统一 IR 描述并由确定性检查器验证。

M2

Provenance DAG 与 Evidence v2

建立产物级血缘关系、证据完整性检查和 PASS / FAIL / INCOMPLETE 三态签核。

验收：任一签核结果都可以追溯到具体输入、产物、工具和运行记录。

M3

DMA Autonomous Verification

从自然语言需求开始，自动生成约束、测试、Checker，执行回归并分析失败。

验收：至少完成无冲突、完全重叠、部分重叠、边界相邻四类场景。

M4

Autonomous Recovery

允许 Agent 在受控工作区提出和实施修复，再由 Engine 重新验证。

验收：能够成功修复至少一类真实验证缺陷，同时证明无法绕过签核门禁。

# 六、还有一个非常重要的问题：不要把它做成 Agent 大杂烩

你现在有 Agent Plane、Orchestration Plane、Generation Plane。

这三个东西必须明确区分：

| 层次            | 核心问题     | 主要职责       |
| ------------- | -------- | ---------- |
| Agent         | 应该怎么做？   | 理解、推理、建议   |
| Orchestration | 谁在什么时候做？ | 调度、状态、闭环   |
| Generation    | 具体产生什么？  | 代码、测试、约束生成 |

例如 UVM Agent 不应该自己管理仿真进程。

Generation 不应该自行决定签核。

Orchestration 不应该自己实现地址冲突算法。

Engine 不应该依赖 LLM 判断验证是否成功。

这些边界一旦守住，系统就不会因为 Agent 数量增长而逐渐失控。

# 七、我的最终建议

现在最应该做的不是 Architecture 5.0，也不是再迁移一遍目录。

而是建立一个真正的工程里程碑：

SignOffAI Architecture 4.0 — Autonomous Verification Closure Milestone

这个里程碑只有三个核心成果：

1. Guard 2.0 真正保护八个平面的架构边界。
2. Resource / Interaction IR 能描述真实芯片资源交互。
3. DMA 验证从自然语言需求走到确定性签核，并具备一次受控自主修复能力。

这三个成果完成后，你就不只是有一个 Agentic IC Verification 架构，而是有了一个能够拿真实芯片验证任务证明自身价值的系统。

我尤其建议你现在先处理 Guard 2.0。 因为在继续扩展功能之前，必须先确保架构治理工具能够看见、识别并约束现在的架构，而不是继续用旧架构的规则保护新架构。

一句话总结：

> Architecture 4.0 的下一阶段，不是继续扩大系统，而是让系统具备自我约束、自主执行、确定性验证和可信签核的完整能力。
