# SignOffAI 数据库设计与业务逻辑优化建议

## 1. 目标

当前项目已经具备较完整的“AI 验证平台”骨架，数据库层面也已经覆盖了用户、项目、审计、签核、文档和流水线等核心对象。  
但从企业级落地和产品化角度看，当前设计还偏“原型化”，建议进一步把它升级为“可审计、可追踪、可审批、可扩展”的签核平台数据模型。

---

## 2. 当前问题

当前数据库设计中，存在以下几个主要问题：

1. 签核流程状态过于松散
   - 目前签核只依赖 `status` 字段字符串来表达状态。
   - 业务上存在“谁审批了、为什么审批、审批过程是否完整”等信息缺失的问题。

2. 审计日志过于通用
   - `AuditLog` 可以记录动作，但它更像“系统事件流”，而不是“业务证据流”。
   - 未来要做合规审计、责任追踪、流程回溯时，单表审计日志不够结构化。

3. JSON 字段使用过多
   - `summary_json`、`phases_json`、`results_json` 等字段灵活，但容易变成“无结构黑盒”。
   - 这会带来后续查询、报表、筛选和性能问题。

4. 证据链与签核对象没有形成强绑定
   - 当前主要靠 manifest / evidence 文件路径和 hash 进行间接关联。
   - 但从业务上看，证据应当明确属于某次签核、某次流水线、某个项目版本。

5. 业务主键与索引还不够完整
   - 需要补齐关键联合唯一约束和索引，保证多项目、多成员、多版本场景下稳定运行。

---

## 3. 建议的数据库演进方案

### 3.1 建立“业务对象 + 事件流”双轨模型

建议把数据库分成两层：

- 业务对象层：用于承载核心实体，如 `Project`、`User`、`Signoff`、`PipelineRun`、`DocDocument`
- 事件流层：用于记录所有关键动作，如审批、回退、版本创建、证据导出、文档修改

这样做的好处是：
- 业务对象负责“当前状态”
- 事件流负责“变化历史”

这非常适合做签核平台，因为签核本质上就是“状态变化 + 证据留痕”。

---

## 4. 推荐新增表结构

### 4.1 签核审批历史表：`signoff_events`

作用：记录每一次签核变更过程。

字段建议：

- `id`
- `signoff_id`：关联签核记录
- `event_type`：如 `submitted`、`approved`、`rejected`、`commented`、`reopened`
- `actor_id`：执行动作的用户
- `actor_name`
- `comment`
- `created_at`

说明：
- 通过这张表可以明确“谁在什么时间审批了什么”
- 后续可做审批轨迹、责任追踪、回溯审查

---

### 4.2 证据对象表：`artifacts`

作用：记录每一个证据产物或文件。

字段建议：

- `id`
- `project_id`
- `run_id`：关联流水线 run
- `signoff_id`：可为空
- `artifact_type`：如 `manifest`、`report`、`coverage`、`log`、`doc`
- `name`
- `path`
- `content_hash`
- `size_bytes`
- `created_at`

说明：
- 证据不是“文件路径字符串”就完了，而是要变成一个数据库对象
- 后续可做证据包生成、完整性校验、追溯查询

---

### 4.3 证据关联表：`evidence_links`

作用：把证据和业务对象绑定起来。

字段建议：

- `id`
- `artifact_id`
- `object_type`：如 `signoff`、`pipeline_run`、`doc_document`
- `object_id`
- `relation_type`：如 `attached_to`、`generated_by`、`referenced_by`
- `created_at`

说明：
- 这张表是把“证据链”真正落地到数据库的关键
- 以后可以很容易查询“某次签核关联了哪些 artifact”

---

### 4.4 文档版本表：保留并增强

当前 `DocVersion` 已经是对的，但建议补充以下字段：

- `author_id`
- `change_summary`
- `created_at`
- `parent_version_id`：可选，便于回溯父版本
- `is_restored`：是否为回退版本

这样可形成更清晰的文档演化链。

---

## 5. 推荐把部分 JSON 字段结构化

当前字段如：

- `summary_json`
- `phases_json`
- `results_json`
- `metadata_json`

建议按“最常用字段优先结构化”的原则拆分。

### 推荐做法

#### 仍保留 JSON 的字段
- 复杂扩展字段
- 不确定未来会不会再变的字段

#### 单独拆成列的字段
建议从业务角度提炼出以下关键字段：

- `pipeline_status`
- `passed_count`
- `failed_count`
- `coverage_line_pct`
- `coverage_branch_pct`
- `signoff_status`
- `evidence_hash`
- `manifest_hash`

这样后续报表、筛选、告警会更容易。

---

## 6. 业务逻辑建议

### 6.1 统一状态流

建议把所有关键实体统一成状态机：

- `PipelineRun`
  - `running -> completed -> completed_with_errors -> cancelled`

- `Signoff`
  - `draft -> pending -> approved / rejected`

- `DocDocument`
  - `draft -> review -> approved -> deprecated`

每个状态变化都应写入事件表。

---

### 6.2 任何“关键动作”都要写审计事件

建议记录以下动作：

- 用户登录
- 项目创建
- 成员加入
- 文档创建/修改/回退
- 签核提交/批准/驳回
- 流水线启动/成功/失败
- 证据导出
- 证据校验

这能帮助把“系统行为”变成“可追溯证据”。

---

### 6.3 让签核对象真正绑定证据和版本

签核时建议至少做以下 3 件事：

1. 记录签核对象和对应 pipeline run 的关系
2. 绑定本次签核所用的 manifest / report / coverage / log
3. 把最终证据包 hash 存入 `Signoff` 记录中

这样就能形成真正完整的签核证据链。

---

## 7. 具体落地建议（优先级排序）

### P0：先做这 3 个

1. 增加 `signoff_events`
   - 解决签核审批链不可追踪的问题

2. 增加 `artifacts` + `evidence_links`
   - 解决证据链不明确的问题

3. 把 `Signoff` 的关键字段结构化
   - 如 `status`、`evidence_hash`、`manifest_hash`

### P1：再做这 2 个

4. 把 `summary_json`、`phases_json`、`results_json` 逐步拆分成结构化字段
5. 给关键表补齐唯一约束、索引、软删除字段

---

## 8. 一句话总结

当前数据库设计已经具备“平台骨架”能力，但如果想真正做成企业可用的签核系统，最关键的不是继续堆表，而是把“状态变化、证据绑定、审批轨迹”变成数据库里的第一等公民。

也就是说：

- 业务对象负责“当前是什么”
- 事件流负责“它怎么变来的”
- 证据对象负责“它依赖什么”

这三层一起组合，才是一个真正可审计、可签核、可落地的平台数据模型。
