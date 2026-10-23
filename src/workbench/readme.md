# workbench — 验证工作台

YAML 驱动的 PySide6 桌面平台。**界面清单是 YAML，业务是插件** —— 想知道
「有哪些界面」不用读代码，读 [`config/workbench.yaml`](../../config/workbench.yaml)。

```bash
python -m src.workbench                              # 用默认清单
python -m src.workbench config/workbench.yaml        # 指定清单
python -m src.workbench -m debug.sim_log             # 启动后聚焦某个模块
vagent gui run                                       # 等价入口
```

PySide6 与 QDarkStyle 是**可选依赖**（`pip install -e .[gui]`）：纯 CLI 用法不需要它，没装时
给出装法提示并退出码 2，而不是甩 traceback。

> GUI 走 PySide6 桌面窗口，**不是 Web 前端** —— 与 `CLAUDE.md` 那条禁止 Web
> 前端的约束不冲突（`pyproject.toml` 的 `gui` extra 注释里也写了）。

## 业务线

平台按业务线组织界面，清单里的 `groups` 就是它们。业务线**不占顶层菜单** ——
它们出现在左窗格的导航树、「窗口」菜单的分段里，以及模块动作归到哪个菜单
（`debug` → 调试，其余 → 工具）：

它们分三层 —— **业务域 → 业务线 → 模块**（导航树就这么摊开）：

```
业务域（section）        业务线（group）                    这一段是什么
────────────────────────────────────────────────────────────────────────
设计时                   ide                                跑之前把输入写对
运行时                   design model verify ops            七个领域 agent，
                         coverage debug audit               按流水线顺序
贯穿层                   flow                               横切：编排 / 运行 /
                                                            证据 / 签核 / 跟踪 / 趋势
```

- **域的顺序由「域内最小 order」决定** —— 所以 `ide` 的 `order` 比 `design` 小
  （它是流程的上游），三个域自然按业务流排成"设计时 → 运行时 → 贯穿层"。
- **不写 `section` 的业务线直接挂树根** —— 树退化成两级，老清单照旧能用。
- 一条业务线 = `modules/<id>/` 一个目录。

| 业务线 | `group` | 现在的模块 | 规划中的 |
|--------|---------|-----------|----------|
| 设计构建 | `design` | （暂无） | RTL 与门禁、IP 拆解 / 接口 / 寄存器总览、单 agent 触发 |
| 参考模型 | `model` | （暂无） | 版本列表 / golden_ref / 占位标记 / 回滚 |
| 验证构建 | `verify` | **Case 建模**（12 个页面） | UVM 环境、用例清单、SVA 断言 |
| 编译与回归 | `ops` | （暂无） | 回归结果 / 趋势、失败用例、重跑 |
| 覆盖率 | `coverage` | （暂无） | gap 归因、覆盖率地图、exclude 审批 |
| 调试技术 | `debug` | 仿真日志、错误指纹 | 波形、失败用例二分 |
| 签核审查 | `audit` | （暂无） | 四道门禁 + verdict、signoff 事件 |
| 集成设计环境 | `ide` | **人工节点**（YAML 编辑 + schema 校验） | 源码编辑 + 静态检查、规格→测试计划、UVM 渲染、断言、电路图占位 |
| 流程与证据 | `flow` | **验证流程**、**运行历史**、**证据 / 产物**、**测试点 / 资产**、**签核判定**（门禁 + 证据链）、**进度趋势** | 证据包导出、治理状态、决策轨迹 |

> 为什么是「七条 agent 线 + 横切线」而不是纯七条：证据 / 治理 / 记忆 / 进化不属于
> 任何单个 agent，却贯穿全部 —— 只按 agent 分，这些能力**无边可挂**。完整论证见
> [`docs/design/agent_gui_business_architecture.md`](../../docs/design/agent_gui_business_architecture.md)。

