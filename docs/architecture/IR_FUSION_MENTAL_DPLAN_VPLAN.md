# 融合优化 IR：Mental + DPlan + VPlan

> 状态：**设计方案 / 兼容投影提案**，不是已经落地的转换器、运行产物或签核结果。
>
> 核心结论：采用 **一个项目作用域的对象图 + 三种权威投影 + 可追溯关系边**，而不是叠加成一份互相覆盖的大 JSON。复用现有 Mental、DPlan、VPlan 契约，不另增职责平面；Execution 和 Evidence 保持独立。

## 1. 为什么要融合，以及不能融合什么

| IR | 它回答的问题 | 现有核心内容 | 不被替代的职责 |
|---|---|---|---|
| Mental IR | 对需求的理解是什么？不确定点是什么？ | goals、assumptions、ambiguities、verification_intents、risks | 它是候选理解，不是执行事实或签核证据 |
| DPlan | 怎样实现 RTL/参考模型？ | interfaces、registers、features、architecture、modules、model_contract | 它是实现与模型契约，不是验证通过记录 |
| VPlan | 要验证什么？如何组织检查？ | requirements、features、contracts、testpoints、cases | 保留计划、契约与用例的状态；不能因融合变成 covered |

**Mental 提供意图，DPlan 提供实现锚点，VPlan 提供验证义务。** 后两者能相互关联，但不能相互证明。即使 DPlan feature、VPlan requirement 和验证用例相等，也仍然只构成候选关联，需要 Engine 或人工复核。

## 2. 本次实际吸收的输入与限制

### 2.1 Mental 样例

已读取 [demo.json](../../src/mental_ir_plane/example/demo.json)。

- `top_module_name = sync_fifo`，根对象 id 为 `5b0f21ab-4f14-4ee9-87d5-04ecd8539199`。
- 本文件字节 SHA-256：
  `63af7b74b9dcdce7d561af7918e169f43504abaea5b18d23a7bb00e95bfece2e`。
- 有端口、参数、内部信号、基本功能、corner case 和错误场景等描述。
- **没有 `schema_version` 字段，它不是当前 `mental_ir_v1` 的直接实例**；不能假装原样通过本仓库的 `MentalIR.model_validate()`。

