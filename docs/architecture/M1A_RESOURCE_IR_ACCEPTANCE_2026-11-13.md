# M1-A：Resource / Interaction IR Fail-Closed 验收记录

**日期**：2026-11-13  
**范围**：仅 M1-A 静态声明校验与三态门禁  
**起点**：Git `7cc3645c0530a4721c244b37025a74ffd0105ed9`  
**机器证据**：[m1a_acceptance_evidence.json](../../review_bundle/m1a_acceptance_evidence.json)  
**不覆盖**：Runtime Checker 执行、RTL 仿真、跨 Run Evidence、自然语言自主验证、自动修复闭环。

---

## 1. 验收结论

**M1-A 的代码实现与定向验收已完成。原三个错误 PASS 已分别变为 INCOMPLETE / INCOMPLETE / FAIL；合法 DMA/GEMM 声明级示例未回归。**

本次只验收：

- Resource / Interaction 声明能否被严格、确定性地校验；
- 非法、未知或缺失输入是否还会被错误放行；
- Engine、Audit、CLI 是否有一致的三态处置；
- 既有合法静态 DMA/GEMM 示例是否保持行为。

**本文件不是 RTL 仿真报告，也不是 Verification Signoff PASS。** `PASS` 的范围在机器证据中标为 `static_declaration_check_only`。

---

## 2. 原三个 fail-open 反例：修复前后实测

| 反例 | 修复前 | 修复后 | 规则 |
|---|---|---|---|
| `FORBIDEN_OVERLAP` 拼错策略 | PASS，按 UNRESTRICTED | **INCOMPLETE** | `unknown_policy` |
| 访问 length = 0 / -1 | PASS，被当成无重叠 | **INCOMPLETE** | `invalid_access_length` |
| 两个访问完全超出资源 base/size | PASS | **FAIL** | `access_out_of_bounds` |

证据文件中的 `facts` 是校验时生成的中间记录，**最终三态和 `validation` 才是裁决依据**；带有非法声明的中间地址计算不得被解释为 RTL 执行事实或签核证据。

### 进一步封住的旁路

- 负地址、非法整数、float/bool 数值；
- 非法 granularity、非法 check_window；
- 未绑定 Resource、缺失/重复 ID；
- 缺失或非法 address_space，以及跨地址空间比较；
- 空 resources / operations / interactions / accesses；
- 有访问但没有完整 base/size；
- Resource 自身和访问区间超出地址宽度；
- malformed YAML / JSON、非 mapping 根节点、不可读文件；
- 无效或损坏的 `resource_intent_result.json`；
- Audit 将 INCOMPLETE 当成可通过状态。

---

## 3. 统一裁决语义

### Engine 与 CLI

| 状态 | 本阶段语义 | CLI 退出码 |
|---|---|---:|
| PASS | 声明合法，已完成本阶段所要求的静态校验 | 0 |
| FAIL | 存在确定的禁止重叠、访问越界或地址宽度溢出等违规 | 1 |
| INCOMPLETE | 输入缺失、非法、未知或结果不可读，无法完成裁决 | 2 |

真实进程级命令验证：

```text
resource_intent.yaml      → PASS        exit 0
dma_gemm_conflict.yaml    → FAIL        exit 1
unknown_policy.yaml       → INCOMPLETE  exit 2
```

### Audit

