# 对话、终端与 PySide6 桌面 GUI：一个底层验证内核

## 1. 实现原则

三种入口共享现有 `agent_mode_service`、Agent/Harness、Workspace 与 `verify_mode/router`。没有为名称为 chat / terminal / desktop 的三个入口各造一条验证链，也没有新增架构职责平面。

本项目的 **GUI 是 PySide6 桌面窗口**，不是新起的 Web 服务器，也不是 DeepSeek Harness 的网页外壳。

```text
 对话 CLI ────────────────┐
 vagent chat               │
                           ├── modes.interaction ─── agent_mode_service
 终端 REPL ────────────────┤                         ├── Agent / Harness
 vagent / vagent -r  ──────┘                         ├── 既有 LLM 预算与审计
                                                     ├── Workspace / Session
                                                     └── 审批与恢复

 PySide6 GUI ── TaskRunner 后台执行同一个 turn
              ── pending / proposal / error 展示真实状态
              ── 明确审批后，恢复同一个 Harness checkpoint
              ── 打开既有 flow.pipeline 查看验证与证据

 明确 verify ───────────── verify_mode / router ── 既有 Engine 与运行记录
```

## 2. 入口与职责

| 入口 | 命令或页面 | 负责什么 |
|---|---|---|
| 对话 CLI | `vagent chat "解释这段握手"` | 单次自然语言交互；可沿用现有 Agent session |
| 候选计划 | `vagent chat --mode plan "制定验证计划"` | 强制计划与操作审批候选，返回真实检查点 |
| 终端长循环 | `vagent`、`vagent chat --repl`、`vagent -r <session>` | 多轮 REPL、命令与人工审批/恢复 |
| 显式验证 | `vagent ... --mode verify "明确目标"` | 使用既有确定性验证主链，不把模型文本当成运行证据 |
| 桌面 GUI | `vagent gui` | PySide6 中提供「项目 → 交互与验证」；验证详情仍由原有「验证流程」页承载 |

`agent` / `verify` 是底层执行模式；`chat` / `plan` / `verify` 是新增交互适配层的三类明确动作。GUI 选择「显式验证 verify」时，不依据普通聊天判断该运行哪个命令，而是将用户选定并已明确提交的目标交给已有验证路由。

### 单次对话

```powershell
venv\Scripts\vagent.exe chat "解释 VALID/READY 握手的稳定性"
```

### 计划候选与人工恢复

```powershell
venv\Scripts\vagent.exe chat --mode plan "为 DMA 制定验证计划"
```

计划必须沿用原 Agent 检查点处理，不能由前端假装已成为已确认 Specification：

```powershell
venv\Scripts\vagent.exe chat --resume <session-id> --approve yes
```

如果要拒绝、补充回答或调整计划，可分别使用 `--approve no`、`--answer`、`--plan-text`。必要的模型输出格式、调用预算与审计仍由原 Harness / Query Engine 负责。

### 多轮终端

```powershell
venv\Scripts\vagent.exe
```

```powershell
venv\Scripts\vagent.exe chat --repl
```

两者都进入已有长循环 REPL；`/approve`、`/deny`、`/answer`、`/plan`、`/status` 继续使用既有实现。新单轮命令并未重写 REPL。

### 明确验证执行

```powershell
venv\Scripts\vagent.exe -p "验证指定项目并报告真实结果" --mode verify
```

```powershell
venv\Scripts\vagent.exe chat --mode verify "验证指定的规格文件"
```

前者保留原命令行为。对外状态、退出码、运行目录和证据仍由原验证内核维护。对于本机不存在的 EDA，保持 INCOMPLETE；不能因为通过交互界面发起了任务就显示 PASS。

### 桌面 GUI

```powershell
venv\Scripts\vagent.exe gui
```

或者使用 `run_gui.bat`。在「项目」组新增 **「交互与验证」** 页面：包含模式选择、工作区、自然语言输入、真实状态、原始结果和待审批区。

- 发送对话或计划阶段由 TaskRunner 放到工作线程，不让耗时操作阻塞 Qt 主线程。
- 完成/暂停/拒绝均通过 Qt 信号回到主线程；后台工作线程不直接更新控件。
- 只有结果携带真实 `session` 和 `pending` 时才显示审批区。
- 批准/拒绝/补充回答通过原 `agent_mode_service.resume_turn()` 恢复，不重新启动第二个 Agent 任务。
- 模式切换和新任务只解除当前前端关联，旧会话文件不被删除。
- 点击「打开验证流程」调用现有 `open_module()` 定位 `flow.pipeline`，不另建第二套执行页面。
- 输入路径只作为工作区/自然语言任务输入传给同一服务；未知文件、错误或 absent 状态不会自动变为确认事实。

