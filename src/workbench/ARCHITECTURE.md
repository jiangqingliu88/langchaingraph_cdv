# Workbench 架构（当前实现）

> 基线：2026-10-31
>
> 本文描述 `src/workbench/` **代码现在怎么组织**，与仓库根
> `ARCHITECTURE.md` 是同一套系统：CLI 是唯一正式入口，工作台是它的
> **可选桌面外壳**。`readme.md` 偏使用说明；本文偏结构、契约与扩展点。

## 1. 定位与边界

Workbench 是一个 **PySide6 桌面应用**，不是 Web 前端：

- 入口：`python -m src.workbench [清单.yaml]`
- 等价入口：`vagent gui run ...`（CLI 里同一套参数）
- 依赖：`PySide6` 与 `qdarkstyle` 都在 `pip install -e .[gui]` 里，**可选**；
  缺失时 `bootstrap.require_pyside6()` 给出装法并以退出码 2 结束，不甩 traceback。
- **不开发 Web UI / Dashboard / SSE**（见 `CLAUDE.md`）。工作台只做桌面窗口。
- 工作台**不另造验证引擎**：业务数据全部来自 CLI/流水线落盘的 run 目录、
  manifest、覆盖率与证据包；工作台与流水线通过**文件契约**解耦，不共享内存状态。

## 2. 分层与依赖方向

```text
app.py                         主窗口 / 菜单 / 工具栏 / 状态栏 / 启动流程
  ├─ registry.py               ModuleManager：清单 → 视图
  ├─ context.py                AppContext：模块能碰到的全部平台能力
  ├─ manifest.py / spec.py     清单读取、校验、声明式契约（不依赖 Qt）
  ├─ config.py                 清单路径 / 业务输入路径解析（不依赖 Qt）
  ├─ loader.py                 "包.模块:类名" 工厂解析
  ├─ projects.py               项目登记表（用户级 YAML）
  ├─ settings_store.py         QSettings：几何 / dock / MDI / 主题
  ├─ bus.py                    事件总线（模块之间只通过话题通信）
  ├─ tasks.py                  后台任务（QThreadPool，结果回主线程）
  ├─ bridge/                   工具绑定 / 归一化 / 参数整形（不依赖 Qt）
  ├─ modules/                  业务模块（插件）
  └─ ui/                       通用 UI 组件（不含业务词汇）
```

**依赖只能从上往下**：`ui ← bridge ← modules ← registry ← app`。

- `bridge/`、`spec.py`、`config.py` **不 import Qt** —— 清单解析与工具绑定
  可以在无显示器环境下被测试和回答。
- `ui/` **不认识任何业务词汇**；业务词汇只出现在 `modules/`。
- 模块不直接 import `src/tools/**`，只通过 `bridge/catalog.py` 的绑定名调用。

## 3. 启动流程

```text
python -m src.workbench [manifest] [--module ID] [--input PATH]
                         [--theme NAME] [--project ID] [--reset-layout]
        │
        ▼
bootstrap.require_pyside6()          缺 PySide6 → stderr + exit 2
        │
        ▼
app.build_parser().parse_args()
        │
        ├─ --project → apply_project()
        │     换 cwd + 换清单（项目隔离靠"换目录"实现；切换需重启）
        │
        ├─ resolve_manifest_path() → load_manifest()
        │     清单坏了 → 内置空清单 + 顶部红条，不闪退
        │
        ├─ SettingsStore()（--reset-layout 时 reset）
        ├─ theme.apply(app, 命令行 > 清单 > 上次 > 默认)
        ├─ AppContext(manifest, bus, tasks, tools, settings)
        └─ WorkbenchWindowImpl(app, ctx)
               ├─ _build_central()      MDI 工作区 + 横幅
               ├─ _build_console()      底部控制台
               ├─ _build_actions()      工具栏/快捷键
               ├─ _build_status()       状态栏（必须先于建模块）
               ├─ _build_menus()        七个菜单
               ├─ manager.build(manifest)
               ├─ _apply_pane_defaults()
               ├─ _restore_layout()
               └─ _report_after_build()
        │
        ▼
window.show(); app.exec()
```

