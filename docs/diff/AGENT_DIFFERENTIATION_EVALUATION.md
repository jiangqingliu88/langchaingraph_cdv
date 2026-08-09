# SignOffAI 智能体差异化评估

## 1. 评估目的

本文档基于当前代码实现，对 SignOffAI 中智能体（Agent）架构的差异化优势进行评估，重点关注：

- 智能体组织与角色划分
- 与通用 AI 编程助手的本质区别
- 本项目在可追溯、可审计、可治理方面的能力
- 需要补强的差异化空间

## 2. 智能体架构概览

核心智能体体系由 `src/core/base.py`、`src/core/registry.py` 和 `src/core/execution.py` 组成。

### 2.1 基础智能体抽象

`src/core/base.py` 定义了 `BaseAgent`：

- 使用模板方法模式组织初始化、LLM 创建、工具绑定、执行和重试逻辑。
- 支持 `consumes` / `produces` 声明共享上下文 `ctx` 的读写契约。
- 内置分数阈值、最大重试次数和最高结果保存，提供质量回退机制。
- 通过 `AgentResult` 统一返回结构化结果。
- 支持 `AgentObserver` / `AgentSubject` 模式，便于事件监听和执行追踪。

这说明项目不是简单把 LLM 当生成器，而是把每个智能体当成具有生命周期、状态、质量判断和上下文契约的执行单元。

### 2.2 智能体注册与执行管理

`src/core/registry.py` 实现了单例 `AgentRegistry`：

- 允许动态注册/获取 Agent 类和实例。
- 支持集中管理当前系统可用的智能体。

`src/core/execution.py` 的 `PipelineExecutionService` 将智能体组织到流水线阶段中：

- `FULL_PHASES` 定义了 `spec`、`design`、`model`、`vplan`、`tpoint`、`UVM`、`test`、`assert`、`regress`、`cover`、`debug`、`qa`、`report` 等阶段。
- 每个阶段对应一个智能体角色或文档生成阶段。
- 提供 `run_pipeline`、`run_single_agent`、状态查询、SSE 交互等运行能力。

这意味着系统本质上是一个“多智能体工作流执行平台”，而非单一对话式助手。

## 3. 关键智能体与功能定位

### 3.1 规格与测试规划智能体

`src/agents/spec_planner/main.py` 中的 `SpecAndTestPlanner`：

- 任务类型 `spec_analysis`
- `consumes = []`, `produces = "spec"`
- 使用专门的 prompt 要求输出严格 JSON 结构。
- 通过 `SpecAnalysisTools` 提供辅助工具。
- `post_process` 从 LLM 输出中提取规范结构化 spec，并计算质量分。

该智能体的差异化在于它不是泛用自然语言理解，而是专门为 IC 验证规格建模而设计的“规格解析与测试规划器”。

### 3.2 验证架构师智能体

`src/agents/verify_architect/main.py` 中的 `VerificationArchitect`：

- 任务类型 `code_generation`
- `consumes = ["spec"]`, `produces = "env"`
- 使用 LangChain Agent + 8 个行业工具：`find_spec_yaml`、`jinja_render`、`quality_report`、`check_static`、`check_compile`、`check_loopback`、`check_health`、`read_file`、`write_file`
- prompt 明确定义“生成 UVM 环境、质量自检、自动修复、失败退回”的工作流。
- `validate()` 通过静态检查、编译检查、loopback 检查确定交付质量。
- `_post_process()` 读取质量报告，构造下游 `env` 上下文，从而支持后续测试阶段。

这说明该智能体并非“生成一点代码”，而是“生成 + 工具闭环校验”的专业验证环境生成器。

### 3.3 其他智能体概览

关键智能体还包括：

- `DesignArchitect`：设计架构与 RTL 生成
- `ModelAgent`：参考模型与 Predictor
- `TestEngineer`：测试场景生成
- `AssertionEngineer`：SVA 断言生成
- `CoverageManager`：覆盖率收集与分析
- `RegressionManager`：回归执行与结果记录
- `DebugEngineer`：失败诊断与修复建议
- `QualityAssurance`：质量评审
- `ReportGenerator`：最终报告与签核摘要

这些智能体分工明确，形成“规格→验证→签核”的闭环。

## 4. 对比通用 AI 的差异化优势

### 4.1 角色与工作流分工

通用编程助手（如 Copilot、Claude Code）通常是“单个大模型 + 单步代码补全/生成”。

SignOffAI 的优势在于：

- 多 Agent 不是“多个 prompt”，而是“多个专业角色 + 不同任务类型”。
- 每个 Agent 有不同的 `task_type`、不同的 `consumes`/`produces`，这本质上是“工作流化的智能体链路”。
- 这种模式适合 IC 验证这种多阶段、多专业的领域。

### 4.2 领域专用工具与 schema 校验

`src/core/tool_system.py` 实现了 Tool + ToolRegistry + Sandbox：

- Tool 支持 `input_schema` 验证，保证 LLM 调用参数合法。
- `RiskLevel` 与 `Sandbox` 机制提供“safe/write/danger”分级控制。
- 这种机制类似 Claude Code 的工具 schema，但更贴近验证场景的安全边界。