本仓库的 [Mental IR 模型](../../src/mental_ir_plane/model.py#L87-L199)规范则是 `goals / assumptions / ambiguities / verification_intents / risks`。其 `digest()` 排除 `generated_at / generator`，对稳定内容的规范 JSON 取哈希。融合层应复用这类溯源思想，而不是迁移旧字段名后宣称升级完成。

### 2.2 DPlan 样例

已读取 [npu_sched_dplan.json](../../specs/npu_sched/docs/specs/npu_sched_dplan.json)。

- `design_name = npu_sched`，`version = "1.0"`，文件 SHA-256：
  `2545908cae43fc3c601d56d2490e92482605792e192b502a82effb498c866018`。
- 顶层有 design/interfaces/features/architecture/modules/model_contract；也有 requirements/contracts/testpoints/cases 等近似 VPlan 的集合。
- 接口 328 个，设计 features 43 个。
- `model_contract` 包含 `module / ports / state / behaviors / scoreboard`；其中 `behaviors` 当前为空数组，**不可补造行为证明**。
- 文件能按 UTF-8 解码，但存在 3 个 U+FFFD 以及多处疑似双重编码/乱码描述。保留原始快照，从可读原始输入恢复或人工审阅，不猜修中文。
- `version="1.0"` 和对齐输出的 `schema="dplan_map_v1"` 是两个概念，不应混写为“原始 DPlan 也已经有完整统一 schema”。

当前 [dplan 对齐](../../src/ir_plane/decision/dplan.py#L165-L195)的主要产物是 `dplan_map_v1`：features/modules/behaviors 与 VPlan feature、requirement、contract、testpoint 的映射和缺口。这正好是融合 IR 的关系边来源，而不是应丢弃的历史数据。

### 2.3 VPlan 样例

通过现有 [`load_project()`](../../src/ir_plane/vplan/source.py#L225-L278)以默认 `allow_spec_drift=False` 读取了当前 NPU 项目：

| 对象 | 实际数量/状态 |
|---|---|
| Requirements | 26 |
| Features | 43 |
| Contracts | 46，全部为 `assume` |
| Testpoints | 58，全部为 `planned` |
| Cases | 20，全部为 `planned` |
| Project warnings | 0 |

源 spec 为 [npu_sched.md](../../specs/npu_sched/docs/specs/npu_sched.md)，其实际 hash 与 metadata 一致：`04f6c9293643f9fcdbe668618e4b2d9f0d94ea6c5ce75276e0d8816ab51c0436`。

这不等于 VPlan 已验证硬件：“哈希/引用检查通过”只说明本次输入可被装载；[spec_meta](../../specs/npu_sched/docs/specs/npu_sched_spec_meta.json)仍注明 LLM bootstrap、需要人工评审。契约矩阵的 `assume` 更加不能被自动升格为 `active`。例如 [复位契约](../../specs/npu_sched/data/contract_matrix/res.csv)的检查来源和 `assume` 必须原样保留。

## 3. 当前数据暴露的真实问题

### 3.1 Mental demo 不能无损静默升级

1. **截断文本**：顶层描述结束于 `between a producer and a c`，clock、reset 等描述也存在截断。不能自行续写为 consumer、clock domain 或其他词。
2. **重复 id 但内容不同**：`module_basic_functionalities.sync_fifo[0]` 和 `basic_functionality[0]` 使用同一个功能 id，但规范化记录不完全相等。不得直接覆盖、去重或 double count。
3. **未定义绑定**：`signals_to_channels` 和 `channels_to_transactions` 是 `INVALID_KEY_PLACEHOLDER`，必须视为未解析，不是空列表，也不是已经有 channel model。
4. **来源不完整**：有 corner case 的某个 RTL 引用只有 `line_range="46-61"`，没有 `source_file`；不能仅根据描述猜它必然来自某个文件。
5. **历史绝对路径**：`/work/home/jqliu/cad_ai_demo/sync_fifo_demo/rtl/sync_fifo.sv` 是历史外机引用。本次扫描未找到可供本地复核的 `sync_fifo.sv` 或 `sync_fifo_spec.md`，因此不把行范围当成已验证锚点，也不擅自读取外机路径。
6. **参数语义待复核**：参数的 `kind="mealy"`、`category="4"` 不应未经审阅自动转成状态机类型或优先级。`DATA_W`、`DEPTH` 等宽度需保留为符号，而非填入猜到的数值。

### 3.2 DPlan 与 VPlan 已有重叠，但不是同一份权威数据

DPlan 文件本身含 requirements、contracts、testpoints、cases 等集合。其中 testpoints 为 46 个，而当前 VPlan 输入为 58 个。它至少包含部分 VPlan-like 数据或旧侧影，**不能作为当前 VPlan 项目的完整替代**。

两处的 feature id 集合均为 43 个且相同；这是建立显式关联的好线索，但同 ID 不等于内容、来源、修订版或覆盖状态都已被校验一致。

因此，融合需要同时保留：

- DPlan 非重叠的设计与模型内容；
- DPlan 中可复用但需对照的“嵌入 VPlan 视图”；
- 当前 VPlan 权威 spec、CSV、契约矩阵和 review/hash 信息；
- 原始对象身份、内容指纹以及不一致的原因。

不能把 DPlan 的嵌入数组当成已经融合过了，就再合并一次来加倍计数。

### 3.3 对齐分数不能变成验证覆盖

当前 DPlan mapper 支持确定性 token 匹配，阈值 `_THRESHOLD = 0.35`。该分数是候选相似度指标，**不是“35% 正确率”、概率或证据**。

另一个值得优化的含义问题是 `coverage.modules_mapped` 的缺省读数：当前 markdown 视图在字段缺席时用 0 展示，但 mapper 的 `coverage` 主要计算 features/behaviors 等映射。对未计算的模块对齐数，融合 IR 应写 `NOT_COMPUTED`，不能用 0 冒充已测量的真实零覆盖。

VPlan 的 warnings=0 只说明现有引用检查没有告警，也不能代替内容审查或实际运行。

## 4. 推荐的融合结构

```text
unified_ir_v1 / logical_project
│
├── artifacts：原始 Mental / DPlan / VPlan / CSV / Spec / Manifest 快照
├── entities：项目作用域内的设计、理解和验证对象
├── relations：显式引用、候选对齐、冲突、人工确认、实际证据等类型化关系
├── gaps：缺输入、冲突、乱码、模糊和待定后端
└── views / projections
    ├── Mental view：Goals / Assumptions / Ambiguities / Intents / Risks
    ├── DPlan view：Interfaces / Modules / Registers / Features / Model
    └── VPlan view：Requirements / Contracts / Testpoints / Cases

Execution / Evidence
    └── 另行记录“真跑过什么、由什么引擎、得到什么结果”
```

### 4.1 为什么是“对象图 + 投影”，不是三个大对象相加

- 例如 reset、写阻塞、FIFO occupancy 可以是一个关联图的多个节点，但各自保留来源和不同视图中的角色。
- 同名 `feature`、`interface`、`behavior` 不能首先按名字合并；先识别其所属项目与类别，再考虑同义关系。
- Mental 观点可以引用某个 DPlan 功能，VPlan requirement 可以覆盖某个测试义务；关系被单独审查，不会覆盖原来的内容或状态。
- 融合文件是可重建的逻辑投影，**不是四种 IR 的总签核表**。

## 5. 根包络（Envelope）

建议的统一根对象如下。字段用于设计收敛和后续实现，非当前仓库已承诺的 schema：

| 字段 | 必要内容 | 优化点 |
|---|---|---|
| `schema` | `unified_design_verification_ir_v1`（建议名） | 显式标识融合格式；不冒充旧 `mental_ir_v1` |
| `mode` | `logical_projection` / `import_only` / `reviewed_projection` | 清楚表明是导入草稿还是经审阅的投影 |
| `project` | `project_id`、`top_module`、`design_name`、`revision` | 项目命名空间必须统一后才允许对齐 |
| `profiles` | 每种输入的原始类型、版本、loader、byte hash | 分离 DPlan 原始 `version`、Mental schema、map schema |
| `artifacts` | 原始文件/快照的定位、字节 hash、状态、计数 | 不丢失原始来源；不要求所有输入是 JSON |
| `entities` | 规范化对象及其原始 locator、内容指纹、角色 | 去重前先核验 key 与内容 |
| `relations` | 多个有类型的边及其确定性依据、候选状态 | 支持多对多，保留未映射项 |
| `issues` | 单项问题与所需补救；`blocking` 由规则决定 | 问题不被隐藏在 notes 里 |
| `semantic_digest` | 规范化稳定内容的 sha256 | 回答“引用的是哪个语义版本” |
| `build_metadata` | 生成时间、loader/版本、工具信息 | 不进入 semantic digest |
| `execution_refs` | Execution/Evidence 的外部引用 | 不把计划状态和执行结论混为一体 |

### 5.1 项目边界是第一道门

`project_id` 应是经过审阅的稳定项目身份；`sync_fifo` 和 `npu_sched` 必须分开。若要把它们放进同一个研究集合，也只能是 `project_group → member_project` 的容器关系。

禁止仅凭 `Reset`、`FIFO`、`clk` 等自然语言或端口名称做跨项目 purpose/meaning 配对。跨项目相似点最多是 `similarity_candidate`，并附各自 project scope 和待复核标记。

## 6. 对象身份与去重规则

### 6.1 创建稳定但可解释的身份

建议 `EntityKey` 至少包含：

```text
(project_id, entity_type, native_id, revision)
```

- `entity_type` 推荐枚举：`module`、`port`、`register`、`parameter`、`feature`、`behavior`、`model_state`、`goal`、`assumption`、`ambiguity`、`requirement`、`contract`、`testpoint`、`case`、`artifact`、`issue`。
- `native_id` 优先沿用原项目提供的 `req_id`、`contract_id`、`tp_id`、`case_id`、`feature_id`、mental id 等；不要一律重新生成 UUID 丢失原引用关系。
- `revision` 由稳定内容指纹或既有版本链决定。若语义改变，则新增对象或新 revision，并用 `supersedes` 指向旧版本。
- 可以额外保存人读的 `semantic_alias`（例如 `reset`、`full_backpressure`），但它是标签/别名，不能替代唯一身份，更不能未经评审绑定语义。

### 6.2 精确归一化与“相似但不相同”

| 情况 | 处理 |
|---|---|
| 同项目、同类、同 id、规范化内容完全一致 | 可以归为一个规范节点，并保留多个原始 locator |
| 同 id，但描述/结构不一致 | 保留两个原始记录，进入 `CONFLICT_REQUIRES_REVIEW`；不静默覆盖 |
| ID 只是写法规格不同 | 依据明确的 alias/normalization 规则生成关联，保留 raw id |
| 仅意义或 token 相似 | `similarity_candidate`，不能自动合并为同一 feature |
| 已有需求、契约、用例 ID | 结构化引用优先于模糊相似度 |

Mental demo 的重复功能记录适用第二条。去重目标是消除重复存储，而不能通过 lossy 内容指纹抹去描述差异。

## 7. 统一的来源和哈希层

### 7.1 一个 Artifact 记录两种不同 hash

| 名称 | 覆盖内容 | 用途 |
|---|---|---|
| `bytes_sha256` | 原始文件实际字节 | 判断是否读取了同一份 JSON/CSV/spec；保留既有 EOL/编码证据 |
| `semantic_digest` | 融合对象的稳定规范化内容 | 在换行、键顺序、生成时间等非语义变化中比较逻辑版本 |

`semantic_digest` 推荐以明确 UTF-8 规范 JSON、稳定 key 顺序计算；明确哪些字段排除，如 `generated_at / generator / build_metadata`。文件级 byte hash 与规范 semantic digest 不得混为同一个值，也不得在某处静默换用算法。

### 7.2 来源引用按类型区分

`ArtifactRef` 至少由 locator、role、status、bytes_sha256、source_profile 组成。每个派生对象还应包含 `legacy_locator`（例如 JSON Pointer、CSV 行号或文本片段）；参数、字段缺失则显式记录。

`SourceAnchor` 应能区分：

- `file`（受限工作区内文件）；
- `spec_section`（如 VPlan 的 `2.1.5/10.1`）；
- `text_span` / `literal_quote`；
- `legacy_external_reference`（尚未重绑地的历史路径）；
- `relationship`、`model_node`、`artifact`；
- 待确定的 `unknown`。

VPlan 中的章节号 `/` 不应直接当路径分隔符。Mental 样例中的 `text_anchor` 外层引号或裸文本应该原样保存；只有实际重绑和校验时才能匹配段落并补 hash。缺失 quote/行号/hash 部分是缺口，不能伪装成强来源。

### 7.3 导入优先级

1. 对原始 artifact 计算并保存 hash。
2. 用受信 loader 解析；不把内容当代码执行，不对 SV 表达式 `eval`。
3. 进行缺文件、文本完整性、ID 唯一性、引用完整性、编码与宽度结构的检查。
4. 建立对象和关系；将不可自动消解的问题写入 `issues`。
5. 处理阻断级问题，再决定是否允许把候选意图投入 Execution；**投影本身不能自动变 PASS**。

## 8. 三种投影的精确映射

### 8.1 Mental → unified Mental / design annotations

| 原字段 | 建议去向 | 不可自动做的事情 |
|---|---|---|
| `module_basic_functionalities` / `basic_functionality` | feature 的 legacy claims 与不同视图引用 | 相同 id 即合并；发现内容不同必须报告 |
| `clock_ports/reset_ports` | 有来源的 clock/reset 接口描述和待核对意图 | 截断文本补全、把描述当已验证硬件行为 |
| `input_ports/output_ports` | 候选 `port` + `direction` + `type_qualifiers` + `width_expr` | 从 `input wire logic [DATA_W-1:0]` 中猜位宽；覆盖 DPlan 接口 |
| `corner_case_functionality` | `behavior` / `corner_condition` 的来源描述；可建议 verification intent | 直接生成已通过 case/SVA/SCB |
| `error_scenarios` | 错误检测/恢复协议主张及关联风险 | 把异常分类或修复建议当已检查结果 |
| `design_parameters` | 参数及原始表达式、来源与 alias | 把派生 `ADDR_W`、`CNT_W` 解析成未经核实的固定值 |
| `relevant_files.top_file` | `legacy_external_reference` | 用旧 Linux 路径证明本仓库存在该 RTL |
| `INVALID_KEY_PLACEHOLDER` | 明确的 `UNRESOLVED_BINDING` 问题 | 转成空数组或空 channel 关联 |

对当前 `mental_ir_v1`，必须保留其 goals、assumptions、ambiguities、verification_intents、risks 以及 ID 唯一性。新增端口/行为注解只能是有来源的辅助视图，不能塞入 `goals` 冒充验证目标已成立。

### 8.2 DPlan → design / model 视图

| DPlan 内容 | 统一对象/关系 |
|---|---|
| `design_name / version / overview` | Project identity、原始 profile、文本来源 |
| `interfaces` 与 modules 的 interfaces | port/interface 实体；保留 module、level、protocol、width 表达式 |
| `registers` | register/field 实体，不与普通 port 混为一类 |
| `architecture / modules` | 模块、层级和实现方法边界 |
| `features` | 实现功能实体；与 VPlan feature 作明确或候选映射 |
| `model_contract.ports` | 参考模型接口，避免将其误当 RTL 同一物理端口的证明 |
| `model_contract.state` | model state 实体，保留名称和描述，需处理乱码问题 |
| `model_contract.behaviors` | 模型行为候选；为空时保留为空，不自行补写 |
| `scoreboard` | 模型检查机制描述；不自动等同于执行过的 SCB |
| requirements/contracts/testpoints/cases 的嵌入部分 | 标成 embedded VPlan-like projection，与 VPlan 原始权威输入逐项对照 |

> `data_width` 若是可证明的整数则保留整数；如果是参数表达式，则保留 `width_expr` 并将 `numeric_width` 记为未解析。不能把 `DATA_W`、`DEPTH`、`$clog2(DEPTH)` 强行降为默认值 1。

### 8.3 VPlan → Verification 视图

- `requirements.csv`：保留 `req_id`、spec section、description、`feature_ids`、priority。
- `features.csv`：保留 feature 树、`parent_feature_id` 与层级路径。
- `contracts.csv` + `data/contract_matrix/*.csv`：矩阵必须有既定的 13 列，`status ∈ {assume,active,exempt}`。只可用候选注释补充缺失信息，不以候选内容覆盖矩阵权威字段。
- `testpoints.csv`：保留 tp、feature、contract、刺激、预期、检查方法、case_plan 和状态。
- `cases.csv` / `case_ir_v1`：保留 case、feats（契约引用位）、checks、SVA/SCB/group 及 `not_applicable`。
- `Checker` 是一种单独的检查类型，不能放进 SVA 计数。`unmodeled_checks` 必须留下，保证“未建模”不是“已经检查”。

参考 [Case IR 的生成](../../src/ir_plane/vplan/build.py#L204-L283)：计划状态、未建模检查和绑定结构应分别保留。融合层宣传统一字段时不得丢失这些已有语义。

## 9. 关系边与覆盖含义

统一关系至少记录：

| 字段 | 含义 |
|---|---|
| `source` / `target` | 创建、验证的实体引用；禁止指向不存在的节点 |
| `predicate` | `describes`、`implements`、`verifies`、`depends_on`、`suggests`、`conflicts_with`、`evidenced_by` 等 |
| `method` | `explicit_reference`、`normalized_id`、`token_similarity`、`human_confirmation`、`engine_evidence` |
| `method_detail` | matcher/version、候选得分、对应的 source locator |
| `review_state` | `CANDIDATE`、`ACCEPTED`、`REJECTED`、`REQUIRES_HUMAN` 等边状态 |
| `origin` | 哪个来源或真实动作产生这条边 |

### 9.1 覆盖只统计被允许的语义

必须至少分开：

- `confirmed_links`：显式 ID 或人工确认的结构化关联；
- `candidate_links`：token/模型产生的建议，尚无确认；
- `unmapped_design_features`；
- `unmapped_verification_requirements`；
- `not_computed_dimensions`；
- 真正的执行/证据覆盖（由 Engine 另行计算）。

不能仅因 `token score >= 0.35` 就把映射纳入 confirmed。建议边、核实边和实际证据边的统计口径要分开。对于实际执行覆盖率，应使用真实 Engine 输入和记录，而不是根据 feature 数量大约估算百分比。

## 10. 一个经过约束的 sync_fifo 示例

以下是**融合结构的示意投影**，不是自动转换后的活着的 IR，也不是 sync_fifo 的 DPlan、VPlan 或测试完成证明。`npu_sched` 的 DPlan/VPlan 应另建独立项目，不能把 demo 的 feature 直接挂到它上面。

```json
{
  "schema": "unified_design_verification_ir_v1",
  "mode": "import_only",
  "project": {
    "project_id": "sync_fifo",
    "top_module": "sync_fifo",
    "revision": "legacy_projection_draft"
  },
  "profiles": {
    "mental_demo": {
      "input_kind": "legacy_mental_description",
      "artifact_ref": "artifact:mental_demo",
      "original_schema": null
    }
  },
  "artifacts": {
    "artifact:mental_demo": {
      "locator": "src/mental_ir_plane/example/demo.json",
      "bytes_sha256": "63af7b74b9dcdce7d561af7918e169f43504abaea5b18d23a7bb00e95bfece2e",
      "status": "OBSERVED"
    }
  },
  "facets": {
    "mental": {
      "feature_claims": [
        {
          "legacy_id": "81b2391a-c49c-4e99-b308-df3478216db4",
          "merge_status": "CONFLICT_REQUIRES_REVIEW",
          "legacy_locators": [
            "/module_basic_functionalities/sync_fifo/0",
            "/basic_functionality/0"
          ]
        }
      ]
    },
    "design": {
      "interfaces": [
        {
          "id": "wr_en",
          "kind": "port",
          "direction": "input",
          "type_qualifiers": ["wire", "logic"],
          "width_expr": "1",
          "source_id": "4db27caf-353d-45bf-a3c3-0d2b948c08a2",
          "source_locator": "/input_ports/0"
        }
      ],
      "model_contract": null
    },
    "verification": {
      "status": "NO_VPLAN_INPUT",
      "requirements": [],
      "contracts": [],
      "testpoints": [],
      "cases": []
    }
  },
  "issues": [
    {
      "code": "TRUNCATED_LEGACY_TEXT",
      "severity": "error",
      "blocking_for_promotion": true,
      "resolution": "提供原始完整描述，不能自动续写"
    },
    {
      "code": "UNRESOLVED_BINDING",
      "fields": ["signals_to_channels", "channels_to_transactions"],
      "blocking_for_promotion": true
    },
    {
      "code": "UNBOUND_RTL_AND_SPEC",
      "blocking_for_promotion": true,
      "resolution": "重新绑定并核验实际 sync_fifo.sv / sync_fifo_spec.md"
    }
  ],
  "verification_state": {
    "engine_executed": false,
    "coverage_evaluated": false,
    "status": "CANDIDATE_IMPORT"
  }
}
```

**示例里特别值得保留的取舍：**

- Mental 的重复功能没有被强行合并，原始两个 locator 都被保留。
- `wr_en` 的端口方向、类型及原始 id 可提取，但描述中的信号时序尚无 RTL 核验。
- 未知 `model_contract` 使用空值表示未提供，而非伪造空行为证明。
- VPlan 缺失通过状态与问题体现，不把空数组解释成“这个硬件已经无需验证”。
- 原始描述即使有 corner-case 文字，也不能替代已被 VPlan 声明的 `tp_id` 或 `case_id`。

## 11. 审查、阻断与证据闭环

### 11.1 建议保留多个正交状态

| 维度 | 含义 | 示例 |
|---|---|---|
| 来源状态 | 文件/输入是否可装载、哈希是否相符 | `OBSERVED`、`HASH_VALIDATED`、`STALE`、`MISSING` |
| 内容可信度 | 声明、推断、还是已审阅 | `DECLARED`、`INFERRED`、`REVIEWED` |
| 映射状态 | 明确关联、候选、冲突或人工接受 | `EXPLICIT`、`CANDIDATE`、`CONFLICTED`、`ACCEPTED` |
| 计划状态 | 原始 VPlan 状态 | `assume`、`active`、`exempt`、`planned` |
| 行为状态 | 真正执行后的 Engine 证据 | 由实际运行记录决定，不由合并器自行设置 |

### 11.2 阻断条件

至少以下情况不能进入“正式候选执行包”：

- 无法在原 project 中解析 project scope；
- 未解决的 dangling reference 或强制 schema 错误；
- 内容冲突、关键描述截断、缺乏必要的原始可读输入；
- spec 或 artifact hash 不匹配；
- 未经审查就把 token 匹配当确定语义映射；
- 将 `assume/planned` 改写为 `active/covered`，但没有对应的审查或 Engine 证据；
- 写入/生成路径超出允许的工作区/输出区。

轻微提示可以保留在 issue 中，但阻断问题不能被“模型给出了答案”自动豁免。对 demo 先允许 `import_only` 导入，修复问题后再评审提升。

### 11.3 执行与证据的关系

融合的产出是**有来源的设计/验证逻辑图**。然后才可:

1. 依据已审阅的 DPlan/Model 约束构造实现候选；
2. 依据有明确引用的 VPlan contract/TP/case 生成验证资产；
3. 在真实 Engine 或人工审查后写回 Execution/Evidence 引用；
4. 保存当时的 `semantic_digest`、source hashes、review/plan 状态和执行 ids，使以后可以定位过期原因。

只有第 3 步的真实证据才能改变相应执行覆盖与签核结论。

## 12. 性能与存储优化：少存重复，不少存来源

针对 Mental demo 的重复功能，以及 DPlan 与 VPlan 的重叠部分，推荐采用：

1. 规范键 — 原始 locator — 内容指纹三层索引，而不是依赖名称匹配。
2. 原始 artifact 保存一次；规范和视图通过引用取回局部内容。
3. 对**完全相同**的对象去重，对相同 id、不同内容的实体建立冲突边，绝不因体积去重丢证据。
4. 生成时保存小型的 graph/index，超大的原始 spec、CSV 和模型 payload 仅保存必要投影，不必每次复制全量描述。
5. 使用版本链和改动片段记录审阅历史，避免人工 CSV 修改后无依据地覆盖前一版本。
6. 对外部执行、引擎日志保持 artifact 引用，不把展开波形或大段日志重复嵌入统一 IR 根对象。

这不是单纯为了缩小 JSON；**保留可复现性、引用稳定性与审阅差异比压缩体积更重要**。

## 13. 建议的迁移步骤

1. **保留当前输入和格式**：继续使用现存 Mental、DPlan/VPlan loader、CSV/contract matrix 和 map，不改写原始权威文件。
2. **建立受限的 legacy adapter**：优先支持本页提到的 demo 与 NPU 数据的实际结构，保留未知字段和原始 locator，不要宣称泛化支持所有历史 IR。
3. **先导入-only，不升格状态**：产生 draft entities/issues/source refs，阻止文本补全和随意“修编码”。
4. **对 same-project 的两份数据做对照**：feature/req/contract/tp/case ID、内容与字节 hash 分开比对，记录嵌入视图是相同、子集、陈旧还是冲突。
5. **补关系审查与问题处理**：明确哪些属于实现意图，哪些属于验证义务；映射建议单独审查，计数以确认状态计算。
6. **在兼容投影稳定后新增输出**：建议放独立的暂存 `contract/coherent_ir.json`，不覆盖原 `dplan_map.json`、Case IR、契约矩阵或团队既有产物。
7. **最后才接 Execution/Evidence**：保持真实工具/审核结果只读追加，避免合并器反向修改 Engine 状态。

后续真正实现时，可复用 `src/mental_ir_plane` 的 SourceAnchor/canonical hash 经验、`src/ir_plane/vplan/source.py` 的哈希和引用校验，以及 `src/ir_plane/decision/dplan.py` 的对齐 view。这里只建议可复用接口，不复制这些模块的另一份业务实现，也不新增第十个 Plane。

## 14. 本方案的最低验收清单

若要把这份设计实现成代码，至少应有下面的确定性检查：

- 所有生成 entity id 在项目内唯一，且所有关系引用可解析。
- `sync_fifo` 描述截断和缺源问题会显式暴露，不能被静默忽略。
- 重复 id、不同内容的多视图记录不会被无损宣称“已合并”。
- `INVALID_KEY_PLACEHOLDER` 会成为阻断/缺口，而不是空 channel 数据。
- 项目间不会误绑 `sync_fifo` 与 `npu_sched`。
- DPlan 原始 `version`、物质文件 byte hash 和融合 semantic digest 各自有独立含义。
- 数据宽度为表达式时不强制填 1；无法判断的语义归为未确定。
- VPlan `assume/planned` 状态能够在导入、映射和审计中保持不变。
- 候选 token 对齐与人工确认/实际 Engine 证据在统计中分离。
- 未计算指标为 `NOT_COMPUTED`，不是随意填充的 0。
- 没有提供 SVA/SCB 时显示其未建模；Checker 和 SVA/SCB 分类不混淆。
- 缺真实 RTL/spec/仿真或形式引擎时，相应结论仍为 `INCOMPLETE` 或 `NOT_RUN`。

## 15. 总结

这套融合不是把 Mental、DPlan、VPlan 改写成一个巨大字段集合，而是建立：

> **同项目、可溯源的设计/验证对象图，以及 Mental 理解视图、DPlan 实现视图、VPlan 验证视图。**

最重要的收益在于：

- 共享对象可以复用，但来源、冲突与权威不丢；
- 不同 IR 的身份、状态和哈希含义不再混淆；
- 同项目内可以做显式映射与去重，候选推断不会被当成执行证据；
- 生成器可以生成下一步意图，但只有受控检查或真实运行才能提升证据状态。

因此它适合作为后续统一 IR 的设计基础，而不是把当前样例直接标成“融合成功”。