交付分三轮：第一轮是平台本身（清单契约、插件接口、工具绑定、通用控件）加一条
垂直切片；第二轮把 **case 属性完备性建模**从 `casemodel_tools` 的旧界面整体搬进来，
成了 `verify.casemodel` 模块 —— 它是目前唯一一个「界面能力本身就是核心」的模块
（见下节）；第三轮按 agent 角色重构业务线，并补上只读的证据链 / 签核 / 跟踪 / 趋势视图。
其余模块在清单里以注释形式留了位。

## 清单怎么写

清单是**唯一**说明「界面长什么样」的地方。字段定义在
[`spec.py`](spec.py)，键名写错会**启动就报错并点名是哪个字段**
（不是静默忽略 —— 静默忽略会让人以为界面坏了，而其实只是拼错了）。

```yaml
version: 1
window:
  title: "SignOffAI · 验证工作台"
  size: [1520, 940]
  theme: ""              # 留空用平台默认主题（浅色）
  restore_layout: true   # 关窗口时记住窗格尺寸与折叠状态

groups:                  # 业务线（分组用，不占顶层菜单）
  - {id: debug, title: 调试技术, order: 10, menu: true}

modules:
  - id: debug.sim_log            # 唯一 id，也是「窗口」菜单与导航树里的锚点
    title: 仿真日志              # 页签的标题
    group: debug                 # 必须存在于 groups
    factory: src.workbench.modules.debug.sim_log:SimLogModule
    area: center                 # center | left | right | bottom
    order: 10                    # 同区域内 (业务线 order, order, id) 升序
    input: ""                    # 本模块自己的业务输入，相对清单所在目录
    tool: {name: debug.collect_sim_log, kind: json}   # 主绑定
    params: {}                   # 模块自定义配置，模块自己解释
    placeholder: false           # true = 无真实数据源，平台自动挂常驻警示横幅
```

`params.subscribe` 是平台认得的一个约定键：列在这里的总线话题会被接到模块的
`on_refresh`。**订阅写在清单里而不是模块代码里**，是为了让「谁在听谁」读一遍
yaml 就看得清，不用追 import：

```yaml
    params:
      subscribe: [input.changed]     # → 这个模块的 on_refresh 会收到该话题
```

几条约定：

- **`area` 决定模块落在哪块窗格**：`center` / `left` / `right` / `bottom` 对应
  Verdi 那三窗格分割里的位置（right 是第四块，默认没有模块时折叠）。
  同区域的模块天然是**同一块窗格里的页签** —— 不需要额外的「合并」动作。
- **空窗格折叠**：清单里没有 left 模块时，左边不会留一条空白带。
- **控制台与导航树是平台自带的页签**（底部 / 左侧的 0 号），**关不掉** ——
  它们是「发生了什么」与「有哪些界面」这两条常驻信息。
- **`input` 相对路径按清单所在目录解析** —— 把 `config/` 整个搬走，清单里的
  相对引用不会断。
- **`tool.name` 必须是 [`bridge/catalog.py`](bridge/catalog.py) 里登记过的名字**，
  不是 python 路径。绑定表是可审计的；清单里写 python 路径会让人以为可以随便写。

## 加一个模块

三步，不用改平台：

1. 写一个类，继承 `modules.base.ModuleBase`，实现 `build_content()`：
   ```python
   from ..base import ModuleBase

   class MyModule(ModuleBase):
       HINT = "一句话说明这个模块干什么"

       def build_content(self):
           ...                      # 搭控件，只调一次
   ```
2. 在 `bridge/catalog.py` 里登记它要用的工具（如果还没登记）：
   ```python
   ToolBinding(name="debug.my_tool",
               target="src.tools.debug_tools.main:collect_sim_log",
               kind="json")
   ```
3. 在清单里加一条 `modules`。

**不需要**改 `app.py`、`registry.py`，也不需要在任何地方列举模块。

## 模块接口