### GUI 的 9 种 Agent 模式

下拉框来自单一清单 [agent_modes.py](../../src/workbench/modes/agent_modes.py)——
界面、后端 config、测试都读这一份，不存在"界面 9 个模式、后端只认 3 个"的第二份真相。
**模式是领域角色，交互方式（chat / plan / verify）是底层真路径**，两者正交：

| 模式 | 描述 | 交互 | 对应 agent（`specialists/`） | stages |
|---|---|---|---|---|
| Agentic Chat | General-purpose chat for workspace exploration and code assistance | chat | `agentic_chat`（通用 Harness） | - |
| Mental Model | Design understanding and analysis mode | chat | `mental_model` | - |
| Formal | Formal verification agent mode | plan | `formal`（生成 Formal IR；无引擎时 engine.ran=false） | verify |
| UVM | UVM testplan, testbench development mode | plan | `uvm`（UVM 子图，原 verify 实现） | verify |
| RTL Designer | Lint violation Auto-fix | plan | `rtl_designer` | front/design/model |
| Unit Testing Agent | Unit testing and testbench development (SV based, no UVM) | plan | `unit_testing`（纯 SV TB 生成 + vlog/vsim） | verify |
| Functional Coverage (interface-based) | Functional coverage monitor generation (RTL interface-based) | plan | `functional_coverage` | coverage |
| Debug | DV debug agent mode | plan | `debug` | ops/debug |
| Workflows | End-to-end automated workflows | verify | `workflows`（入口；执行走 supervisor） | 全阶段 |

**对应关系**：8 个业务模式现在都有明确落点——`mental_model` / `formal` /
`unit_testing` 是独立专家（见 [Standalone 专家](SPECIALIST_AGENTS.md)），
`rtl_designer` / `uvm` / `debug` / `functional_coverage` 是闭环专家，
`workflows` 是执行入口（走 supervisor）；Agentic Chat 是 `agentic_chat` 通用
Harness。上表是**当前真实映射**，UI 的 hint/tooltip 和返回结果的
`interaction.specialist/stages` 都从这里来；新增专家后只改
`agent_modes.py` 一处即可。

每个 agent 都有对话命令（与 GUI 共用同一份模式配置）：

```powershell
vagent agents list
vagent agents chat uvm "分析这份 testplan"
vagent uvm chat "分析这份 testplan"
```

- `plan` 模式会设置 `plan_first=True` / `require_plan_approval=True`，并保留执行审批；
- `verify` 模式走既有 `verify_mode/router`，不经过 agent chat；
- 模式注册表里的 `action` 决定是否出现**统一动作按钮**（界面不再按模式写分支）：
  - Mental Model → 「生成 Mental IR」→ `specialists/mental_model`；
  - Formal → 「生成 Formal 计划」→ `specialists/formal`；
  - Unit Testing → 「生成/运行单测」→ `specialists/unit_testing`。
  产物分别落在 `<workspace>/output_*/` 下对应子目录。

## 3. 一致性与人审边界

新增 [共享适配器](../../src/workbench/modes/interaction.py) 很薄，只负责模式适配和展示元数据：

| 交互选择 | 实际调用 | 审批策略 |
|---|---|---|
| chat | 原 `agent_turn()` | 对执行/写入类工具请求开启人工审批 |
| plan | 同一个 Agent/Harness，`plan_first=True` | 强制计划审批，并对执行类操作保留审批 |
| verify | 原 `verify_mode` / router | 由既有 Engine 的审批和执行契约决定 |

必须区分这几种状态：

- **模型讲解/计划草稿**：供人阅读，不是确认的事实；
- **proposal**：候选提案，仍需复核；
- **paused**：有真实 question/approval/plan 检查点待解决；
- **VALIDATED / PASS / FAIL / INCOMPLETE**：由原 Engine 与真实数据决定，不根据界面前缀换算。

错误返回、空返回和错误类型均在前端被拒绝。GUI 的错误处理先验证任务归属与类型，再更新控件；不会保留旧 pending 信息让用户误批准另一项操作。

## 4. 工作区、模型与隐私

