# SignOffAI Architecture 4.0：Guard 2.1 与 M1 接线评审

**评审日期**：2026-11-13  
**评审对象**：工作区 `D:\cdv_a`  
**评审基线**：`7cc3645c0530a4721c244b37025a74ffd0105ed9`（`feat(m1): resource intent enters DMA/SoC main chain`）  
**评审方式**：源码追踪 + 实际 Guard/CLI 运行 + 定向 pytest + Qt 离屏检查 + 临时目录反例验证  
**工作区状态**：评审开始时 HEAD 干净；本次只新增本评审文档，未改业务代码、Guard 规则或预算基线。

> 历史基线说明：本文记录的是上述 commit 的评审结果。其 M1-A fail-open 发现已在后续工作区修复，实际验收见 [M1-A 验收记录](M1A_RESOURCE_IR_ACCEPTANCE_2026-11-13.md)。

---

## 1. 执行结论

### 一句话结论

**Guard 2.1 的治理骨架已经真实落地并能运行，但还不能据此认定架构治理已经完全固化；M1 已接上“Resource/Interaction 声明 → 静态冲突判定 → 场景/证据落盘 → Audit/SoC 门禁”的骨架，但当前判定存在 fail-open 反例，也没有完成运行时资源冲突验证闭环。**

因此：

1. **方向上符合这次要求**：没有继续进行 Architecture 5.0，也没有继续拆目录；资源语义已放到确定性 Engine 中，不是再增加一层 Agent 解释。
2. **当前仓库实际进度已超过“只有 Guard 2.1”的状态**：HEAD 已包含 M1 的 DMA/SoC 主链接线。
3. **不建议按现有里程碑表把 M0/M1/M2 全部视为 ✅ 已验收**：应先处理本文 P0/P1 问题，并将能力状态改成“治理已落地、语义验证中、执行证据尚不完整”。
4. **本次 `ok=True` 只表示当前源码树通过 Guard 的预算/依赖扫描**，不等于测试无回归，更不等于真实 DMA RTL 验证通过。

### 建议的里程碑判定

| 里程碑 | 源码证据 | 本次判定 | 能否按完成签收 |
|---|---|---|---|
| M0 — Architecture Guard 2.1 | 扫描、CLI、GUI、债务命令均有实现 | **基本落地，待少量硬化** | **条件通过**：修完 §4 的 Guard/CI/文档欠账后固化 |
| M1 — Resource / Interaction IR | 已有统一模型、静态判定、场景生成、Audit/SoC 接线 | **骨架已接线，语义门禁未达签核级** | **否**：先修 fail-open 与缺失/损坏证据处理 |
| M2 — Evidence & Provenance | 单 Run 包、哈希、离线回放基础较强；新增 audit/stale 辅助命令 | **部分实现** | **否**：跨 Run 失效传播尚未实现；新 `trust` 检查不等于完整校验 |
| M3 — Autonomous Verification | 有 DMA/GEMM 声明级场景与 checker 生成基础 | **部分实现，未形成自主闭环** | **否**：尚无自然语言到生成、执行、结果裁决、签核的端到端证据 |
| M4 — Autonomous Recovery | 有 proposal 校验、staging 与保护前缀 | **受控修复原型，自动闭环未接；隔离有缺口** | **否**：先修 staging 隔离，再接 Engine 复验 |

---

## 2. 本次实际发生了什么

### 2.1 已验证通过的事实

#### A. Guard 当前全绿

`python -m config.architecture_guard` 实际退出码为 **0**，JSON 汇总为：

| 字段 | 实测 |
|---|---:|
| `tool_version` | `2.1` |
| `ok` | `True` |
| `line_issues` | 0 |
| `complexity_issues` | 0 |
| `zone_issues` / `unzoned_files` | 0 / 0 |
| `import_issues` | 0 |
| `cycle_issues` | 0 |
| 登记的 lazy dependency 方向 | 8 对 |
| `debt_issues` | 0 |