[resource_intent_hard_ok()](../../src/engine_plane/audit/helpers.py#L1176-L1178) 现在只允许：

- `PASS`：资源静态检查通过；
- 空状态：普通、未声明资源模型的 Run，资源检查在当前 profile 下不适用。

`FAIL`、`INCOMPLETE` 和未知状态都不能再满足资源检查硬门禁，不能只依靠 caveat 被放行。Audit 主链的取值与硬门禁见 [audit/main.py](../../src/engine_plane/audit/main.py#L162-L169)。

损坏的结果文件返回 `INCOMPLETE`，而不是和“不存在结果”混为一谈，见 [read_resource_intent_status()](../../src/engine_plane/audit/helpers.py#L1159-L1173)。

**其他签核硬条件仍然存在**：这里通过的是 Resource intent 的一项门禁，不是跳过回归、覆盖率、RTL 真实性或完整 Evidence 审查。

---

## 4. 实现内容

### 4.1 Resource Model：先验证声明，再解释地址

[model.py](../../src/mental_ir_plane/decision/resource_model/model.py) 已增加：

- 整数与容器解析错误记录，禁止失败后静默变成合法的 0；
- ID、引用、address_space、资源绑定检查；
- 完整资源边界、地址宽度、访问合法性检查；
- 未知策略与跨 address_space 的不可裁决处理；
- 必要集合、空访问、粒度及时间窗口检查。

`declaration_errors` 只保留解析错误供统一校验，**不写入公开的 ResourceModel JSON**。

`validate()` 保留返回 list 的调用方式，validation item 新增 `status`：

- `INCOMPLETE`：输入声明本身不能支持裁决；
- `FAIL`：确定的地址或资源访问违规。

### 4.2 Policy：未知策略不再降级成无限制

[policy.py](../../src/mental_ir_plane/decision/resource_model/policy.py#L18-L28) 对未知策略返回：

```json
{
  "valid": false,
  "incomplete": true,
  "conflict": false,
  "requires_checker": false,
  "reason": "未知策略，不能裁决"
}
```

它不会再用 UNRESTRICTED 的含义来宣布无冲突。已有合法策略的原字段与区间关系继续保留。

### 4.3 Engine：文件读取与最终裁决统一

[resource_intent.py](../../src/engine_plane/verify/resource_intent.py) 现在分别负责：

- [verify_document()](../../src/engine_plane/verify/resource_intent.py#L63-L117)：模型校验、地址事实和三态结论；
- [_decide()](../../src/engine_plane/verify/resource_intent.py#L120-L136)：统一裁决，声明不完整优先于基于该声明的事实判定；
- [read_document()](../../src/engine_plane/verify/resource_intent.py#L139-L163)：YAML/JSON 和根节点形状解析；
- [verify_file()](../../src/engine_plane/verify/resource_intent.py#L166-L176)：文件输入和兼容既有入口。

Malformed 输入现在仍具有 `resource_intent_result_v1` 结果形状和 `intent_hash`，但状态为 INCOMPLETE，不需要靠捕获解析异常推断。

### 4.4 Verify 与 Audit：错误结果会进入主链

[write_resource_artifacts()](../../src/engine_plane/verify/ir_artifacts.py#L213-L280) 复用同一文件解析入口，先把 INCOMPLETE 结果写给 Audit，不再只写一条 warning 就跳过。

当声明文件被移除时，同时清理上一轮残留的 `resource_intent_result.json`，避免旧结果继续充当当前结论。

Audit 的损坏结果与缺文件已被区分；INCOMPLETE 仍产生 `RESOURCE_INTENT_INCOMPLETE` caveat，同时硬门禁为 false。

---

## 5. 测试与验收证据

### 5.1 新增测试

[test_resource_intent_fail_closed.py](../../tests/test_resource_intent_fail_closed.py) 共 **70 项**。

覆盖用户要求的负例：

| 类别 | 覆盖情况 |
|---|---|
| Unknown Policy | 未知关系不能获得 PASS，策略 API 标记 invalid/incomplete |
| 地址与长度 | Negative Address、Zero Length、Negative Length |
| 数值解析 | Invalid Integer、float/bool、非法 granularity、非法地址宽度 |
| 资源边界 | 缺失边界、访问越界、资源边界超宽、Address Width Overflow |
| 身份与绑定 | Duplicate IDs、Missing IDs、缺失 Resource、Unknown references |
| 输入结构 | Empty Accesses、必需集合、非法容器、非 mapping 根节点 |
| 地址关系 | PARTIAL / FULL / CONTAINED / ADJACENT / NONE、Cross Address Space |
| 文件解析 | malformed YAML/YML/JSON |
| 合法兼容 | 原有三个 DMA/GEMM 示例、operation 简写、hash 稳定、输入不被修改 |
| 调用一致性 | Engine / Audit / CLI 三态、损坏结果读取、Audit 硬门禁 |

最终定向执行结果：

```text
tests/test_resource_intent_fail_closed.py
70 passed
```

### 5.2 合法 DMA/GEMM 场景保持预期

| 输入 | 结果 | 数量 |
|---|---|---|
| [resource_intent.yaml](../../examples/open_npu_soc/spec/resource_intent.yaml) | PASS（仅静态声明检查） | 2 resources / 8 operations / 4 interactions / 4 scenarios |
| [dma_gemm_conflict.yaml](../../examples/open_npu_soc/spec/dma_gemm_conflict.yaml) | FAIL（确定的禁止重叠） | 1 resource / 2 operations / 1 interaction / 1 scenario |
| [dma_gemm_interaction.yaml](../../examples/open_npu_soc/spec/dma_gemm_interaction.yaml) | PASS（仅静态声明检查） | 2 resources / 8 operations / 4 interactions / 4 scenarios |

三份输入均没有新增 validation error；实际 `intent_hash`、计数和 coverage 保存在机器证据中。

### 5.3 相关定向回归

```text
M1-A tests + architecture_guard + architecture_invariants + workbench_planes
107 passed

M1-A 及相关 Guard / stages / verify_steps_dag 测试
152 passed（其中 M1-A 当时是 66 项，后续边界已补到 70 项）

tests/test_signoff_flow.py（补齐 greenlet 后）
9 passed
```

Workbench 的 77 项 manifest / registry / flow view 测试通过。完整 Workbench 补充回归运行到结束，正文为 **693 passed**，耗时 3230.08 秒；输出包含 PySide6 callback destructed 析构警告，包装器记录 exit 1。该结果不代表对警告的内容验收，不将 GUI 运行解释为无警告。

### 5.4 仓库全量 tests/

最终全量测试：**1308 passed、16 skipped，`PYTEST_EXIT=0`**（1322 collected，其中 2 项在收集时跳过）。

此前执行到结束的中间版本为 1307 passed / 16 skipped / 1 failed；唯一失败是缺少 `greenlet`。已用 `sqlalchemy[asyncio]` 补齐后，失败文件单独复验通过，最终全量数据以上述结果为准。

### 5.5 静态检查

- 新增/主体修改的 Model、Policy、Engine、测试：configured `ruff check` **通过**；
- Verify / Audit 集成修改：compileall 与 E4/E7/E9/F 检查通过；Audit 主文件既有 20 个未使用 import，没有在本阶段做无关清理；
- `python -m config.architecture_guard`：**[architecture] OK**；
- `git diff --check`：通过；未产生空白错误。

---

## 6. 修改文件

| 文件 | 修改目的 |
|---|---|
| [model.py](../../src/mental_ir_plane/decision/resource_model/model.py) | 声明解析、ID/引用/数值/边界校验，fail-closed |
| [policy.py](../../src/mental_ir_plane/decision/resource_model/policy.py) | 未知策略不可裁决，不按 UNRESTRICTED |
| [resource_intent.py](../../src/engine_plane/verify/resource_intent.py) | 文件解析、三态裁决、坏的文件结果结构化 |
| [ir_artifacts.py](../../src/engine_plane/verify/ir_artifacts.py) | 复用解析入口，错误结果落盘，避免旧结果残留 |
| [helpers.py](../../src/engine_plane/audit/helpers.py) | 损坏结果归类 INCOMPLETE，明确硬门禁 |
| [audit/main.py](../../src/engine_plane/audit/main.py) | 消费新的硬门禁，INCOMPLETE 不再只靠 caveat 放行 |
| [test_resource_intent_fail_closed.py](../../tests/test_resource_intent_fail_closed.py) | 新增 70 项参数化正负例与集成测试 |
| [architecture_budget.yaml](../../config/architecture_budget.yaml) | Guard --reduce-debt：已缩小 CLI 文件预算 792 → 773 |
| [complexity_baseline.json](../../config/complexity_baseline.json) | Guard --reduce-debt：清除已低于阈值的 `from_dict` 24 → 删除 |
| [architecture_debt_history.jsonl](../../config/architecture_debt_history.jsonl) | 上述两笔债务偿还的追加记录，未抬高预算 |
| 本验收文档及 [机器证据](../../review_bundle/m1a_acceptance_evidence.json) | 固化实际结果与范围 |

未新增 Agent、未迁移目录、未修改八平面职责、未扩大依赖 allowlist、未批准新增复杂度债务。`from_dict` 拆分后复杂度从登记的 24 降至 10，按 Guard 规则执行偿还；CLI 文件预算下调是 Guard 对历史缩小文件的一次正常收紧。

---

## 7. 兼容性与使用边界

### 保持的接口

- `ResourceModel` 及 Resource / Operation / Access / Interaction 的核心数据形状；
- `from_dict()`、`model.validate()`、`model.interaction_facts()`；
- `verify_document()`、`verify_file()`、`write_result()`；
- `vagent resource verify` 与既有 PASS / FAIL 退出码；
- operation 上直接写 address / length 的简写。

### 有意的语义变化

1. 之前会被吞成 0 或默认 UNRESTRICTED 的非法输入，现在不能获得 PASS。
2. 非法 YAML/JSON 从解析异常变为结构化 INCOMPLETE 结果；CLI 保持非零退出。
3. validation item 增加 `status` 和更细 `rule`，下游不能假定只有旧三键。
4. 有访问操作的 Resource 必须给出完整的 base/size；缺失时返回 INCOMPLETE，而不是绕过边界证明。
5. Audit 的 INCOMPLETE 硬门禁变为 false；无资源声明的普通 Run 仍保留原放行语义。

### 测试环境

本机原先缺少部分开发依赖；验收中补齐了 pytest-asyncio、ruff 与 SQLAlchemy asyncio extra。它们是测试执行环境，不是本轮新增的产品平面或 Agent。

### 未声称完成的验证

- **未运行真实 RTL 仿真**；
- **本阶段未生成一份新的 SystemVerilog checker**；
- **未收集仿真 seed 或 checker 运行时结果**；
- **未实现 SERIALIZED / ORDERED / ARBITRATED 等运行时证明**；
- **未做 M2 跨 Run 失效传播**；
- **未实现 M3 自然语言自主验证和 M4 修复闭环**。

`resource_intent_result` 的静态 PASS 不能替代任何上述证据。

---

## 8. 遗留事项与下一阶段

本阶段没有解决原评审中的所有 M0/M1/M2 问题，尤其没有顺带修改：

- M0 的多环检测、整层依赖债务、CI 旧路径、Guard 自身预算；
- M1-B 的运行时操作观测、仲裁/顺序/互斥检查；
- M2 的真实 package trust 组合校验与跨 Run 失效传播；
- M4 staging_root 隔离与 Engine 复验接线。

**下一独立阶段应是 M1-B：选一个 DMA/GEMM 场景，补齐 agent/watch，生成并实际执行 checker，保存 seed、运行时结果、hash 与 Audit 证据，再分别报告 Static Check、Runtime Check 与最终 Signoff。**

在此之前，停止扩展架构，并继续保留“静态检查 PASS ≠ RTL 仿真 PASS ≠ Verification Signoff PASS”这一硬边界。