`build_workbench()` **只建窗口、不跑事件循环** —— 测试与 `main()` 共用它。

## 4. 清单驱动（唯一的界面真相）

清单默认 `config/workbench.yaml`，字段定义在 `spec.py`（pydantic，
`extra="forbid"`：键名拼错启动即报错，不静默忽略）。

```yaml
version: 1
window:
  title: "SignOffAI · 验证工作台"
  size: [1520, 940]
  theme: ""              # 空 = 平台默认；命令/清单/上次依次兜底
  restore_layout: true

groups:                  # 业务线（左树分组 + 窗口菜单分段 + action 归属）
  - {id: flow, title: 流程与证据, order: 8, section: 贯穿层}

modules:
  - id: flow.signoff
    title: 签核判定
    group: flow
    factory: src.workbench.modules.flow.signoff:SignoffModule
    area: center                 # center | left | right | bottom
    order: 30
    tool: {name: flow.signoff, kind: json}
    params: {subscribe: run.selected}
    placeholder: false
```

关键约定：

| 键 | 语义 |
|---|---|
| `area` | `center` = 中央 MDI 子窗口；`left/right/bottom` = QDockWidget |
| `group` | 必须存在于 `groups`；决定左树分组、窗口菜单分段、模块动作进「调试」还是「工具」 |
| `section` | 业务线之上的业务域；导航树按「域 → 业务线 → 模块」三级展开 |
| `factory` | `"包.模块:类名"`，由 `loader.resolve()` **惰性 import** |
| `input` | 模块的业务输入；相对路径按**清单所在目录**解析 |
| `tool` | 主绑定工具名（必须是 `bridge/catalog.py` 登记过的名字） |
| `params.subscribe` | 平台把列出的话题接到模块 `on_refresh`；订阅关系读 YAML 即可见 |
| `placeholder` | `true` = 无真实数据源；平台**自动**挂关不掉的警示横幅 |
| `pin_to_view` | 显隐开关同时也挂到「视图」菜单（窗格型模块用） |

**清单里没有流程拓扑**：阶段、前驱、回边属于领域（`graph.py` / `stages.py`），
视图只消费；写进 YAML 会出现第二份真相。

## 5. 窗口外壳与工作区

`WorkbenchWindowImpl` 自己几乎不做业务，只做四件事：

1. 读清单 → `ModuleManager` 建界面；
2. 摆好中央工作区 + 三面 Dock + 状态栏 + 控制台；
3. 提供模块要用的钩子（`set_tab_suffix` / `set_status` / 窗格开关）；
4. 关窗口时逐个问模块「能关吗」，存/取布局。

界面形状（当前实现）：

```text
QMainWindow
├─ 中央 = QWidget
│   ├─ Banner                    平台横幅
│   └─ WorkspaceArea             QMdiArea：center 模块 → ModuleSubWindow
├─ ModuleDock「模块」   (left)   导航树（pin，关不掉）
├─ ModuleDock …         (left)   flow.runs
├─ ModuleDock …         (right)  flow.evidence
├─ ModuleDock「控制台」 (bottom) 控制台（pin，关不掉）
└─ ModuleDock …         (bottom) debug.fingerprint
```

- **center 模块可多开**：`_subwindows[module_id]` 是列表，每个窗口独立模块实例。
- **dock 模块单例**：同区 dock 自动 `tabify` 成页签；标签栏也补了 ×。
- **关掉不是销毁**：视图窗口 `WA_DeleteOnClose=False`、dock 只 `setVisible(False)`；
  编辑器文本/计算结果不因关一下丢失，导航树与「窗口」菜单随时能再开。
- **center 懒加载**：`manager.build()` 只实例化模块（挂菜单动作、载输入），
  控件先存起来；左树/菜单点开时才进 MDI。
- **布局持久化**：`SettingsStore` 用 `QMainWindow.saveState()` + `Workspace`
  自己序列化的 MDI 子窗口几何；布局版本号不匹配就不贴旧布局。