[`modules/base.py`](modules/base.py) 的 `IModule` 是平台唯一认识的契约：

| 方法 | 作用 |
|------|------|
| `create_widget()` | **必须实现**。建本模块的主控件，只调一次 |
| `build_content()` | `ModuleBase` 的实现钩子：搭内容控件 |
| `create_actions()` | 本模块自有动作（带快捷键），进「调试」或「工具」菜单与工具栏 |
| `on_activated()` | 页签被切到时 |
| `on_theme_changed()` | 主题切了 —— 重挂图标、重画自绘控件 |
| `can_close()` / `mark_clean()` | 有未保存改动时拦住关窗口 |
| `on_input_changed(path)` | 清单的 `input` 或 `--input` 指过来时 |
| `on_refresh(payload)` | 收到订阅事件后（订阅写在清单的 `params.subscribe` 里） |

`ModuleBase` 替子类把三件每次都要做的事做掉了：**顶部横幅**、**工具调用的错误
落点**（`run_tool()` 失败不抛，而是「横幅 + 控制台 + 状态栏」三处都说到）、
以及 `placeholder: true` 时**自动挂上关不掉的警示横幅**（不能靠模块作者记得加）。

## 工具绑定

模块不直接 import `src/tools/**`，而是按名字调：

```python
payload = self.run_tool(output_dir=target)        # 用清单里绑定的主工具
payload = self.run_tool("sim.parse_log", log_text=text)
```

[`bridge/binding.py`](bridge/binding.py) 负责三件事：

1. **惰性 import** —— 清单里列了但没启用的模块，不会因为依赖缺失拖垮启动。
2. **返回值归一化** —— `src/tools/` 里的返回值不统一：`casemodel_tools.api`
   返回真 dict，而 `debug_tools` / `coverage_tools` 这些返回 **JSON 字符串**
   （它们的第一消费者是 LangChain）。界面不该逐个记这件事，`kind` 字段决定。
   **归一化永不抛**：`kind: json` 但拿到非 JSON 时返回 `{"raw": ..., "_parse_error": ...}`
   —— 工具的错误路径常常返回纯文本，那正是最需要显示出来的时候。
3. **非纯工具不许被顺手调用** —— LLM 相关与长任务标 `pure=False`，`call()` 默认
   拒绝执行。否则「切了一下标签页就烧了一次 LLM 调用」迟早会发生。

`bridge/` **不 import Qt**，所以「清单里这个名字绑到了哪个函数、它返回什么」
可以在没有显示器的地方回答。

## 后台任务

编译、仿真、回归不能卡住界面。[`tasks.py`](tasks.py) 的 `TaskRunner` 用
`QThreadPool` + `QRunnable`，结果经主线程的信号发回来：

```python
task_id = ctx.tasks.submit("扫描 output", lambda: ctx.tools.call(...))
ctx.tasks.finished.connect(self._on_done)         # 这个回调在主线程
ctx.console.begin_task("扫描 output")
```

刻意**没有**取消、优先级、进度百分比：跑起来的仿真停不掉（那是 EDA 工具自己的
事），给一个点不动的「取消」按钮比没有更糟。

## Case 建模模块（`verify.casemodel`）

目前唯一一个「界面能力本身就是核心」的模块，也是这套插件化最实的一次检验 ——
它原本是 `casemodel_tools` 包里一个 3142 行的独立窗口（`view/gui/`），第二轮
整体搬进来成了普通模块，**没有为它改动平台一行**。

```bash
vagent gui run -m verify.casemodel
vagent case-model gui [模型.yaml]        # 同一扇门的别名
```

它在回答 case 建模最核心的两个问题：