- 延续既有 Session / Harness 持久化，`session_id` 是恢复同一上下文的依据。
- 不将 Agent 心智模型改写成另一上层 JSON，也不替代既有芯片工作区的 SourceAnchor / Temporal IR / Binding 证据。
- 预设工作区为当前目录，可由用户明确选择。约束的是同一个 `workspace`，不能让每个前端在不同项目副本中自行运行。
- 模型仍使用现有配置和集中调用链，不绕过原模型工厂的 schema、预算、重试和缓存。
- GUI 不收集、不保存密码或 API Key。
- 页面在创建时不调用 LLM、不启动 EDA、不修改缓存。只有用户发送一个请求后才建立工作线程。
- `.signoffai` 会话是当前真实会话的来源；不为只有 structured authoring 的 ChipStack 示例虚造聊天。

## 5. Qt 版本与环境

[pyproject 中的 GUI 依赖](../../pyproject.toml#L60-L70) 当前固定 `PySide6==6.6.3.1`。

实测 6.12 环境中，新界面的定向测试主体通过后，进程在析构阶段以 `0xC0000409` 结束，并报告 Qt thread-storage 退出异常。以同样的测试对照原可用环境中的 6.6.3.1，正常退出。因此此处是兼容性选择，不是忽略退出码，也没有收紧其它 Python 包的版本。

旧混合环境仅移到同仓库下的 `venv_broken` 备份，不会覆盖用户原来的系统解释器或旧 `D:\liujiangqing\.venv` 包目录。实际使用 `venv/`。这两个环境文件夹与备份均在 `.gitignore` 中。

如果再次修改 Qt 版本，必须再次运行真实 PySide6 进程级测试，而不能只看测试主体是否全绿。

## 6. 当前限制

- 当前入口提交 turn 并异步展示完整结果，没有宣称原生、连续的 LLM token 流。执行日志和审批则以原运行记录为准。
- 界面中的 Respond/Approval 用例使用注入的 Agent caller，以验证前端路由和线程行为；这不是远端模型联调或硬件仿真证据。
- 对话答案本身仍需要源文件、规格绑定或真实执行证据支撑。不能把推测当签核证据。
- 工作流重放、跨 run 失效传播、完整 auto-fix 安全替换，继续继承原有规则，不由本前端完成后补造。
- 这里不启用独立 Web 服务，也不把本页面称为 Web UI。

## 7. 验证入口

- [共享路由测试](../../tests/test_interaction_frontends.py)：确认 chat/plan/verify 使用正确调用与审批配置，不产生额外 Agent。
- [PySide6 交互测试](../../src/workbench/tests/test_interaction_module.py)：模块初始化、后台线程、暂停/恢复、跳转与错误载荷。
- [完整 GUI 清单构建测试](../../src/workbench/tests/test_workbench_registry.py)：真实清单的成功实例化数量从 47 增至 48，仍属于既有 Interfaces Plane。

## 8. 无回复/无错误提示问题：修复与诊断

### 已找出的真实前端缺陷

最初本模块调用 `ctx.tasks.submit()` 后，没有自行连接 `tasks.finished` / `tasks.failed`。主窗口只把任务完成/失败写到总控制台，**不会自动把回复载荷送到具体聊天页面**。

现在 [InteractionModule](../../src/workbench/modules/interaction/module.py) 在生产使用的 `create_widget()` 中，用一次性的标志绑定本模块自己的 `on_finished` 和 `on_error`。这意味着：

- Agent 返回的回答与 session 会显示在聊天面板；
- `error` / `blocked` / 后台异常会直接显示在消息区和顶部 Banner；
- `_jobs` 在收到本任务的真实结果后清除，发送按钮恢复；
- 状态区显示等待秒数。超过 15 秒仍未收到结果会提示检查模型配置和会话，但这只表示仍在等待，**不把等待判成完成或超时失败**；
- 返回类型错误、空结果、调用异常都会有可记录、可见的错误，不会留下“静默永久忙碌”。

此前测试在夹具中手动连接上述信号，掩盖了生产路径的缺失。现在测试明确不再手动补接线，并以实际清单创建的 `QMainWindow -> manager -> InteractionModule -> TaskRunner` 路径验证返回，防止重现这一类假绿。

### 当前配置导致的第二个问题

用户实际最近的 Agent 会话已经落在 `blocked`，显示 `LLM_UNAVAILABLE（无输出或输出不符合 JSON 决策 schema）`。本地配置检查发现：

- 当前提供商：`deepseek`；
- 当前模型：`deepseek-flash`；
- `LLM_API_KEY`：**未设置**；
- Base URL 已配置，但没有密钥并不表示模型可以连接。

**缺少 API Key 与桌面回包链路是两个独立原因。只改 GUI 并不会凭空得到模型答案。**

不要在对话框里提交密钥。可依据 [`.env.example`](../../.env.example) 建立本地 `.env`（该文件已被 `.gitignore` 排除），配置自己的提供商、端点、模型和密钥，然后**完全退出并重新启动 PySide6 桌面应用**。示例模型名已与当前 Settings / LLMFactory 的 `deepseek-flash` 取值保持一致；自定义端点应使用该端点实际支持的模型，不能只看名称对照。

`.env` 当前用 `venv/Scripts/python.exe` 检查时，只应输出布尔状态，不打印密钥：

```powershell
venv\Scripts\python.exe -c "from config.settings import Settings; c=Settings.get_instance().llm; print('provider=',c.provider); print('model=',c.model); print('api_key_configured=',bool(c.api_key))"
```

该检查只能说明配置是否存在，不能证明凭据有效或服务可用。对于本地自定义提供商，请使用其真实 JSON 输出格式与认证要求；不要把占位密钥用于需要认证的远端服务。

另外，当前 Agent 不是绕过 Harness 的通用裸聊天补全器：其返回必须符合原决策格式（单次 JSON、合法的 tool 选择与参数）。模型没有输出、凭据/接口错误、超时，或不遵守该 JSON 决策格式，都不能成为正常回答。修复后 GUI 会明确显示这些失败，不会退成编造的"好的"。

### 你应该如何验证

1. 更新到这个修复版本并重启桌面应用；
2. 查看工作区旁的模型配置提示；
3. 按本地密钥和提供商配置补齐后再次重启；
4. 先发送一个不涉及改文件/EDA 的简单问题；
5. 若仍失败，查看聊天面板的真实错误、顶部 Banner、状态区与 `.signoffai` 的实际会话，而不是盲目重复点击。

宿主 DeepSeek Harness 中的当前助手可以对话，并不代表本仓库已经自动继承其模型账户或凭据。本项目的模型调用仍按自己的 Settings / QueryEngine 管理，本次不会从宿主读取或复制任何 API Key。

### 本次已完成的进程级验证

- 该无回复缺陷的新增生产路径回归：**15 项直接路由与 GUI 测试通过**；
- 与窗口、TaskRunner 和真实清单联动检查：**65 项通过**，包括生产路径下的恢复、错误和等待状态；
- 本次修复后的全仓库 `tests/`：**1349 passed、16 skipped，`PYTEST_EXIT=0`**；窗口与任务专项回归：**65 passed**。
- 此前完整 `src/workbench/tests/` 基线拆成两个互不重复的部分：**649 passed** + 流程模块 **50 passed**，即 **699 passed**，两个进程出口均为 0。此后修复回包遗漏的测试另见上面的 65 项窗口/任务专项检查。
- 本次新增/修正的共享路由、模型配置与 GUI 定向用例：**15 passed**；它不再由测试手动补装生产连接，明确覆盖真实窗口路径。
- 真实清单按新数量 **48** 成功实例化；新增子进程导入检查在退出码上也通过。
- Architecture Guard：**OK**；新增交互相关 Ruff lint：通过。

### 实际 PySide6 控件截图

[打开交互模块的离屏截图](../../review_bundle/interaction_modes/pyside6_interaction_module.png)。它是用 PySide6 `QWidget.grab()` 实际渲染的文件，不是 HTML 示意图或人工拼接的图片。捕获时未调用模型、未启动验证或 EDA。

当前模型不具备本次图片查看能力，所以没有宣称完成视觉复核。请通过上面的文件或真实 GUI 检查布局、中文显示和按钮可用性。Qt 还有字体目录缺失与析构回调警告，不能用测试通过数字代替视觉/运行时检查。

### 不能从这些测试推出的结论

- 注入 caller 的界面测试不证明模型提供商已连通，也不证明有 LLM 完成设计理解。
- 假图审批和状态机测试验证流程与界面关系，不是完整 RTL 仿真、形式证明或 PPA 通过。
- 本次结果不恢复未执行的 formal、lint、PPA、compile-fix 工作。
- 当前 `venv_broken` 只保留作环境问题备份，不是可运行环境。实际使用 `venv/`。

不把个别单测断言通过掩盖 Qt 原生退出失败；不把多个窗口入口的存在当成硬件签核完成。