七个顶层菜单固定：文件 / 编辑 / 视图 / 调试 / 工具 / 窗口 / 帮助。
**业务线不占顶层菜单**；它们在导航树、「窗口」菜单分段，以及模块动作归属
（`debug → 调试`，其余 → `工具`）里。

## 6. 模块插件契约

`modules/base.py` 的 `IModule` 是平台唯一认识的契约：

| 方法 | 作用 |
|---|---|
| `create_widget()` | **必须实现**；建主控件，只调一次 |
| `build_content()` | `ModuleBase` 的钩子：搭内容控件 |
| `create_actions()` | 模块自有动作（快捷键、菜单/工具栏） |
| `on_activated()` | 标签页被选中 / dock 被抬升 |
| `on_theme_changed()` | 主题切换后重挂图标、重画自绘控件 |
| `on_input_changed(path)` | 清单 `input` 或 `--input` 指过来时 |
| `on_refresh(payload)` | 收到订阅话题后 |
| `can_close()` / `mark_clean()` | 有未保存改动时拦住关窗口 |

`ModuleBase` 替子类做了三件共同义务：

1. **顶部横幅**（`Banner`）；
2. **工具失败落点**：`run_tool()` 不抛，失败同时进横幅、控制台、状态栏；
3. `placeholder: true` 时**自动**挂关不掉的警示横幅。

能写盘的模块还必须调 `record_human_edit()` —— 人工修改进哈希链与五层证据；
不调就等于这次编辑在所有审计视图里不存在。

## 7. 工具绑定（bridge）

模块不直接 import 工具，而是按名字调：

```python
payload = self.run_tool(output_dir=target)          # 清单里的主工具
payload = self.run_tool("sim.parse_log", log_text=text)
```

`bridge/binding.py` 负责三件事：

- **惰性 import**：清单列了但没启用的模块/绑定，不会因依赖缺失拖垮启动；
- **返回值归一化**：`src/tools/` 返回 dict 或 JSON 字符串不统一，由 `kind`
  （`auto/text/json/filesystem`）决定；**归一化永不抛**，非 JSON 原样放进
  `{"raw": ..., "_parse_error": ...}`，因为工具错误路径常返回纯文本；
- **非纯守卫**：`pure=False` 的绑定（LLM / 编译 / 仿真 / 回归 / 写盘）默认
  拒绝执行，必须 `force=True` 显式触发 —— 防止切标签页顺手烧一次 LLM。

`bridge/catalog.py` 是**唯一**允许写工具 python 路径的地方；清单里写的是
可审计的绑定名，不是任意 import 路径。`bridge/adapters.py` 只做参数整形
（把吃 JSON 字符串的工具包成吃关键字参数），不改原工具。

## 8. 数据流

```text
CLI / LangGraph 流水线
        │  写：run 目录（manifest / coverage / evidence / logs / 决策）
        ▼
文件契约（不共享内存 state）
        │  读：flow.* 模块 / agent_output / 覆盖率 / 证据
        ▼
Workbench 模块 ──tool 绑定──► src/tools（只读分析/查询）
        │
        ├─ EventBus：run.selected / run.updated / input.changed / log ...
        └─ TaskRunner：编译/仿真/扫描等长任务在后台线程，结果回主线程
```

- **选中的运行**是跨视图的锚点：`flow.runs` 发布 `run.selected`，其余模块在
  清单 `params.subscribe` 里订阅。
- 模块之间**不互相 import**，只通过 `bus.py` 的字符串话题通信。
- 长任务由 `tasks.TaskRunner` 提交（`QThreadPool` + `QRunnable`），结果经
  主线程信号返回；刻意不做取消/优先级/进度条（跑起来的仿真停不掉，给一个
  点不动的取消按钮更糟）。
- 工作台与 CLI 的契约是**文件**：同一份 run 目录既能被 CLI 读，也能被工作台
  打开；工作台不替流水线计算业务结论。

## 9. 模块清单（`config/workbench.yaml`，37 个启用模块）

