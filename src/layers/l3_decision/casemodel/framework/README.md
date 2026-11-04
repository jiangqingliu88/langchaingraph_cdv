# 方法学框架（Methodology Framework）

> 用例建模 → 测试点 IR → 执行计划 → 约束编译。**可组合、可扩展、可复现。**

## 1. 为什么是框架

旧链路里同一个判断被写了三遍：

```text
plan.build_testpoints          判 stimulus/observe
associate._policy_assignments  再从维度推一次赋值
find_spec_yaml                 又自己拼回归任务
```

三处各自推导 = 三处会漂。框架把它们收成一条流水线，阶段之间只通过
`PipelineContext.artifacts` 交换数据。

## 2. 流水线

```text
                 ┌───────────────┐
 casemodel ─────►│  decompose    │  取值点 → 测试点身份（dimension/value/专题/优先级）
                 └───────┬───────┘
                         ▼
                 ┌───────────────┐
                 │  trace        │  测试点 → 覆盖仓（coverpoint.bin）
                 └───────┬───────┘
                         ▼
                 ┌───────────────┐
                 │  realize      │  实现方式策略注册表（stimulus/sequence/observe/…）
                 └───────┬───────┘
                         ▼
                 ┌───────────────┐
                 │  execute      │  test 类名 / 回归级 / 起点种子 / 判据
                 └───────┬───────┘
                         ▼
                  MethodBundle
                  ├─ testpoints.yaml    测试点 IR（下游唯一主键 tp_id）
                  └─ methodology.json   阶段/计数/输入/IR 哈希（可复现）
```

## 3. 契约

| 概念 | 位置 | 说明 |
|---|---|---|
| `Stage` | `contracts.py` | `name` / `consumes` / `produces` / `run(ctx)` |
| `PipelineContext` | `contracts.py` | 阶段之间唯一的交换面；`notes` 记录所有"判不了" |
| `Registry` | `contracts.py` | 扩展点：`register` / `get` / `require` / `unregister` |
| `TestPoint` | `model.py` | 稳定数据形状（身份 + 观测端 + 实现方式 + 执行 + 判据） |
| `MethodBundle` | `pipeline.py` | 产物包（`to_dict` / `testpoints_yaml` / `manifest`） |

**不变式**

1. 阶段顺序由流水线决定，阶段之间零 import；
2. 依赖缺失在**启动前**报错（不是跑到一半拿到 `None`）；
3. 截断只发生在所有阶段之后，边界取值优先；
4. 所有"没声明/对不上"进 `notes`，不静默；
5. 产物带 `manifest`：阶段 + 计数 + 输入 + IR 哈希。

## 4. 扩展手册

### 4.1 新增一种 realization（不改核心）

```python
from casemodel_tools.framework import REALIZATIONS, Realization

@REALIZATIONS.register("backdoor")
class BackdoorRealization:
    kind = "backdoor"

    def resolve(self, req):
        return Realization(kind="backdoor", extras={
            "path": f"dut.{req.dim.key}", "value": req.value})

    def validate(self, tp, ctx):
        return [] if tp.realization.extras.get("path") else ["缺少后门路径"]
```

模型里写：

```yaml
- id: D_queue
  realization: {kind: backdoor}
```

### 4.2 新增一个阶段

```python
from casemodel_tools.framework import MethodologyPipeline, Stage

class CheckpointStage(Stage):
    name = "checkpoint"
    consumes = ("testpoints",)
    produces = "testpoints"

    def run(self, ctx):
        ...

pipeline = MethodologyPipeline().insert(CheckpointStage(), after="trace")
```

### 4.3 新增一种约束编译器

```python
from casemodel_tools.framework.constraints import CONSTRAINT_COMPILERS

@CONSTRAINT_COMPILERS.register("cross-illegal")
class CrossIllegalCompiler:
    name = "cross-illegal"
    def compile(self, req):
        return [...]
```

`associate.build_constraint` 通过注册表调用，不写 if/elif。

## 5. 产物契约

### `testpoints.yaml`

```yaml
testpoints:
  - tp_id: TP-NPU-D_TYPE-MAC
    dimension: D_type
    value: MAC
    coverpoint: cp_instr_type
    bin: mac
    requirement: REQ-NPU-002
    realization: {kind: stimulus, agent: npu_sched_in, field: instr_type, value: 0}
    execution:
      test: npu_sched_env_d_type_pMAC_test
      stage: p0
      seeds: [2001, 2002]
    status_rule: {pass: "UVM_ERROR=0 and mismatched=0"}
    observe_only: false
```

下游只认 `tp_id`：

- `uvm_tools`：属性 test 注释 / `environment.tests` / 回归任务；
- 覆盖率：`tp_matrix.json`（TP × bin 命中）；
- 审计：按 TP 汇总三态（PASS / OBSERVE_ONLY / NOT_RUN）。

### `methodology.json`

```json
{
  "framework": "signoff-methodology",
  "version": "1.0",
  "stages": [{"name": "decompose", "count": 63}, ...],
  "inputs": {"env_name": "npu_sched_env", "module_name": "npu_sched"},
  "summary": {"count": 63, "by_kind": {"stimulus": 26, "observe": 37}},
  "artifacts": {"testpoints_yaml": {"sha256": "...", "size": 56274}},
  "notes": [...]
}
```

> **写入纪律**：`testpoints.yaml` 必须用 `newline="\n"` 落盘。Windows 文本
> 模式会把 LF 翻成 CRLF，而 manifest 里的 sha256 算的是 LF 那份 —— 不锁
> 换行符，哈希与实际文件永远对不上（实测），证据链就失去意义。

## 6. 边界

- 框架**不生成 SV**；`uvm_tools` 通过文件契约消费。
- 框架**不做 LLM 归因**；测试点是模型推出来的。
- 观测型维度标 `observe_only` 是正确状态，不是缺陷 —— 要变成可驱动，
  在模型里补 `stimulus.field` 或注册新的 realization 策略。