| 问题 | 在哪一页 |
|------|----------|
| **正交属性怎么 cross** | 「维度交叉矩阵」—— 专题先选范围，`cross_matrix` 再约束这些维度哪些必须一起变（★）、哪些可选（○）、哪些互斥（✗） |
| **覆盖率怎么收敛** | 「取值覆盖」—— 分母是字段声明的取值点，分子是被 case 命中的；缺口按维度列出，联动派生字段单独标灰 |
| **测试点怎么落地** | 「测试点」—— 一条取值点一行，带实现方式（stimulus / sequence / observe）、覆盖仓、回归级；选中运行后叠加 `tp_matrix.json` 的命中状态 |

**12 个页面嵌在模块内部的一个 QTabWidget 里**，不摊成平台的中央标签页。理由是
它们都是同一份文本的只读视图：摊开之后用户能把「概览」拖到别的标签页去，而它
跟「编辑 YAML」本来是一体的（点诊断跳源码靠的就是这个关系）。

为了搬它，`ui/` 补了一批通用件（编辑器、高亮、矩阵、覆盖条、诊断表、面板），
其中两处是**顺手修掉的老问题**：

- `highlighter.py` 原来把 case 模型的骨架键/枚举值**写死在通用高亮器里** ——
  现在这两张词表由调用方传入（`vocabulary.py`），通用层一行领域词都没有。
- `coverage_view.py` 原来把底色写死成 `white` / `#eceff1`（那是照浅色背景调的），
  放到深色主题上会撕出一大块白 —— 现在跟主题走。

## 目录

```
src/workbench/
├─ app.py             QMainWindow：七个菜单 / 图标工具栏 / 三窗格 / 状态栏 / 横幅
├─ spec.py           清单契约（pydantic，extra=forbid）
├─ manifest.py       读清单 + 把 pydantic 错误翻成人话
├─ config.py         默认清单路径 + 业务输入路径解析
├─ registry.py       ModuleManager：ModuleSpec → 窗格页签 / 菜单
├─ loader.py         "包.模块:类名" 工厂解析
├─ context.py        AppContext：模块能碰到的全部平台能力，就这一张清单
├─ bus.py            事件总线（模块之间只通过话题通信）
├─ tasks.py          后台任务
├─ settings_store.py QSettings 包装（几何 / 窗格尺寸与折叠 / 主题）
├─ ui/               通用件 —— 按组件类别分目录（不含任何业务词汇）
│   ├─ theme/            配色（palette.py）+ 图标（icons.py）
│   ├─ models/           Qt 模型：行表（rows.py）/ 诊断（issues.py）
│   ├─ widgets/          通用控件：横幅 / 面板 / 控制台 / 占位
│   ├─ views/            自绘视图：覆盖条 / 交叉矩阵 / 折线
│   ├─ editors/          YAML 编辑器 + 语法高亮
│   ├─ nav/              左窗格那棵导航树
│   ├─ containers/       容器：工作区（MDI 子窗口 + 停靠面板）
│   └─ helpers/          装配助手：表格该长什么样（tables.py）
├─ bridge/           工具绑定：binding / catalog / adapters（不 import Qt）
│   └─ adapters.py   把「吃 JSON 字符串」的工具包成「吃关键字参数」的
└─ modules/          业务模块（目录名与清单的 group 一致）
    ├─ debug/        仿真日志、错误指纹
    ├─ verify/       casemodel/  module.py / page.py / pages/（12 页）/ models.py / vocabulary.py
    ├─ ide/          manual_nodes/  人工节点 YAML 编辑
    ├─ flow/         pipeline / runs / evidence / signoff / tracking / trend + run_common.py
    ├─ agent_output.py   跨线共享：各 agent 的「这次运行产出了什么」视图
    └─ design/ model/ ops/ coverage/ audit/   （每条 agent 线一个目录，待填）
```

依赖只能从上往下：`ui ← bridge ← modules ← registry ← app`。
`ui/` 与 `bridge/` 不认识任何业务；业务词汇只出现在 `modules/` 里。

## 界面形态：像 Verdi

**三窗格无缝分割**（`ui/panes.py`），不是 QDockWidget：

