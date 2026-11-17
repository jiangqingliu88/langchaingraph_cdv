# Mental IR —— agent 的「心智模型」

> 状态：**独立路径已可用**（`vagent mental build`），尚未挂进 supervisor 闭环。

## 1. 它解决什么问题

Case / Execution / Evidence IR 回答的是「验证什么、怎么跑、跑出了什么」。
Mental IR 回答更靠前的一层：

- 这份规格到底要求证明什么？
- 哪些前提是**假设**，一旦不成立会怎样？
- 哪里还没说清？是否必须先找人澄清？
- 每条验证意图期望什么证据？
- 设计与验证过程有哪些风险？

它把「理解」变成可审阅、可哈希、可引用的数据，而不是藏在 LLM 的上下文里。

## 2. 不是什么

- **不是签核证据**：Mental IR 是候选理解，必须人来审；`blocking` 歧义未清零前
  不应把它当成验证完成的依据。
- **不是 Case IR 的替代**：Case IR 仍是用例/断言/SCB 的身份源；Mental IR 只
  解释「为什么这么验」。
- **不是另一份 IR 层**：`src/mental_ir_plane/` 现在是唯一 IR 根：
  `model.py / store.py` 是理解层，`unified/` 是融合投影，平级的
  `contract / decision / formal / interface_timing / proposal /
  specification_compiler / vplan` 是引擎与契约；统一层只消费快照，不复制引擎。

## 3. 数据模型（`mental_ir_v1`）

`src/mental_ir_plane/model.py`（Mental）与 `src/mental_ir_plane/dplan/model.py`
（DPlan IR，`dplan_ir_v1`）是两条“总”层输入：前者回答理解，后者回答实现/模型契约。

| 字段 | 说明 |
|---|---|
| `module` | 模块名 |
| `source_anchors` | 输入锚点：spec / case_ir / testpoints 的路径 + sha256 |
| `goals` | 验证目标（`id=G*`，P0..P3，`source_refs`） |
| `assumptions` | 依赖前提（`id=A*`，`rationale`、`risk_if_wrong`） |
| `ambiguities` | 待澄清项（`id=Q*`，`blocking`、`needs_human`） |
| `verification_intents` | 验证意图（`id=VI*`，`goal_ids`、`evidence_expected`） |
| `risks` | 风险（`id=R*`，severity low/medium/high、`mitigation`） |
| `notes` | 补充说明 |
| `generated_at` / `generator` | 生成时间与 prompt 版本（**不参与哈希**） |

约束：所有 id 在整份 IR 内唯一；`digest()` 对除时间戳/生成器外的规范 JSON
做 sha256，用于回答「引用的到底是哪一版理解」。

## 4. 生成流程

```
spec 文本
   │
   ▼
mental 专家（LLM，JSON 对象）
   │  pydantic 校验（id 唯一 / 枚举 / 必填）
   ├─ 失败 → 带校验错误重试一次（最多 2 次）
   ▼
MentalIR（附 source_anchors）
   │
   ▼
<run>/mental_ir/
   ├── mental_ir.json      # 机器读
   ├── mental_ir.yaml      # 人读
   └── manifest.json       # digest + counts + generator
```

LLM 无输出 / 两次都不合法 → 抛 `MentalIRError`，**不写半成品**。

## 5. 用法

```bash
# 生成（默认输出 output_mental_<spec 名>/）
vagent mental build specs/npu_sched/docs/specs/npu_sched.md \
    -o output_mental_npu_sched

# 只看机器可读摘要
vagent mental build <spec.md> -o <run> --json
```

Python 入口：

```python
from src.agent_plane.design_understanding.mental_model_agent import run, generate_mental_ir
result = run(spec_text, "output_x", module="npu_sched", spec_path="spec.md")
ir = generate_mental_ir(spec_text, module="npu_sched")
```

## 6. 后续消费方式（尚未接线）

- verify / coverage 读取 `<run>/mental_ir/mental_ir.json`，把 goals 与
  verification_intents 作为**上下文**，而不是新的身份源；
- 引用时把 `manifest.json.digest` 一并记入证据，回答"依据的是哪版理解"；
- `blocking=true` 的歧义应由 human_review 拦下，不能自动消解。

## 7. 统一 IR（已落地分层适配器）

Mental 是唯一 IR 根；DPlan / VPlan 作为投影输入并入
`src/mental_ir_plane/unified/`：

```text
schema.py       包络 / 实体 / 关系 / 缺口
adapters/       mental / dplan / vplan（接受快照，不 import 执行引擎）
build.py        项目作用域对象图 + 最佳候选关系
views.py        Mental / DPlan / VPlan 三种只读投影
store.py        unified IR JSON 原子读写
```

```bash
vagent mental unify \
  --mental output_mental_npu_sched/mental_ir/mental_ir.json \
  --dplan specs/npu_sched/docs/specs/npu_sched_dplan.json \
  --vplan specs/npu_sched \
  --out output/unified_ir.json --views-out output/unified_views.json
```

- 旧 `mental_ir_plane/vplan/types.py` 已变为兼容入口（类型定义在
  `mental_ir_plane/unified/vplan_types.py`）；VPlan 执行引擎与 DPlan 对齐引擎保留。
- 关系默认 `candidate`；同名 native id 也只是候选，不自动升级为 confirmed。
- `Execution / Evidence` 仍是独立记录；统一 IR 不是签核表。

设计说明见 [融合优化 IR](IR_FUSION_MENTAL_DPLAN_VPLAN.md)。

## 8. 边界与待办

- 不进 supervisor 闭环：当前只有独立 CLI/服务入口。
- 不做自动澄清：歧义输出给人和后续工作流，不在本轮自动改写 spec。
- 统一层只消费快照；执行/契约引擎仍由 `contract / decision / vplan / ...` 负责。