| 业务线 / 域 | 模块 | 作用 |
|---|---|---|
| `project` / 项目 | `project.overview`、`project.management` | 当前项目/最近运行进展 + 项目登记表（切换需重启） |
| `service` / 客户工程 | `service.uvm`、`service.regression`、`service.coverage` | 三个业务服务入口（只做导航/编排，见 §16） |
| `platform` / 平台配置 | `platform.settings` | 当前项目/清单/Python/Qt/EDA 工具的可读视图 |
| `ide` / 设计时 | `ide.ip_spec`、`ide.manual_nodes` | IP 规格、人工节点 YAML 编辑 + schema 校验 |
| `verify` / 运行时 | `verify.casemodel`（12 页）、`verify.isa_gen`、`verify.output` | case 属性建模、ISA 激励、验证产出 |
| `design` / `model` / `ops` / `coverage` / `debug` / `audit` | `*.output` | 各 agent 本次运行的产出视图 |
| `ops` | `ops.regression_status`、`ops.regression_wave`、`ops.regression_coverage` | 回归状态、波形、覆盖率产物 |
| `debug` | `debug.sim_log`、`debug.fingerprint` | 仿真日志解析、错误指纹 |
| `coverage` | `coverage.excludes` | 覆盖率豁免审批 |
| `flow` / 工程工作区 | `flow.pipeline`、`flow.diagram`、`flow.task`、`flow.todo`、`flow.runs`、`flow.evidence`、`flow.artifacts`、`flow.fcov`、`flow.drafts`、`flow.compare`、`flow.signoff`、`flow.trend`、`flow.decision`、`flow.manifest` | 闭环编排/流程视图/运行历史/证据/签核/趋势/决策轨迹/运行清单 |

**边界**：`*.output` 是只读视图；`verify.casemodel` 是唯一「界面能力本身即核心」
的模块（12 页嵌在模块内部 QTabWidget，不摊成平台中央标签页，因为它们同属
一份 YAML 的只读视图，拆开就失去"点诊断跳源码"的整体关系）。

## 10. UI 通用件

`ui/` 按组件类别分目录，**不含业务词汇**：

```text
ui/
├─ theme/       palette.py（配色档位 + 领域语义色） / icons.py（按主题色渲染）
├─ models/      Qt 模型：行表 rows.py / 诊断 issues.py
├─ widgets/     横幅 / 面板 / 控制台 / 占位
├─ views/       自绘视图：覆盖条 / 交叉矩阵 / 折线 / 流程图
├─ editors/     YAML 编辑器 + 语法高亮（领域词表由调用方传）
├─ nav/         左窗格导航树（域 → 业务线 → 模块）
├─ containers/  workspace/（MDI + Dock）、empty_state、subwindow、dock
└─ helpers/     表格装配助手
```

主题分四路落地：QDarkStyle 的 QSS（标准控件）、本项目的 `Palette`（自绘控件 +
领域语义）、`_rebrand()`（替换库内编译死的色值）、`QPalette`（样式表管不到的
`Highlight` / `Link`）。`ui/` 不 import `modules/`。

## 11. 项目与隔离

- 「项目」= **一个工作目录**：产物 `output/` 与记忆 `database/*.db` 都相对
  cwd 解析，换目录即隔离，不另造机制。
- 登记表在 `~/.signoffai/projects.yaml`（用户级），可用
  `SIGNOFFAI_PROJECTS` 覆盖；条目缺 `id/root` 跳过，坏表返回空表。
- `--project ID` 在**建窗口之前** `chdir` 并换清单；切换项目需要重启进程
  （`Settings` / `RunService` / sqlite 单例绑定了启动时 cwd）。

## 12. 测试

```bash
python -m pytest src/workbench/tests -q
```

- 测试在 `QT_QPA_PLATFORM=offscreen` 下跑，无需显示器。
- `conftest.py` 的 window teardown 先 `mark_all_clean()` 再 `close()`，
  否则 `closeEvent` 会弹"未保存"模态框，offscreen 下永久挂住。
- 清单解析与工具绑定**不需要 Qt**（`spec.py` / `manifest.py` / `bridge/`
  都不 import Qt），因此这两层可以单独测。
- 关键测试：`test_workbench_manifest.py`、`test_bridge.py`、
  `test_workbench_registry.py`、`test_menu_structure.py`、`test_workspace*.py`、
  `test_theme.py`、`test_nav_pane.py`、`test_casemodel_module.py`、
  `test_casemodel_editor.py`。