```
QSplitter(竖直)   objectName="pane.outer"
├─ QSplitter(水平) objectName="pane.top"
│  ├─ PaneHost("left")     模块导航树
│  ├─ PaneHost("center")   主工作区（window.center_tabs 就是它的 QTabWidget）
│  └─ PaneHost("right")    默认无模块 → 折叠
└─ PaneHost("bottom")      控制台 + 底部模块
```

为什么不用 Dock：Dock 的标题栏、浮动、拖拽停靠是 **IDE 的形状**，而 Verdi 的窗格
之间只有一条可拖的分割条。两套布局也意味着两套持久化，那是最难维护的状态 ——
所以 `ui/docks.py` 整个删掉了，**不留并行路径**。

代价与对策：`window.saveState()` 只认 QDockWidget，所以布局改成自己存
**每个分割条的尺寸 + 各窗格是否折叠**（`SettingsStore.save_panes/restore_panes`）。

**配色与控件外观交给 [QDarkStyleSheet](https://github.com/ColinDuquesnoy/QDarkStyleSheet)**，
默认「浅色」，另一套「深色」在「视图」里切。它不是"抄了一份 QSS 进来"，而是
一个依赖：`pyproject` 的 `gui` extra 里跟 PySide6 并排。

**整套界面是新思紫**（品牌紫 `#573885` 那一族），不是库默认的灰 + 蓝。

颜色分两张表（都在 [`ui/theme/palette.py`](ui/theme/palette.py)），**都只换颜色、
不换档位** —— 所以"哪块比哪块深"这层关系还是库定的，换色换不出对比度问题：

| 表 | 管什么 |
|----|--------|
| `_SURFACE_SWAP` | 底：菜单栏 / 工具栏 / 状态栏 / 停靠窗标题 / 窗格标题 / 边框 / 表头 / 交替行 / 正文与次要文字 |
| `_ACCENT_SWAP` | 强调：选中底 / 当前行 / 悬停 / 焦点框 / 链接 / 那批强调色图标 |

而颜色在界面上有**四条独立的路**要走到，只改一条就是"一半紫一半灰"：

| 谁 | 管什么 |
|----|--------|
| **QDarkStyle** | 标准控件的样子：按钮 / 表格 / 页签 / 滚动条 / 菜单 / 工具栏 / 输入框… |
| **本项目的 `Palette`** | 只有两类 —— ①**自绘控件**要的底与线（交叉矩阵、覆盖条、折线、源码高亮、导航树着色都是 `QPainter` 画的，QSS 管不到）；②**领域语义**（error/warning/ok、语法高亮九档、矩阵三档底色）—— 后者任何通用主题库都不可能提供，也不跟着品牌走 |
| **`_rebrand()`** | 把库那份 QSS 里**编译死的 hex**（灰阶 + 强调色）换掉，并把引用的强调色图标换成换过色的副本（`_brand_icons`，副本缓存在临时目录，见下） |
| **`apply()` 里的 `QPalette`** | 样式表管不到的那几处取色。库只刷了 `Link`，**选中的 `Highlight` 一直是 Qt 默认的蓝**、`LinkVisited` 是品红 —— 留着它们，界面里就藏着一处非品牌色 |
| **`_app_overlay()`** | 几条以**本工作台自己的 `objectName`** 开头的补充（`#paneHeader` / `#paneHost` / `#mdiArea`），因为库里不可能有这些名字 |

`Palette` 的**档位**（panel/text/border/accent/selection…）是从 QDarkStyle 的
色阶里**读出来的**（`_from_qdarkstyle`）—— 读的是"`COLOR_BACKGROUND_1` 是主背景"
这层语义，颜色过品牌表。库升级重排色阶时，档位名不变，自绘控件与 QSS 仍然对得上。
所以这个类从 60 多个字段砍到了 40 个：原先一半的字段是在手写那套已经不存在的 QSS。

**为什么换色要"替换"而不是"覆盖"**：`qdarkstyle 3.2.3` 的
`load_stylesheet(palette=…)` **只拿 `palette.ID` 选深浅** —— 传进去的类会被换成
它自己的，颜色是 SCSS 编译进 qss 资源的。所以在 `_app_overlay` 里重写
`QTableView::item:selected`、`QToolBar`、`QDockWidget::title` 这一大堆规则，就又是
"一处按钮两处描述"。替换表是**按档位**列的（库的 `Gray.B120` → 我们的
`#e0d6f2`、`Blue.B100` → `#c9aaf6`），两张表加起来十几对，一眼看得全。

**唯一不能靠替换表的地方**是"同一个灰、两种用处"：`::item:selected:!active`
（选中但没焦点）在库里退回中性灰，而同一个灰在交替行、表头、悬停上也在用 ——
全局替换会把它们一起变成选中色。那条按选择器单独改（`_brand_inactive_selection`），
而且**两档合一**：选中了就是紫的，跟焦点在不在无关（点一下导航树，焦点立刻被
中央标签页拿走，按库的规矩那行会当场变灰 —— 品牌色就只在按下的那一瞬看得见）。

三处**必须记着**：

- **`_app_overlay()` 里只准写 `#objectName` 选择器**。一旦写 `QPushButton { … }`，
  就又是"两处各描述一遍按钮"，跟库打架 —— 谁后加载谁赢，升级库时表现会变得
  莫名其妙。有测试钉着这条（`test_overlay_only_touches_our_own_object_names`）。
- **`QPalette` 的角色要自己收编**：富文本链接、少数按调色板取色的控件都不吃
  样式表，而库只刷了 `Link`（还是它那族蓝）—— `Highlight` 一直是 **Qt 默认的
  蓝 `#308cc6`**、`LinkVisited` 是品红。`apply()` 里按品牌色一次设齐
  `Highlight` / `HighlightedText` / `Link` / `LinkVisited`。
- **`QMdiArea`（中央工作区）的底色仍然要显式设**：它抓的是构造时
  `QPalette::Dark` 的一份**快照**，样式表改不动。所以 `WorkspaceArea` 显式
  `setBackground`，换主题时由窗口喊一声 `apply_theme()`。库里那条通用的
  `QAbstractScrollArea { border: 1px; padding: 2px }` 还会顺手给 MDI 加 6px
  内缩，overlay 里也一并抵掉。

换过色的**图标副本**落在临时目录：`<临时目录>/signoffai-theme-icons/<浅色|深色>-<指纹>/`，
连"哪张图带强调色、哪张不带"的清单（`manifest.json`）一起存。指纹含色表 +
认亲容差 + qdarkstyle 版本，所以改了品牌色自然落到新目录，不会读到上一版的旧色图。
它是缓存，随时可以删 —— 删了下次重算：首次约 150ms（要逐像素扫几十张小图），
之后读一次清单即可。

**菜单栏是 Verdi 形的七项**：文件 / 编辑 / 视图 / 调试 / 工具 / 窗口 / 帮助。
业务线**不占顶层菜单**（否则每加一条线菜单栏就长一节），它们的落点是：

- 左窗格的**导航树**（按业务线分组，双击切换模块）
- **窗口**菜单里按业务线分段平铺的模块清单
- 模块动作按业务线进 **调试**（`group: debug`，Verdi 的 Trace 就是这个位置）
  或 **工具**

**工具栏是图标 + 小字**。图标来自 `ui/icons.py`：通用的走 Qt 标准图标，
领域相关的（波形、层次树、重置布局）是内联 SVG，**按当前主题的正文色渲染**
（换主题时 `icons.clear_cache()` 并重挂）。

## 已知边界

- **窗格与页签的增删要重开窗口**。「文件 → 重新载入清单」只重新校验清单并
  提示，不做原地增量更新 —— 与其做一套容易出 bug 的热重载，不如老实说清楚。
- **不做窗格浮动**。Verdi 的 nWave 可以是独立顶层窗口，那是另一个特性
  （需要自己的设计：多窗口、窗口间拖拽、各自的生命周期），本轮不做。
- **原理图与状态机是演示占位**。仓库里既没有网表/原理图读取器，也没有状态机
  提取器，所以这两个视图只能画示意数据。它们的 `placeholder: true` 会让平台
  自动挂一条**关不掉**的琥珀色横幅，界面上再写一遍「演示数据」——
  一条能被习惯性无视的提示等于没有提示。
- **波形不是占位**。`debug_tools/waveform.py` 有真实的 WLF 解析（`wlf2log` →
  `parse_wlf_text` → `extract_signal_trace`），只是需要 QuestaSim 与一个
  `output/**/*.wlf`。第二轮按「真实模块 + 优雅降级」接入。
- **控制台日志上限 5000 行**。仿真日志动辄几十万行，不设上限会把内存吃完。
- **测试跑在 `QT_QPA_PLATFORM=offscreen` 下**（conftest 里设），无需显示器。
  测「有关不掉的模块时关窗口」这类行为要显式调 `manager.mark_all_clean()` ——
  真去 `close()` 会弹模态框，offscreen 下没人点它，测试会永久挂住。

## 测试

```bash
pytest src/workbench/tests -q
```

| 文件 | 覆盖 | 需要 Qt |
|------|------|---------|
| `test_workbench_manifest.py` | 清单解析 / 校验报错点名 / 排序 / 路径解析 / `input` 存在性 | 否 |
| `test_bridge.py` | 绑定表自洽、归一化、非纯守卫、真调一次工具 | **否** |
| `test_ui.py` | 行表模型、排序代理、表格助手、横幅、控制台分级 | 是 |
| `test_workbench_registry.py` | 清单→窗格、**失败隔离**、关窗口闸门、输入载入、布局持久化、两个调试模块 | 是 |
| `test_panes.py` | 空窗格塌陷、页签/标题条互斥、隐藏后再显示回到原位、尺寸与折叠的往返 | 是 |
| `test_nav_pane.py` | 按业务线分组、双击切换、当前模块加粗、失败标灰 | 是 |
| `test_menu_structure.py` | 七个顶层菜单及顺序、模块动作进调试/工具、窗口菜单平铺、窗格开关 | 是 |
| `test_theme.py` | 调色板字段合法、选中色对比度、**样式表 = 库 + 只碰 objectName 的补充**、没有没人用的字段、横幅跟主题 | 是 |
| `test_icons.py` | 图标都渲染得出、缓存按颜色区分、引用的名字都存在 | 是 |
| `test_tasks.py` | 结果回主线程、任务体在别的线程、不阻塞提交方 | 是 |
| `test_casemodel_module.py` | case 建模：领域 Qt 模型、自绘控件、12 个页面都填上、报告与 CLI 一致 | 是 |
| `test_casemodel_editor.py` | YAML 编辑器：**保存不改原文**（`RANDOM` 不被改写成 `RND`）、脏标记、保存前确认、构不出模型时保留上次结果、**刷新不碰文本** | 是 |

后两个是从 `src/tools/casemodel_tools/tests/` 的 `test_gui.py` / `test_editor.py`
迁过来的（界面搬到哪，测试跟到哪）。它们保住的那几条不变式是「原文编辑」这个
设计的全部理由 —— 迁的时候一条都没丢。工具层那三条（`check_text` / 文本入口 vs
文件入口）留在原处，进了 `casemodel_tools/tests/test_analysis.py`。

「清单解析」与「工具调用」这两件事不需要 Qt，是本包一条硬性设计约束
（`bridge/` 与 `spec.py` 一律不 import Qt），也是它能被单独测的前提。