通用助手缺少这一层行业工具绑定和执行安全控制。

### 4.3 证据链与 manifest

`src/core/evidence.py` 和 `src/core/manifest.py` 为系统提供了差异化证据能力：

- 5 层证据链模型（需求、设计、验证、执行、签核）。
- `RunManifest` 记录阶段输入/输出 hash、阶段产物、tool 调用、执行日志。
- `ExecutionTracer` 记录 LLM 调用、工具调用、文件写入等到 `logs/execution`。

这使得 SignOffAI 能输出“可审计的验证证据包”，而通用 AI 工具通常只能输出文本或代码。

### 4.4 交互与可追溯执行

`src/web/api.py` 提供了：

- REST 接口启动 pipeline、查询状态、运行历史、SSE 实时推送。
- vPlan / traceability / signoff / regression / coverage / testcases 管理接口。
- 审计日志写入入口。

系统不是“ChatGPT 页面”，而是一个带实时执行、结果查询和交互反馈的工程平台。

## 5. 代码中体现的差异化要素

### 5.1 Agent 与上下文契约

`BaseAgent` 的 `consumes` / `produces` 定义导致：

- `spec` -> `env` -> `tests` -> `coverage` 等明确数据流。
- 这种设计让智能体之间的衔接更像“编排管道”，而不是“各自回答问题”。

### 5.2 质量自检与降级策略

`VerificationArchitect` 的 `validate()` 和 `Super()` 的 retry 机制表明：

- 系统自带质量门槛，而不是不加控制地执行 LLM 输出。
- 可接受“静态校验通过但编译/闭环失败”的降级结果，保证流程可继续。

### 5.3 Tool schema 与风险控制

`ToolRegistry.invoke()` 的 schema 验证和 `Sandbox.check()`：

- 防止 LLM 传入非法参数。
- 对写磁盘和危险操作做审批控制。
- 为后续做“企业级治理”提供基础。

### 5.4 证据链差异化

`EvidenceCollector.collect()` 完整收集了：

- 需求层校验（req/test 映射、规格完整性）
- 设计层校验（RTL 信号/寄存器映射）
- 验证层校验（P0/P1/P2/P3 任务状态）
- 执行层校验（输出文件、回归日志、错误分类）
- 签核层校验（是否满足签核条件）

这给 SignOffAI 提供了“行业专用证据链”的核心论据。

## 6. 当前实现中的差异化短板

虽然框架设计较好，但实际实现中还存在可优化之处：

### 6.1 权限与项目隔离落地尚不充分

- `src/infra/rbac.py` 定义了详细权限集，但 `src/web/api.py` 中多数接口仍只做 `require_auth`，并未严格按项目/角色细分权限。
- `src/infra/project_isolation.py` 是内存对象实现，与数据库中的 `Project` / `ProjectMember` 并不是完全一致的治理链路。

### 6.2 证据与审计闭环还未完全统一

- `manifest.py` 支持生成 manifest，但并未看到全局证据包导出 API 与验证功能。
- 审计日志存在，但 `AuditLog` 字段（例如 `resource_type` / `resource_id`）的使用还需进一步规范。

### 6.3 真实 EDA 工具集成仍处于雏形

- `VerificationArchitect` 的工具链抽象很好，但是否支撑 Questa/VCS/Verdi 等真实工业工具的完整稳定闭环，还有待实际验证。
- 目前更多是“执行器、脚本、工具封装的初步形态”，不是“完全工业化的 EDA 调度平台”。

## 7. 结论与建议

### 7.1 结论

SignOffAI 的智能体架构已经具备明显差异化：

- 从单一助手转向多智能体专业角色链路；
- 从文本生成转向工具驱动验证产物；
- 从“问题回答”转向“验证流程执行”；
- 从“结果不可知”转向“可审计证据链”。

如果把项目进一步聚焦在“功能验证与签核协作平台”上，这个差异化会非常有竞争力。

### 7.2 建议

1. **强化 Agent 角色边界**：把 `SpecAndTestPlanner`、`VerificationArchitect`、`RegressionManager` 等智能体明确写成“专业 Copilot”，而不是“生成器”。
2. **补齐治理链路**：把 `RBAC`、`ProjectIsolationManager`、`AuditLog` 和 API 访问控制真正联通。
3. **推动证据包完整性**：补充“manifest + evidence package 导出 + 校验”能力。
4. **验证真实工具链**：优先落地一个 Questa/VCS 的真实回归闭环，形成工业验证能力。
5. **将智能体差异化写成产品卖点**：
   - “每个阶段是可审计的 Agent”，
   - “每个 Agent 都有上下文契约和质量门槛”，
   - “整个流程输出的是签核证据包，不只是代码。”

---

## 8. 推荐落地表达（可直接用于融资/产品文档）

> SignOffAI 的核心差异不在于“AI 会写 UVM”，而在于“AI 能在验证流程中做到可执行、可追溯、可审计、可治理的工程化产物交付”。

> 它不是一个通用代码助手，而是一个“面向 IC 功能验证的专业智能体平台”。