当前环境提示：本机 venv 若缺 `qdarkstyle`，工作台测试收集会失败
（`ModuleNotFoundError: qdarkstyle`）；先 `pip install -e .[gui]`
或 `pip install PySide6 qdarkstyle`。

## 13. 扩展点

| 想加什么 | 改哪里 | 不需要改 |
|---|---|---|
| 新模块 | 写 `ModuleBase` 子类 + `bridge/catalog.py` 登记工具 + 清单加 `modules` | `app.py` / `registry.py` |
| 新工具绑定 | `bridge/catalog.py` 加 `ToolBinding`（路径、kind、pure） | 模块调用点 |
| 新总线话题 | `bus.py` 加常量；发布方 `publish`；订阅方在清单 `params.subscribe` | 模块间 import |
| 新通用控件 | `ui/widgets` / `ui/views`（保持无业务词汇） | `modules/` |
| 新主题 | `ui/theme/palette.py` 的 `PALETTES` | 模块（除自绘控件需 `on_theme_changed`） |
| 新项目管理 | `projects.py` 登记表 YAML | 窗口代码 |

## 14. 已知边界

- **清单增删模块/窗格要重开窗口**：「文件 → 重新载入清单」只重新校验并提示，
  不做原地热重载（与其做一套容易出 bug 的热插拔，不如显式重启）。
- **不做 Web UI / SSE / Dashboard**；工作台是桌面外壳，交付仍以 CLI 为准。
- **原理图 / 状态机等占位模块**没有真实数据源；`placeholder: true` 会自动挂
  关不掉的演示横幅。
- **控制台日志上限 5000 行**（仿真日志几十万行，不设上限会吃内存）。
- **长任务不可取消/无进度百分比**：跑起来的 EDA 仿真由 EDA 工具自己决定能否停；
  给一个点不动的取消按钮比没有更糟。
- **切项目需重启**：单例句柄绑定启动时 cwd，热切会留下旧连接。
- **工作台不替流水线做业务判定**：签核、覆盖率、决策结论都来自 run 目录产物；
  工作台只展示与触发，不另存一份"界面结论"。

## 15. 快速文件地图

```text
src/workbench/
├─ __main__.py          python -m src.workbench
├─ app.py               主窗口 / 菜单 / 工具栏 / 启动流程
├─ bootstrap.py         PySide6 可选依赖检查
├─ spec.py              清单契约（pydantic）
├─ manifest.py          读清单 + 人话报错 + 内置兜底
├─ config.py            默认清单 / 输入路径解析
├─ loader.py            "包.模块:类名" 工厂解析
├─ registry.py          ModuleManager：清单 → 视图 / 菜单 / 懒加载
├─ context.py           AppContext：模块能碰到的全部平台能力
├─ bus.py               事件总线
├─ tasks.py             后台任务
├─ settings_store.py    QSettings（几何 / dock / MDI / 主题）
├─ projects.py          ~/.signoffai/projects.yaml
├─ sim_modes.py         仿真业务词条（与 CLI 同源）
├─ manual_gate.py       人工节点开关辅助
├─ bridge/              catalog / binding / adapters（不 import Qt）
├─ ui/                  theme / models / widgets / views / editors / nav / containers / helpers
├─ modules/             design model verify ops coverage debug audit ide flow
├─ tests/               工作台测试（offscreen）
├─ readme.md            使用与上手说明
└─ ARCHITECTURE.md      本文
```

## 16. 工程服务入口（2026-10 调整）

导航改成**两层视角**，但**不新增执行引擎**：

```text
项目（project）
├─ 项目总览            project.overview
└─ 项目管理            project.management

客户工程（service）
├─ UVM 自动化验证      service.uvm
├─ 回归效率优化        service.regression
└─ Coverage Closure    service.coverage

设计时（ide）
工程工作区（flow / ops / coverage / debug）
运行时（design / model / verify / audit）
平台配置（platform）
```