实现入口见 [architecture_guard.py](../../config/architecture_guard.py#L589-L621)。

#### B. 三个新 CLI 命令确实可用

实际执行 `vagent` 对应的模块入口：

| 命令 | 实测结果 |
|---|---|
| `python -m src.workbench.cli.commands arch --help` | 正常列出 `check / planes / matrix` |
| `... arch check` | `Guard 2.1: OK`，退出码 0 |
| `... arch planes` | 正常显示 8 个职责平面和 Workbench，退出码 0 |
| `... arch matrix --json` | 正常输出 allowed 与实际 import 计数 |

命令定义见 [cmd_arch.py](../../src/workbench/cli/cmd_arch.py#L11-L66)。平面快照由 [architecture_service.py](../../src/workbench/api/architecture_service.py#L61-L92) 提供。

#### C. GUI Architecture Planes 页面有真实绑定，不是静态示意

PySide6 离屏构造 `ArchitecturePlaneModule` 并调用真实 `architecture.snapshot` 成功：

- 表格为 **9 行 × 5 列**：8 个平面 + Workbench；
- 显示 `Guard 2.1：OK`；
- 详情显示 `没有 Guard 违规`；
- Bridge 注册目标是真实只读服务，见 [catalog.py](../../src/workbench/bridge/catalog.py#L29-L35)；
- 页面内容逻辑见 [module.py](../../src/workbench/modules/architecture/module.py#L51-L91)。

本次证明的是**页面组件能加载并填入真实 Guard 数据**，不是已完成主窗口所有交互和视觉验收。

#### D. `approve-debt` / `reduce-debt` 的单向棘轮有效

为避免污染真实预算，本次复制 Guard 源码到临时工程，并通过真实 CLI `main(argv)` 入口验证：

| 操作 | 实测结果 |
|---|---|
| 登记新增函数复杂度债务 | 成功，检查退出 0，baseline 写入实际值 23 |
| 未增长时再次批准同一债务 | 拒绝，退出码 2，提示使用 `--reduce-debt` |
| 登记 watched 文件增长 1600 → 1650 | 成功，保留 reason/plan，更新 registered |
| 文件缩小至 100 行且函数复杂度降至阈值以下 | `debt reduced: 2 entries`，最终检查退出 0 |
| reduce 后结果 | 函数条目删除，registered=100；history 有 4 条记录 |

实现位于 [architecture_guard.py](../../config/architecture_guard.py#L456-L528)。**没有发现 `--update-baseline` 式的批量抬高入口。**

#### E. 定向测试通过

| 测试集合 | 结果 |
|---|---:|
| [test_architecture_guard.py](../../tests/test_architecture_guard.py) | 17 passed |
| [test_workbench_planes.py](../../tests/test_workbench_planes.py) | 4 passed |
| [test_architecture_invariants.py](../../tests/test_architecture_invariants.py) | 16 passed |
| Workbench registry / manifest / flow views 三个测试模块 | 77 passed |
| **合计** | **114 passed，0 failed** |

说明：本机原测试环境起初缺少 `structlog` 等运行依赖；补齐声明依赖后完成上述执行。**没有声称重新跑过主文档所写的 1249 条全量单测，也没有运行真实 EDA 回归。**

#### F. Resource/Interaction 的确定性计算路径确实存在

- 数据模型覆盖 Resource、Operation、Access、Interaction，见 [schema.py](../../src/ir_plane/decision/resource_model/schema.py#L15-L68)；
- 地址重叠采用左闭右开区间，能区分 NONE / ADJACENT / PARTIAL / FULL / CONTAINED，见 [address.py](../../src/ir_plane/decision/resource_model/address.py#L35-L53)；
- 冲突由声明策略计算，不调用 LLM，见 [policy.py](../../src/ir_plane/decision/resource_model/policy.py#L17-L47)；
- 三态结果由 Engine 生成，见 [resource_intent.py](../../src/engine_plane/verify/resource_intent.py#L25-L71)；
- Verify 生成前写入资源模型和场景，随后交给 checker 渲染，见 [verification/main.py](../../src/generation_plane/verification/main.py#L231-L237)；
- Audit 已把 `FAIL` 纳入硬门禁，见 [audit/main.py](../../src/engine_plane/audit/main.py#L163-L169)；
- SoC 回归前有 `resource_intent.yaml` preflight，见 [soc_adapter.py](../../src/workbench/cli/soc_adapter.py#L718-L755)。

实际命令结果：

- 仓库内 `resource_intent.yaml`：**PASS**，2 resources / 8 operations / 4 interactions / 4 scenarios，退出 0；
- `dma_gemm_conflict.yaml`：**FAIL**，检测到禁止的 PARTIAL overlap，退出 1。

这说明“Intent → 区间事实 → 场景”不是空壳。问题是这个 `PASS` 目前的语义边界太宽，不能直接提升为“资源交互已在仿真中验证通过”。

---

## 3. 对照用户提出的五项能力评价

| 评价问题 | 当前回答 | 证据边界 |
|---|---|---|
| 1. 架构违规能否被自动发现？ | **可以发现主要类别，尚非完备** | 当前扫描全绿；已验证新平面和跨平面环反例。但多环检测、依赖债务 allowlist、CI 路径仍有欠账 |
| 2. 验证意图能否转换成统一 IR？ | **结构化 YAML → Resource/Interaction Model 已成立** | 是声明文件转 IR；尚不是自然语言自动理解到 IR 的稳定主链 |
| 3. Engine 能否独立执行和裁决？ | **静态区间/策略裁决可由 Engine 独立完成** | 不需 LLM；SERIALIZED/ORDERED 等时序关系还需要真实运行时 checker 及执行结果，不能只靠静态区间 |
| 4. Evidence 能否证明结果？ | **单 Run 证据基础较强；资源执行证据不完整** | 有 intent hash、事实、场景、包哈希与回放基础设施；尚无每场景 seed、实际 checker 输出和对应签核关系 |
| 5. Agent 能否受控修复失败？ | **尚未成立** | 当前是 CLI staging 原型；staging 根目录可绕过保护，且没有自动 Engine 复验与受控 apply/回滚闭环 |

---

## 4. P1：M0 固化前应完成的治理硬化

这些问题不否定 Guard 2.1 的方向，但会影响“系统自动检查架构”这一承诺的强度。

### 4.1 依赖债务登记被整层 allowlist 抵消

代码注释说：Engine → l2 的债务“只允许具体文件，不允许整层放开”。但当前 `engine` 的 allowed 集合本身包含 `l2/l3/l4/l5`，再叠加五个文件的 debt 特例，见 [architecture_guard.py](../../config/architecture_guard.py#L263-L287)。

**隔离反例实测**：新建一个未登记的 Engine 文件，直接 `from src.orchestration_plane.l2 import something`，`import_violations()` 返回 `[]`。

**影响**：`_DEPENDENCY_DEBT` 的五个文件不能真正限制新增同方向依赖；文档所述的逐文件治理强度高于实际执行强度。

**最小修复**：

1. 目标 allowed 集合与历史债务分开；
2. Engine → l2 只保留已登记文件/模块，新增文件即失败；
3. 债务带 `reason/plan`，并能统计实际命中和偿还；
4. 增加“新文件沿旧方向 import 必须失败”的回归测试。

### 4.2 import cycle 检查只处理第一个环，CLI 放行会提前返回

[cycle_issues()](../../config/architecture_guard.py#L563-L586) 只捕获一次 `CycleError`。如果第一个环全部属于 CLI allow prefix，就直接返回 `[]`，不继续扫描后续环。

**隔离反例实测**：

- 两个独立且未被逐对登记的 CLI 环：结果为 `[]`；
- 同样两个 CLI 环，再加入一个 Engine ↔ Generation 环：只报告该跨平面环，CLI 环仍不可见。

因此“0 cycle issues”应理解为“按当前首次环算法没有报告违规”，而不是已枚举所有 SCC。

**最小修复**：先生成全部 SCC，再逐个判定。CLI 环也不建议按包前缀无限豁免，至少应让 GUI/报告看见允许的环；新增 CLI 环需要逐对登记。

### 4.3 Guard 没有执行自己的 600 行预算

[ARCHITECTURE_GUARD_PRINCIPLES.md](../../docs/architecture/ARCHITECTURE_GUARD_PRINCIPLES.md#L215-L228) 规定 Guard 自身最多 600 行且必须接受同一套检查。

实测 [architecture_guard.py](../../config/architecture_guard.py) 当前 **659 行**，而扫描函数只遍历 `src/`，不包含 Guard 本身。

另外，同一份原则文档 §5.3 还写着 import 环“尚未实现，下一轮”，§12 同时列“已落地”和“尚未实现”，见 [ARCHITECTURE_GUARD_PRINCIPLES.md](../../docs/architecture/ARCHITECTURE_GUARD_PRINCIPLES.md#L150-L153) 与 [同文档实现状态](../../docs/architecture/ARCHITECTURE_GUARD_PRINCIPLES.md#L260-L271)。

**最小修复**：统一规则文档和实现状态；将 Guard 自身纳入同口径检查。若确有行数债务，应正式登记，而不是靠扫描范围豁免；若不保留 600 行约束，则按文档变更程序正式调整。

### 4.4 CI 仍使用迁移前测试路径，Guard 前面的命令就可能失败

[ci.yml](../../.github/workflows/ci.yml#L38-L48) 的 packages job 先执行：

```text
pytest src/tools/checking src/tools/humanview src/layers/l3_decision/contract/tests ...
python -m config.architecture_guard
```

其中前三个目录已经不是当前八平面结构。也就是说，虽然 Guard 已写进 CI，packages job 可能先在旧测试路径处失败，无法走到 Guard。

此外，[.pre-commit-config.yaml](../../.pre-commit-config.yaml) 没有 Guard hook；目前主要应依赖 CI 强制阻断，而不是假定每个开发者本地都运行过。

**建议**：修正 CI 测试路径，并单独保留一个快速、明确的 `architecture-guard` job。无需再以新增架构层次为代价提高覆盖率。

### 4.5 `--root` 对债务命令的隔离语义不完整

CLI 把 `args.root` 传给 `reduce_debt(root)` / `approve_debt(..., root)`，但没有同步传入该 root 下的 budget/baseline/history，见 [architecture_guard.py](../../config/architecture_guard.py#L624-L642)。

**结论**：`--root` 可以改变源码扫描位置，但债务修改默认仍使用当前模块定义的仓库配置路径。不能把 `--root <临时目录>` 当成完整隔离测试手段。本次为验证债务 CLI 使用了 Guard 的临时副本，没有直接对真实配置执行写操作。

建议明确参数契约：要么让 root 同时选择源码与配置，要么给 CLI 提供显式 budget/baseline/history 参数，并拒绝含混组合。

### 4.6 M0 的最小补测范围

现有 [test_architecture_guard.py](../../tests/test_architecture_guard.py) 对尺寸、复杂度、审批和部分 import 方向已有覆盖，但缺少以下 2.1 专项回归：

- 两个以上环必须全部输出；
- `unzoned_file` / `unregistered_zone` 的 CLI 端到端负例；
- 依赖矩阵与真实 import 结果对齐；
- 新文件不能继承旧的 Engine → l2 债务；
- GUI 的失败状态（导入违规、unzoned、line debt）而非只有 OK；
- Guard 自身预算与规则文档状态一致性。

---

## 5. P0：M1 语义判定必须先修的三类 fail-open

### 5.1 未知 relation 拼错后按 UNRESTRICTED 处理，最终可 PASS

[policy.py](../../src/ir_plane/decision/resource_model/policy.py#L21-L23) 对未知策略返回 `conflict=False / requires_checker=False`；这个结果没有被提升为 `validation` 错误。

**实测**：把 `FORBIDDEN_OVERLAP` 改成拼错的 `FORBIDEN_OVERLAP`，两次完全相同地址、禁止重叠的操作最终得到：

```text
status=PASS；conflicts=[]；reason=未知策略 FORBIDEN_OVERLAP，按 UNRESTRICTED 处理
```

**要求**：未知策略必须是 `INCOMPLETE` 或直接 `FAIL`，绝不能按最宽松策略继续签核。

### 5.2 负数/零长度访问不做非法输入处理，最终可 PASS

[AddressRange.valid](../../src/ir_plane/decision/resource_model/address.py#L23-L24) 会识别非法长度，但 `overlap()` 对非法区间直接返回 NONE；[ResourceModel.validate()](../../src/ir_plane/decision/resource_model/model.py#L31-L44) 没有检查这一点。

**实测**：两个操作使用同一地址，但 length 分别为 -1 和 0，仍得到 `PASS`、`validation=[]`。

**要求**：地址为负、长度 ≤ 0、非整数解析失败、granularity 非法等输入属于声明错误，应独立报告，不能转译成“无重叠”。

### 5.3 资源 base/size 没有进入访问合法性校验，越界访问仍可 PASS

Resource 的 `base`、`size` 已声明在 [schema.py](../../src/ir_plane/decision/resource_model/schema.py#L17-L24)，但实际 overlap 只使用 access.address/length 和 address_space，见 [model.py](../../src/ir_plane/decision/resource_model/model.py#L46-L85)。

**实测**：资源声明为 `[0x1000, 0x1100)`，DMA 访问 `[0x9000, 0x9020)`、GEMM 访问 `[0x9100, 0x9120)`，最终得到 `PASS`、`validation=[]`。

**要求**：对声明了边界的资源，访问区间非法或越界必须进入 validation；非法声明不能在没有禁止重叠时被当成 PASS。

### 5.4 必须新增的最小负例矩阵

至少覆盖：未知策略、空/重复 ID、非法地址/长度、整数解析失败、资源内外边界、地址宽度溢出、跨 address space、空 accesses、interaction 自比较、同 owner/异 owner、PARTIAL/FULL/CONTAINED/ADJACENT，以及 malformed YAML/JSON。

**验收标准不是 PASS/FAIL 两列，而是三态语义**：

- 合法输入且所有要求满足 → PASS；
- 有确切禁止事实 → FAIL；
- 输入不完整或没有足够证据裁决 → INCOMPLETE；
- malformed/未知字段/非法数值不得静默降级成“无冲突”。

---

## 6. P0/P1：M1 主链接线的真实边界

### 6.1 当前静态 PASS 混入“尚需运行时 checker”的场景

对 SERIALIZED / ORDERED / DEPENDENT / ARBITRATED_OVERLAP / EXCLUSIVE，策略层返回 `requires_checker=True`。但 [verify_document()](../../src/engine_plane/verify/resource_intent.py#L40-L50) 的最终 PASS 只看 validation、operations/interactions 是否为空、conflicts 和 overflows，**没有消费任何运行时 checker 执行事实**。

因此当前 `PASS` 的准确含义是：

> **声明合法性和静态禁止重叠检查通过；并不表示仲裁、顺序、依赖、互斥已在 RTL 仿真中被证明。**

建议把结果拆成 `static_check` 与 `runtime_check`，或引入明确的 `requires_runtime_evidence`。若声明需要运行时证据，缺少时最终验证状态不能是完整 PASS。

### 6.2 自带 DMA/GEMM PASS 示例无法生成运行时 checker

生成器要求 operation 有已注册的 `agent` 和 `watch.address/watch.length`，见 [resource_checker.py](../../src/generation_plane/uvm_tools/tool_uvm/resource_checker.py#L39-L68)。

仓库的 [resource_intent.yaml](../../examples/open_npu_soc/spec/resource_intent.yaml) 没有这些字段。本次实测：

1. `write_resource_artifacts()` 成功，2 resources / 8 operations / 4 interactions / 4 scenarios；
2. Audit 能读到 `PASS`；
3. `build_checker_plan()` 返回 `{}`。

所以该样例目前证明的是静态声明路径，不是仿真检查闭环。应为受支持的场景补充观测绑定；若某场景不能观测，要显式进入 `INCOMPLETE/unsupported` 统计，而不是平移到“已验证”。

### 6.3 缺失、损坏、不可读当前会被混为“无状态”，并且不产生 caveat

[read_resource_intent_status()](../../src/engine_plane/audit/helpers.py#L1159-L1167) 将不存在、I/O 错误、JSON 解析错误全部返回空字符串；[audit/main.py](../../src/engine_plane/audit/main.py#L163-L169) 将其写成 `MISSING`，而 `resource_intent_ok=True`。

本次实测：空 run 和损坏的 `resource_intent_result.json` 都没有资源 caveat。

**建议的最小语义**：

- 没有资源声明的普通 run：可为 NOT_APPLICABLE；
- 明确声明资源但未产出结果：NOT_RUN / ENGINE_ERROR，应阻断对应资源签核；
- 结果损坏或 hash 不匹配：INVALID，应 fail closed；
- 结果存在但所需 runtime checker 未执行：INCOMPLETE。

不建议把所有 MISSING 一律改成失败，否则会影响没有 Resource IR 的普通项目；应按任务声明与 profile 决定是否 required。

### 6.4 IR 生成失败仍可能静默降级

[write_resource_artifacts()](../../src/engine_plane/verify/ir_artifacts.py#L256-L274) 对 intent 以及资源编译错误只记录 warning，随后可能返回 `available=False`，让后续继续生成。

对“资源声明是本轮必选输入”的任务，这类错误是可签核缺口，不能只是日志。异常应形成结构化错误结果与 evidence，并由 Audit 消费。

### 6.5 Evidence 收集不等于 Evidence 验证

资源 intent 结果已加入 [signoff_package.py](../../src/orchestration_plane/l2/evidence/signoff_package.py#L154-L172) 的 `case_view` 收集列表；而新的 Evidence audit 默认必需 section 只有 inputs/execution，见 [evidence_v2.py](../../src/engine_plane/audit/evidence_v2.py#L23-L34)。

**结论**：存在文件时会被收集，但当前并没有形成“resource intent 声明 → 每场景执行结果 → 对应 checker 输出 → 三态签核”的强约束证据链。对有资源声明的 profile，应定义各自必需证据，不要让全局默认 completeness 掩盖资源场景缺证。

---

## 7. M2：已有的强项与不能提前宣称完成的部分

### 已有强项

[signoff_package.py](../../src/orchestration_plane/l2/evidence/signoff_package.py) 已有真实的文件 SHA-256、package hash、manifest hash 与 Tier-A replay 基础；这些内容比“只写一个 conclusion.json”更有工程价值，应保留并复用。

本次构造证据包还确认：

- 修改被登记文件的内容而不改 manifest，`evidence audit` 能发现 `mismatch` 并返回 FAIL；
- 单份 provenance 的输入 hash 比较可以发现 `old → new` 的差异。

### 7.1 新 `evidence audit` 的 trust 只检查字段“是否存在”

[evaluate_package()](../../src/engine_plane/audit/evidence_v2.py#L73-L86) 只判断 `package_hash / envelope / manifest_hash` 是否 truthy。

**本次反例**：三项分别填入 `not-a-hash / not-signed / not-a-hash`，函数仍返回 `PASS`、`trust.ok=True`；它并没有重算 package/manifest hash。

而现有的 [verify_package()](../../src/orchestration_plane/l2/evidence/signoff_package.py#L785-L817) 已有真实 hash 校验，可复用。

**结论**：新命令可做预筛，但不能单独把 `trust.ok=True` 解释为“证据包可信”。建议收敛到现有真实校验器，而不是维护第二套弱判据。三态字段展示与真实校验可以共享一个入口。

### 7.2 `evidence stale` 不是跨 Run 失效传播

[stale_inputs()](../../src/engine_plane/audit/evidence_v2.py#L101-L126) 比较的是一个 provenance JSONL 与调用者传入的当前 hash 字典。没有run_id和依赖图层面的下游失效传播，也不会自动使其他 Run 的 signoff 失效。

因此 M2 应继续保持“部分实现”。下一步是：输入变化 → 找到受影响 DAG 节点 → 枚举受影响 Run/Claim/Signoff → 标 STALE/INCOMPLETE → 重验后恢复，且整个过程留下 Evidence。

---

## 8. M4：staging 原型存在保护边界绕过

### 8.1 目标文件校验有了，但 staging 根目录不受约束

[validate_proposal()](../../src/agent_plane/specialists/debug/repair_policy.py#L43-L79) 会拒绝目标中的 `..`、绝对路径与保护前缀，这是正确基础。

但 [stage_patch()](../../src/agent_plane/specialists/debug/repair_policy.py#L82-L115) 接受任意 staging_root，只说不能越过 staging 自己，没有禁止 staging 指向项目根或证据目录。CLI 也让调用者直接给出任意路径，见 [cmd_repair.py](../../src/workbench/cli/cmd_repair.py#L46-L66)。

**临时目录实测**：

- 把 project_root 本身作为 staging_root：成功写入 `<项目根>/rtl/dut.sv`；
- 把 `<项目根>/signoff_evidence` 作为 staging_root：成功写入证据目录下的 `rtl/dut.sv`。

这与“只能写 staging，不能写项目根/证据包”的模块承诺不符。

**最小修复**：由系统生成受控 staging，目录在项目外或使用受信任的兄弟目录；拒绝 project_root 及其祖先、项目内保护目录、重解析点逃逸；把 apply 到项目根设计成单独的、人工审批 + 原子替换 + 可回滚动作。

### 8.2 `requires_engine_verification=True` 目前只是记录字段

staging 输出会把这个字段写成 true，但搜索调用点未发现 proposal → Engine 复验 → 受控应用 → Evidence → 经验沉淀的主链消费方。当前 M4 不能称“自动修复已接通”。

---

## 9. 文档状态建议

主里程碑表 [ARCHITECTURE_4.0.md](../../ARCHITECTURE_4.0.md#L678-L689) 当前把 M0/M1/M2 标为 ✅，M3/M4 标为 ◐。本次更准确的建议写法是：

| 项目 | 建议状态 |
|---|---|
| Guard 2.1 | **✅ 核心机制已落地；◐ 测试/CI/自身预算硬化中** |
| Resource / Interaction IR | **◐ 静态骨架已接 DMA/SoC/Audit；签核级语义与 runtime 证据待完成** |
| Evidence v2 | **◐ 单 Run 校验/回放已有基础；跨 Run 失效传播未完成** |
| DMA Autonomous Verification | **◐ 已有四类静态场景；自然语言、执行与真实 checker 结果闭环未完成** |
| Autonomous Recovery | **◐ staging 原型；先修隔离，再接 Engine 复验** |

本次发现的“里程碑提前宣称完成”也说明当前文档一致性测试不够：它检查某些文字存在，并不验证 ✅ 是否满足验收条件。建议里程碑条目链接到验收命令、测试和证据，而不是只更新状态图标。

---

## 10. 建议的执行顺序（不增加新架构）

### A. Guard 2.1 最后固化

1. 修复 §4.1 的债务/allowlist 叠加与 §4.2 的多环算法，添加负例；
2. 修正 CI 路径，让 Guard 在每个必过 job 中实际执行；
3. 处理 Guard 自身 659 行与 600 行规则的矛盾，更新过时文档；
4. 完成后保留当前通过项：**CLI、GUI、114 条定向测试、单向债务棘轮**。

### B. 继续 M1，但收敛到签核语义和证据，不再铺新模块

1. Resource Model 输入 fail closed，修复 §5 的反例并补测试；
2. 明确 `static PASS` 与 `runtime PASS`；需要 checker 的 relation 缺执行证据时不得给完整 PASS；
3. 区分 NOT_APPLICABLE / NOT_RUN / INVALID / INCOMPLETE；不再把损坏和缺失都当空状态；
4. 给一个最小 DMA/GEMM 场景补齐 `agent/watch`，真正生成 checker，并保存 seed、仿真输出、判定依据与签核关联；
5. 对确实不支持观测/执行的场景明确报 INCOMPLETE，不把 unsupported 隐藏掉。

### C. M2 收敛验证器，M4 先修边界

- M2：复用现有真实 package hash 校验，再实现跨 Run STALE 传播；
- M4：修 staging root 隔离，然后才接 apply、Engine 重验、重试上限和人工门。

**完成 A、B 的最小闭环后，再谈“自主验证能力进入主链”。当前不需要 Architecture 5.0，也不需要新的目录迁移。**

---

## 11. 验证边界与复现

### 本次没有做的事

- 未运行 1249 条全量单测，因此不能说原有 CLI/GUI/业务完全无回归；
- 未跑 Questa/VCS/Verilator 或真实 RTL 仿真；
- 未调用 LLM，未验证自然语言到 IR 的自动抽取；
- 未在主窗口做手工视觉与交互验收，只做了 GUI 页面离屏实例化；
- 未针对真实仓库预算执行 approve/reduce 写操作；债务行为在 Guard 临时副本中验证；
- 未启动远程 GitHub Actions，CI 结论来自路径与 job 顺序静态检查。

### 主要复现命令

```powershell
python -m config.architecture_guard
python -m src.workbench.cli.commands arch check
python -m src.workbench.cli.commands arch planes
python -m src.workbench.cli.commands arch matrix --json
python -m src.workbench.cli.commands resource verify examples/open_npu_soc/spec/resource_intent.yaml
python -m src.workbench.cli.commands resource verify examples/open_npu_soc/spec/dma_gemm_conflict.yaml

python -m pytest tests/test_architecture_guard.py tests/test_workbench_planes.py -q
python -m pytest tests/test_architecture_invariants.py -q
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest src/workbench/tests/test_flow_views_module.py src/workbench/tests/test_workbench_manifest.py src/workbench/tests/test_workbench_registry.py -q
```

反例均通过临时目录构造：未向仓库提交夹具、PATCH 或新架构代码。

---

## 最终评审签字口径

**建议结论：有条件认可架构方向，拒绝把当前状态解释为 M1/M2 已完整完成。**

- 可以确认：现代码已经有真实可运行的 Guard 2.1、CLI/GUI 展示、审批式债务增长、只减不增的偿还机制，以及 Resource/Interaction 的确定性静态计算与主链接线。
- 必须保留：Guard 整体回归与 CI 还需硬化；资源 intent 的 PASS 当前不能代表运行时 DMA 验证通过；跨 Run Evidence 失效传播与受控自动修复尚未成立。
- 下一步应围绕“**正确判定、真实执行、可追溯证据**”收尾，而不是继续增加抽象、目录或 Agent 数量。