三个入口都是普通 `ModuleBase` 模块（`modules/service/`），只做三件事：
**收参数、调用已有工具/模块、把用户送到专业视图**。它们不复制
`flow.runs` / `flow.evidence` / `ops.regression_status` —— 同一份 run 结果
仍然只有一个模块实例，服务入口通过 `open_module()` 聚焦它。

### 16.1 UVM 自动化验证（`service.uvm`）

内部五步（`QListWidget + QStackedWidget`，不是五个平台模块）：

| 步骤 | 入口做的事 | 复用的现有模块 |
|---|---|---|
| 项目输入 | 选 RTL 目录 / Spec 文件 / case 模型 | `ide.ip_spec`；`pipeline.start(casemodel=…)` 复制到 run 的 `inputs/casemodel.yaml` |
| 验证配置 | 打开 case 模型 / ISA 激励 | `verify.casemodel`、`verify.isa_gen` |
| 环境生成 | 打开验证流程 | `flow.pipeline` |
| 仿真 | 目标/轮次/审批 → `pipeline.start` | `flow.pipeline`、`flow.runs` |
| 交付 | 打开产出/证据/签核 | `verify.output`、`flow.evidence`、`flow.signoff` |

`pipeline.start` 是已有的非纯绑定（`force=True`），启动后立即返回 run_id；
GUI 不等待、不生成本地结论。

### 16.2 回归效率优化（`service.regression`）

- 输入：项目目录 / 历史 run 目录（留空扫 `output_*`）。
- 点击「分析并生成计划」→ `TaskRunner` 后台跑 `src/core/optimize`：
  `collect_history` → `build_plan` → `write_plan`。
- 页面展示 flaky / failing / 慢用例 / 低边际跳过 / 预计节省；**不执行回归**。
  执行仍由 CLI `optimize-regression --execute`（或现有回归执行器）承担。
- 导航按钮打开 `ops.regression_status`、`debug.sim_log`、`debug.fingerprint`、
  `flow.compare`、`flow.trend`、`flow.decision`。

### 16.3 Coverage Closure（`service.coverage`）

- 运行下拉来自 `pipeline.runs`；目标覆盖率可调。
- 「生成 Closure 计划」→ `src/core/closure.write_closure_plan` 读
  `tp_matrix.json` / `coverage_result.json`，写 `<run>/closure/plan.json`。
- 展示当前/目标/缺口/动作表；**不执行仿真**。执行由 CLI
  `coverage-closure --execute` 走现有闭环。
- 导航按钮打开 `ops.regression_coverage`、`coverage.excludes`、`verify.casemodel`、
  `flow.artifacts`、`flow.evidence`、`flow.signoff`。
- 页面明确写出：**豁免 / 达到目标 / 真正收敛是三个不同结论**。

### 16.4 联动与边界

- 三个入口在清单里订阅 `run.selected`：`flow.runs` 选中一次，入口显示当前 run；
  入口启动/选择 run 时也发布 `run.selected`，专业视图跟着切。
- 服务入口与专业模块之间**不 import**，只通过总线话题与文件契约。
- 服务入口**不产生签核结论**：签核只来自 audit 写入的 run 产物与证据包。
- 平台配置（`platform.settings`）只读展示 cwd、清单、Python/Qt、EDA PATH、
  `database/` / `config/`；清单/项目切换仍需要重启。

### 16.5 调整后的清单片段

```yaml
groups:
  - {id: service,  title: 工程服务, order: 1,  section: 客户工程}
  - {id: ide,      title: 集成设计环境, order: 5, section: 设计时}
  - {id: flow,     title: 流程与证据, order: 8, section: 工程工作区}
  - {id: ops,      title: 编译与回归, order: 40, section: 工程工作区}
  - {id: coverage, title: 覆盖率, order: 50, section: 工程工作区}
  - {id: debug,    title: 调试技术, order: 60, section: 工程工作区}
  - {id: platform, title: 平台配置, order: 90, section: 平台配置}

modules:
  - id: service.uvm
    title: UVM 自动化验证
    group: service
    factory: src.workbench.modules.service.uvm:UVMServiceModule
    area: center
    order: 10
    params: {subscribe: [run.selected]}
```
