# casemodel_tools — case 属性完备性建模

把「一个 case 由哪些属性组成」从一个点变成一张可检索、可组合、可扩展的属性表。
传统写法把属性塞进 case 名（`tc_fc_recv_max_len_tail_bp_full_rnd_01`），信息密度高
但无法检索、无法组合、层级错位后必然重复。本工具把属性显式建模，case 由属性组合
**生成**，而不是手写。

理论依据是 [`readem.md`](readem.md)。

## 三层骨架

```
L1 对象 Object（验证主体，用功能组织树描述）
  └─ L2 功能组织树 OrgTree        层级分解，只有叶子生成 case
       ↑ 专题作用于树节点
     专题 Theme                  横切的验证关注点，按 P0/P1/P2 分层
       └─ 维度约束组合            L3 维度 / L4 字段 / L5 方法 / L6 检查
```

**功能组织树**是结构骨架。像 CPU 流水那样分段落，层级由 `children` 表达：

```yaml
sub_objects:
  - {id: STG-01, name: 指令, code: INST, children: [
      {id: STG-01a, name: 控制请求数据/结构仲裁, code: ARB},
      {id: STG-01b, name: 发射解析和启动,     code: DISP}]}
  - {id: STG-02, name: 读数据, code: RD}
  - {id: STG-03, name: 计算,   code: ALU}
  - {id: STG-04, name: 写数据, code: WR}
```

扁平列表是这棵树的特例（所有节点都是叶子），所以只写一层 `sub_objects` 的旧模型
不用改一行 —— `fc_flowcontrol.yaml` 就是这种。

**专题**是横切在骨架上的验证关注点。三类的区别**全由两个字段派生**，不设独立的
`kind` 字段（免得字段说的和标签说的两处打架）：

| | `applies_to` 留空 | `applies_to` 非空 / `["*"]` |
|---|---|---|
| **`dimensions` 留空 / `["*"]`** | 全量随机 | 全维度随机组合（**随机专题**） |
| **`dimensions` 指定** | 正交专题（**错误和异常** / **性能常稳**） | 结构类专题（**P0 配置和参数** / **P1 流控反压 cross** / **P2 边界 cross**） |

`applies_to` 指向**分支**时会自动展开到它的叶子 —— 这是「专题作用于功能组织树」
的核心语义：

```yaml
themes:
  - id: TH-P0-CFG          # 结构类：打树上 5 个叶子（含「指令」展开出的两个）
    name: 配置和参数专题
    priority: P0
    applies_to: [指令, 读数据, 计算, 写数据]
    dimensions: [指令长度, 配置档位]
    method: D
  - id: TH-P1-FC           # 结构类：只打两个叶子
    name: 流控和接口反压 cross 专题
    priority: P1
    applies_to: [发射解析和启动, 写数据]
    dimensions: [反压模式, 反压比例, 反压持续时间]
    method: G
  - id: TH-ERR             # 非结构类：不作用树
    name: 错误和异常专题
    priority: P1
    applies_to: []         # ← 留空 = 不作用于功能组织树
    dimensions: [异常类型, 指令长度]
    method: SPCL
  - id: TH-RND             # 组合类：各维度随机组合
    name: 随机专题
    priority: P2
    applies_to: ["*"]      # ← 全树
    method: RND            # ← dimensions 留空 = 全部维度
```

**然后是维度的约束组合** —— 专题选完范围，`cross_matrix` 再去约束这些维度怎么配：

```yaml
cross_matrix:
  指令长度×反压模式: required      # ★ 必需一起变
  指令长度×反压比例: optional      # ✓ 可选
  反压比例×反压持续时间: forbidden  # ✗ 禁止同时变
```

`forbidden` 是硬约束，优先于专题的 `dimensions`：专题同时列了两个互斥维度是模型
自相矛盾，analysis 报 `theme_forbidden_pair`，生成侧保留先声明的那个、丢掉后一个
并记进 notes（不静默）。

## 目录与设计模式

按依赖方向分层，依赖只能从上往下：

```
casemodel_tools/
├─ schema/case_model.schema.json     JSON Schema 契约
├─ domain/          数据与不变式，不依赖任何 IO
│   ├─ vocab.py         词表与别名归一（唯一的归一化依据）
│   ├─ nodes.py         OrgNode 功能组织树        ← Composite
│   ├─ fields.py        Field + 五种类型化         ← Strategy
│   ├─ dimensions.py    Dimension / CrossPair / CrossGroup
│   ├─ themes.py        Theme（P0/P1/P2，applies_to / dimensions）
│   ├─ cases.py         CaseAttribute / ExternalCase 值对象
│   ├─ model.py         CaseModel 聚合根 + 引用解析
│   └─ errors.py
├─ repository/      取数与落盘                     ← Repository
│   ├─ loader.py        YAML → CaseModel
│   ├─ case_list.py     真实 case 列表 → ExternalCase
│   └─ exporters.py     属性表 → table/yaml/json/csv ← Strategy
├─ generation/      唯一会造 case 的地方
│   ├─ strategies.py    D/RND/G/RPLY/SPCL 五个方法   ← Strategy
│   └─ builder.py       文档十七节的六步流水线       ← Builder
├─ analysis/        只读判断
│   ├─ issues.py        诊断类型与分类
│   ├─ specifications.py 规则基类 + 注册表          ← Specification
│   ├─ rules/           每条规则一个模块（按分类分文件）
│   │   references  orthogonality  org_tree
│   │   themes      cross          coverage  environment
│   ├─ matrix.py        维度交叉矩阵
│   ├─ coverage.py      覆盖数据类型
│   ├─ external.py      真实 case 反向核对
│   ├─ score.py         八项子分加权              ← Strategy（权重集中可审计）
│   ├─ result.py        AnalysisResult
│   ├─ schema_check.py  JSON Schema 门禁
│   └─ facade.py        analyze() 门面            ← Facade
├─ coverage.py      功能覆盖率方法学（覆盖点 → SystemVerilog covergroup）
├─ text.py          只渲染。纯文本报告（CLI 与界面导出共用）
├─ api.py           程序化接口（run_validate/run_gaps/run_generate/run_covergroups）
└─ cli.py           命令行入口
```

> `text.py` 原先在 `view/text.py`。界面搬去工作台之后，「表现层」只剩这一个
> 文件，那一层已经没有存在理由 —— 文件上提到包根，与 `api.py` / `cli.py` 平级。

**本包是纯工具，不含任何面向 LLM 的代码，也不含界面。** 前者在
`src/agents/verify/casemodel/`（见下节），后者在验证工作台
（`src/workbench/modules/vms/casemodel/`，见「界面」一节）—— 分开是为了让工具能在
不装 langchain、**也不装 Qt** 的环境里直接用（`from src.tools.generation.casemodel_tools import api`
就够了）。

依赖只能从上往下：`domain ← repository ← generation ← analysis ← text / cli`。
`text` 不 import `repository`，`domain` 不 import 本包任何其它层。
**反过来也不成立**：本包不 import 工作台，也不 import Qt（有测试用子进程固定
这一点 —— 导入 `cli.py` 与 `api.py` 之后 `sys.modules` 里不许出现 `PySide6`）。

**规则可插拔**是这套结构的主要收益：新增一条校验 = 在 `analysis/rules/` 下写一个
`Rule` 子类并 `@register` —— 报告、界面里的规则页、`rules` 命令三处都从注册表读，
一行都不用改。

## 命令

两个入口，能力等价：`python -m src.tools.generation.casemodel_tools.cli`（独立工具）与
`vagent case-model`（主 CLI）。

```bash
# ── 独立入口 ──
python -m src.tools.generation.casemodel_tools.cli check    config/casemodel/examples/cpu_pipeline.yaml
python -m src.tools.generation.casemodel_tools.cli analyze  config/casemodel/examples/cpu_pipeline.yaml
python -m src.tools.generation.casemodel_tools.cli analyze  config/casemodel/examples/cpu_pipeline.yaml \
    --cases config/casemodel/examples/fc_real_cases.yaml
python -m src.tools.generation.casemodel_tools.cli tree     config/casemodel/examples/cpu_pipeline.yaml   # 组织树 + 专题
python -m src.tools.generation.casemodel_tools.cli matrix   config/casemodel/examples/cpu_pipeline.yaml
python -m src.tools.generation.casemodel_tools.cli rules                                # 规则清单
python -m src.tools.generation.casemodel_tools.cli generate config/casemodel/examples/cpu_pipeline.yaml \
    --format yaml --out cases.yaml
python -m src.tools.generation.casemodel_tools.cli uvm-tests config/casemodel/examples/fc_flowcontrol.yaml \
    --dimension D_ratio --out tests.yaml
python -m src.tools.generation.casemodel_tools.cli covergroups specs/apb_uart/casemodel.yaml -m apb_uart

# ── 主 CLI ──
vagent case-model check    config/casemodel/examples/cpu_pipeline.yaml
vagent case-model analyze  config/casemodel/examples/cpu_pipeline.yaml --cases real.yaml --json
vagent case-model tree     config/casemodel/examples/cpu_pipeline.yaml
vagent case-model rules
vagent case-model generate config/casemodel/examples/cpu_pipeline.yaml -f csv -o cases.csv
vagent case-model uvm-tests  config/casemodel/examples/fc_flowcontrol.yaml -d D_ratio
vagent case-model covergroups config/casemodel/examples/fc_flowcontrol.yaml -m fc
vagent case-model gui
```

退出码：有 error → `1`，模型结构非法 / 文件不存在 → `2`，正常 → `0`。
`check <目录>` 会递归展开 —— 所以 `check config/casemodel/examples/` 也会校验到 `fc_real_cases.yaml`，
那是一份 case 列表而不是模型，报 error 是**正确**行为。

## 一份清单，一个或多个被测对象

顶层有**两种写法**，都能读，且是等价的：

```yaml
object: FlowControl          # 写法一：一份清单 = 一个对象
sub_objects: [...]
dimensions: [...]

tests:                       # 写法二：一份清单 = N 个对象，共享下面那套属性空间
  - {object: FlowControl, object_cn: 流控, object_code: FC, sub_objects: [...]}
  - {object: Arbiter,     object_cn: 仲裁, object_code: ARB, sub_objects: [...]}
dimensions: [...]            # ← 共享的：维度 / 方法 / 检查 / 交叉 / 环境 / 生成参数
themes: [...]
```

写法二的 `dimensions` / `themes` / `methods` / `checks` / `cross_*` / `environment` /
`generation` / `case_defaults` 是**共享属性空间**，被每个对象共用 —— 这正是这个写法
存在的理由：**一套维度空间，测多个对象**（流控、仲裁共用同一批反压属性）。条目里
写了同名键就覆盖共享值。

**合并语义**（产物怎么来）：

| 产物 | 怎么办 | 为什么 |
|---|---|---|
| 交叉矩阵 / 取值覆盖 / 维度级规则 | **算一次** | 只依赖共享的维度空间，对每个对象都一样 |
| 功能组织树 / case / 组织树规则 | **每个对象各一份** | 树是各对象的 |
| 完备性评分 | **一个数** | 评分是**属性空间**的属性，不是某个对象的 |

case 必须在各对象的上下文里生成（`case_id` 是 `TC-<对象代号>-…`，合成一棵树之后
就再也分不出哪个节点属于哪个对象了）。所以 `--max-cases` 是**每个对象各自**的上限，
不是全局的 —— 全局上限会让排在后面的对象被前面的挤光。

`object_code` 撞车**直接报错**（不是警告）：代号进 `case_id`，撞了就会产出重名 case，
而重名 case 在回归结果里是分不开的。

实现落在 `analysis/multi.py`（`merge_models` / `generate_many` / `analyze_many`）与
`repository/loader.py` 的 `models_from_dict`。合并体走原来的 `analyze()` ——
所以矩阵 / 覆盖 / 评分那一路**一行都没改**，变化被吸收在「模型长什么样」这一层，
没有渗进判定逻辑。单对象时 `merge_models` 是恒等，旧写法行为一个字节都没变。

## 示例

| 文件 | 说明 | 分数 |
|------|------|------|
| `cpu_pipeline.yaml` | 五段流水组织树 + 6 个专题（P0/P1/P2，含非结构类与随机），218 个 case | **93.8** |
| `cpu_pipeline_flawed.yaml` | 组织树 / 专题层的坑：叶子代号重复、子树死结构、优先级空洞、专题重叠、SPCL 推不动边界、专题选了互斥维度 | **46.7** |
| `fc_flowcontrol.yaml` | 流控，扁平子对象 + 交叉组（**没有专题层**）。用 `tests:` 写法列对象（当前只有一个）。因为缺整个专题层，分数明显低于 cpu_pipeline | **77.8** |
| `fc_flawed.yaml` | 维度层的坑：把字段当维度、把方法当维度、把检查当对象… | **22.6** |
| `fc_real_cases.yaml` | 外部真实 case 列表，注入 7 类缺陷供 `--cases` 演示 | — |

`fc_flowcontrol.yaml` 是**刻意保留的老写法**：只写一层 `sub_objects`、不声明 `themes`。
它照常工作（生成退化为按交叉组），但分数会因「缺专题层」掉下来 —— 这正好演示了
新模型比旧写法多出来的那层价值。要迁移，把它按流水/能力点加上 `children`、
再按 P0/P1/P2 补上 `themes` 即可。

## 校验规则（53 条）

规则清单从注册表生成（`rules` 命令 / GUI 规则页），这里只给分类概览：

| 分类 | 条数 | 抓什么 |
|------|------|--------|
| 引用完整性 | 8 | 悬空引用：节点 / 维度 / 字段 / 专题 / 交叉组，以及代号推导的提示 |
| 层级正交性 | 12 | 文档十八、十九节四类错位，外加重名、重复取值、维度无变化 |
| 功能组织树 | 4 | 叶子代号重复（case_id 会撞车）、叶子零覆盖、子树死结构、扁平树提示 |
| 专题 | 9 | 优先级空洞、专题重叠（会同节点同维度同方法产重复 case）、维度未被任何专题选中、SPCL 推不动边界、选了互斥维度、空专题 |
| 维度交叉 | 6 | 声明与交叉组级别冲突、禁止交叉被塞进必需组、组维度不足、规模爆炸、维度未参与交叉 |
| 取值覆盖 | 4 | 逐维度取值缺口、字段名重复导致统计串味、零 case、生成过程注意事项 |
| 环境与检查 | 8 | 环境指纹缺失 / 无缺省 / 未登记键、检查项缺失 / 未使用 / 建议 |
| 真实 case 核对 | 12 | 模型落后于实现、实现落后于模型、重复、命名、缺指纹、节点/专题零覆盖 |

```bash
python -m src.tools.generation.casemodel_tools.cli rules          # 全部列出
```

## 第五块：真实 case 反向核对（`--cases`）

前七类规则都是「模型对自己」——生成 case，再拿生成的 case 量模型。这一块换方向：
拿**真实存在的 case 列表**去量模型，回答四个问题。

```
真实 case 核对 —— 源 config/casemodel/examples/fc_real_cases.yaml
──────────────────────────────────────────────────────────────────────────────
  真实 case 数     : 45
  真实取值覆盖     : 43.5%     （模型生成覆盖 87.0%）
  重复 case        : 4 组
  缺环境指纹       : 1
  模型落后于实现   : 1 个未声明字段 + 1 个未声明取值 + 0 个未声明专题
  实现落后于模型   : 10 个取值

  注：真实 case 的缺陷不计入模型完备性评分 —— 评分必须只是模型的属性，
      否则换一份 case 列表分数就变，不再可复现。
```

**输入的四种形状**与 `generate --format` 的输出同构，所以「生成 → 落盘 → 核对」
可闭环（有往返测试固定这一点）：`{cases: [...]}` / 裸列表 / 单条 / `.json` / `.csv`。

**为什么评分不计入真实 case 的缺陷**：完备性评分必须只是模型的属性。若把「实现
落后」也算进去，同一个模型传两份完整度不同的 case 列表就会得到两个分数，分数不再
可复现 —— 与项目「可复现」定位直接冲突。所以两边分开报：模型分一个数，真实覆盖
另一个数。外部 error 仍会让退出码变 1（你既然要了核对，它的结论就该影响命令成败）。

## 评分

八项子分加权成 0~100，权重集中在 `analysis/score.py`：

| 评分项 | 权重 | 依据 |
|--------|------|------|
| 分层完备 | 0.15 | 八层（对象/组织树/专题/维度/字段取值/方法/检查/环境）是否都有实质内容 |
| 引用完整 | 0.12 | 悬空引用条数 |
| 层级正交 | 0.16 | 错位规则的严重度加权 |
| 组织树 | 0.12 | 叶子被专题覆盖的比例；代号重复一票重扣 |
| 专题 | 0.15 | 维度被专题选中的比例 × 优先级阶梯完整性 × 专题自身问题 |
| 维度交叉 | 0.10 | 声明比例 × 参与度 |
| 取值覆盖 | 0.15 | 命中取值点 / 总取值点 |
| 环境与检查 | 0.05 | 必需环境键落到 case 的比例 × 检查项覆盖 |

**每一项扣分都带理由**（`score.row_reasons()`）—— 分数如果不能解释就没法行动。
有测试固定「扣了分必须给理由」。

## 界面（验证工作台）

界面**不在这个包里** —— 它搬进了验证工作台，成了 `vms.casemodel` 模块
（`src/workbench/modules/vms/casemodel/`）。工作台自带主题、Dock、控制台、
状态栏与其它业务线，界面待在那边才不用把这些各写一遍。

```bash
vagent case-model gui                              # 打开工作台，落在 case 建模模块上
vagent case-model gui config/casemodel/examples/cpu_pipeline.yaml   # 直接打开某份模型
vagent gui run -m vms.casemodel                    # 等价写法
# 不传模型 → 清单里的 input（config/casemodel/examples/cpu_pipeline.yaml）会被自动载入
```

十一个页面嵌在模块内部的**一个 QTabWidget** 里，第一页是**编辑 YAML**：编辑 YAML、
概览、组织树 / 专题、层级正交性、维度交叉矩阵、取值覆盖、环境与检查、Case 属性表、
真实 case 核对、Schema 校验、规则清单。快捷键 **Ctrl+O** 打开、**Ctrl+S** 保存、
**Ctrl+R** 重新分析 —— 由模块自己的 `QAction` 绑，所以跟焦点在哪个控件无关。

搬走之后本包**完全不依赖 Qt**：纯 CLI 用法（`check` / `analyze` / `generate`）的
安装里不会出现 PySide6，工具自己的测试也不再有「没装 Qt 就跳过」的用例。
本包的 CLI **没有** `gui` 子命令 —— 工具只有 check / analyze / matrix / tree /
rules / generate 六个。`vagent case-model gui` 仍在，但那属于主 CLI
（`src/cli/commands.py`），它直接调工作台，不经过本包。

### 这个模块在回答什么

case 建模的出发点是「**case 由属性组合生成，而不是手写**」：传统写法把属性塞进
case 名（`tc_fc_recv_max_len_tail_bp_full_rnd_01`），信息密度高但无法检索、无法
组合、层级错位后必然重复。属性显式建模之后，两个最核心的问题变成可操作的：

| 问题 | 在哪一页 |
|------|----------|
| **正交属性怎么 cross** | 「维度交叉矩阵」—— 专题先选范围，`cross_matrix` 再约束这些维度哪些必须一起变（★）、哪些可选（○）、哪些互斥（✗）；下面那张表估这一轮会跑出多少 case |
| **覆盖率怎么收敛** | 「取值覆盖」—— 分母是字段声明的取值点，分子是被 case 命中的；缺口按维度列出，联动派生字段单独标灰（它不是真缺口） |

### 编辑 YAML

**为什么是文本编辑器而不是表单编辑器**：分析管线是 `YAML → CaseModel`，归一化是
**有损的** —— 注释、键顺序、别名写法都会变（`RANDOM` 会被改写成 `RND`）。若从解析
后的模型重新生成 YAML 再写盘，你写的注释就没了。所以编辑的是**原文**，保存时原样
写回。有测试固定这一点：`test_save_preserves_raw_aliases` 断言保存后磁盘上仍是
`RANDOM` 而不是 `RND`。

> 顺带一条一致性约定：**别名（`随机` / `RANDOM`）在 schema 层也是合法的**。
> 归一化层认它们，schema 若判它们非法，「这个模型合法吗」就会有两个答案 ——
> 这正是本项目一直在避免的「两处真相」。

**真相只有一个，就是这段文本**；其它页面都是它的只读视图。由此推出三条行为：

| 行为 | 为什么 |
|------|--------|
| 「重新分析」分析的是**编辑器里的文本**，不重读文件 | 改一行就能立刻知道坏了哪条规则，不必先保存 |
| 保存后**自动**重新分析并刷新全部页面 | 保存即校验、保存即生效 |
| 文本构不出模型时，**保留上一次的结果** + 挂红条说明 | 改到一半看到一片空白，会让人以为工具坏了 |

保存前会跑 schema 校验；有 error 时先弹窗问「仍然保存吗」，答「取消」就不写盘
（`test_save_asks_before_writing_schema_errors` 固定）。有未保存改动时，打开别的
文件或关窗口都会先问一句 —— 关窗口那条走平台的 `can_close()`，标题上的 ● 挂在
**模块自己的标签页**上（同时开着几个模块时，得看得出是哪一个没存）。

> **为什么是桌面 GUI 而不是 Web**：`CLAUDE.md` 明确禁止 Web 前端开发。
> PySide6 是桌面窗口（Qt），不是前端页面 —— 与那条约束不冲突。

## Agent 接入面

在 **`src/agents/verify/casemodel/`** —— 归 verify 角色，因为 casemodel 产出的是
测试计划 / case 属性表，消费它的是会生成 UVM + 测试 + 断言的 verify 角色
（该角色已经在 import `testcase_tools`）。

```
src/agents/verify/
├─ main.py              VerifyAgent
└─ casemodel/           ← 本工具的 Agent 适配器
    ├─ langchain_tools.py
    └─ registry.py
```

| 接入面 | 位置 | 用途 |
|--------|------|------|
| LangChain `@tool` | `casemodel/langchain_tools.py` | 用 `_lc_tool_compat.tool`，langchain-core 1.x 下仍可直接调用 |
| 声明式 `ToolRegistry` | `casemodel/registry.ensure_casemodel_tool_registry()` | 由 `layers/.../agents/agent_tools.py` 汇总，BaseAgent 据此 wrap + 校验 |
| `ToolHub` 的 `ITool` | `casemodel/registry.register_casemodel_tools(hub)` | 带 manifest / 风险等级 / 审计追踪 |

三个面**共用 `casemodel_tools.api` 的实现与 `tool_specs()` 的工具名**，
所以不会各给一个答案（有测试固定）。

**为什么把适配器移出工具目录**：仓库里旧的做法是「工具的 LLM 代码就放在工具文件夹里」
（`uvm_tools/agent_tools.py`、`testcase_tools/tools.py`），结果是「49 个 `@tool` 只注册了
29 个」（见 `docs/design/full_project_refactoring_plan.md`）。工具与接入面分开之后：

- `src/tools/generation/casemodel_tools/` 零 LLM 依赖，脚本 / 测试 / 别的工具可以直接 import
- LLM 包装集中在 `src/agents/`，与项目「Agent 按角色分」的结构一致

| 工具 | 用途 |
|------|------|
| `casemodel_validate(yaml_text)` | Schema 校验结果 |
| `casemodel_gaps(yaml_text, max_cases=None, cases_text=None)` | 全量完备性分析；给 `cases_text` 时追加反向核对 |
| `casemodel_generate(yaml_text, max_cases=None, seed=None)` | case 属性表 |
| `casemodel_uvm_tests(yaml_text, dimensions=None, max_tests=None)` | UVM 的 `environment.tests` 片段（见下） |

## 属性 → UVM TEST（`uvm-tests`）

**一条 = 一个 UVM_TEST = 一个属性取值**。这个命令把模型里每个维度的取值点摊平成
`tool_uvm` 的 `environment.tests` 片段，贴进 env 清单的 `environment:` 下，
生成的 test class 里就有 `uvm_config_db#(int)::set(..., "<key>_int", <取值>)`。

```bash
python -m src.tools.generation.casemodel_tools.cli uvm-tests \
    config/casemodel/examples/fc_flowcontrol.yaml --dimension D_ratio
# → 4 条（0/10/50/100），key=d_ratio
```

**与 `uvm_tools` 之间只有「文件格式契约」，没有 import**（本仓库的规矩是工具互不
依赖；有测试用子进程钉住）。所以换个 UVM 模板不用改这个工具。

两处设计取舍：

- **机器通道是 `int`，中文取值只进注释**。维度 id 是 ASCII（`D_mode`）但取值
  token 常是中文（`首拍`）。把非 ASCII 塞进**会被比较、被打印**的 SV 字面量是
  locale 隐患，所以取值投影成 int（数字本身，非数字用下标），中文值作为注释保留
  —— 类名也走同一投影（`d_mode_p1`），保证全 ASCII。
- **截断不静默**：`--max-tests` 超限时 `truncated` / `dropped` / `notes` 都记账，
  且优先保留**边界取值**。注意边界是跨维度按声明顺序挑的，想只要某一个维度的
  边界值要同时给 `--dimension`。

风险等级一律 `safe`（纯计算，不写盘、不起子进程）。按 ADR-3 的凭证约定，
`verified_by` 是 `"none"` —— 确定性工具本身无「外部验证」概念，但结论由输入 YAML
唯一决定，所以可复现。工具名用下划线而非 `a.b` 点号：点号会被带进 OpenAI
function-calling 的 `function.name`，那是非法字符（有测试固定）。

## 功能覆盖率方法学（`covergroups`）

模型建的是"该测什么"，回归跑的是"用例"，而**签名要看的是"打到了没有"**。
这三件事之间原来缺一段：模型里的覆盖点从来没变成过一条真的 SystemVerilog
covergroup。这一节是那段转换的规则，实现只有一处 ——
`src/tools/generation/casemodel_tools/coverage.py`（模块头与本节同源）。

### 规则

| 模型里的东西 | 变成 | 为什么 |
|---|---|---|
| 一个 `CaseModel` | **一个** `covergroup cg_<module>` | `cross` 要求两个 coverpoint 同作用域，所以合一个而不是每维度一个 |
| `Dimension` | 一组 coverpoint（它的每个字段一个） | 维度只归类、不承载取值 |
| `Field` | `coverpoint <field.name>` | **字段名就是接口信号名**（`front` 从 spec 的 interfaces 取） |
| `ValuePoint` | 一个 `bins` | 取值点就是覆盖分母的刻度，一比一 |
| `Field.cover_bins` | bin 的**名字** | 作者能命名就让作者命名 |
| `CrossPair`（`required`/`optional`） | `cross cp_a, cp_b;` | 声明了要一起组合就该有 cross；`forbidden` 是**禁止**组合，不生成 |
| `CrossPair.bins` / `.illegal` | `binsof(...)` 过滤交叉 / `illegal_bins` | 全交叉是乘积（4×4 = 16），关心的往往四五个；非法组合不写就该**报错**而不是被统计成合法状态 |
| `Field.cover_id` / `.requirement` | （不进 SV） | 追溯矩阵的两端：`CP_NPU_xxx` 给人对账，`cp_<信号>` 给编译器 |
| `Field.cover_illegal` | `illegal_bins x = {[33:$]};` | 命中即报错 |

### 三条纪律

**一、生成的 SV 必须能编译。** 取值的字面量走**整型投影**（与 `uvm-tests` 的
`int_value` 同一套）：取值本身是数字就用它，否则用下标。中文取值直接写进
`bins x = {首拍};` 是语法错误；投影成下标则合法，原取值以注释留在旁边
(`bins b_0 = {0}; // 首拍`)—— 语义没丢，编译器也没炸。bin 名同理走 ASCII 化，
全非 ASCII 的取值退到 `b_<下标>`（折成空串会得到 `bins b_ = {0};`，那是个
**非法标识符**，要到 `vlog` 才炸 —— 实测踩过）。

**二、算不出来就说出来。** 字段一个取值点都没有、`cross` 引用的维度解不出来、
取值点超过 `MAX_BINS_PER_POINT` —— 都进 `notes` 记账，**不静默跳过**。
一个"看着生成了、其实少了一半 bin"的 covergroup 比一个报错的更坏。

### 写法：取值点、显式仓、非法仓

三条路，从粗到细（**同一条覆盖点只能选一种**，都写时以显式仓为准并记账）：

```yaml
# ① 取值点 —— 一个取值点一个仓（默认）
- name: instr_type
  type: enum
  values: ["MAC", "VECTOR", "SCALAR", "DMA"]
  cover_bins: [mac, vector, scalar, dma]     # 字符串 = 给第 i 个取值点命名

# ② 显式仓 —— 仓**不必**是取值点。值域的一个划分只能这么写
- name: queue_level
  type: range
  min: 0
  max: 32
  cover_bins:                                 # 对象 = 定义一个仓
    - {name: empty,     at: 0}                #   bins empty = {0};
    - {name: low,       range: [1, 7]}        #   bins low = {[1:7]};
    - {name: full,      at: 32}
  cover_illegal:
    - {name: illegal_over, from: 33}          #   illegal_bins illegal_over = {[33:$]};

# ③ 过滤交叉 —— 只交叉有意义的那几对
cross_matrix:
  D_type×D_unit:
    level: required
    bins:
      - {name: mac_to_mac, when: {instr_type: mac, issue_unit: mac}}
    illegal:
      - {name: mac_to_dma, when: {instr_type: mac, issue_unit: dma}}
```

**为什么需要 ②**：`queue_level` 的 0–32 要分六档，其中三档是**区间** ——
"值域的一个划分"用取值点表达不出来。**为什么需要 ③**：全交叉的仓数按乘积涨
（4×4 = 16，而关心的往往四五个）；更要紧的是**非法组合** —— 不写 `illegal` 的话，
`mac` 指令发到 `dma` 单元会被全交叉当成一个**正常状态**统计，那等于在说它合法。

`when` 里的值**写 bin 名或取值 token 都认**（`mac` 与 `MAC` 等价）；写了个
两边都对不上的名字会**记账跳过**，不会默默生成一个 `binsof(cp.nope)`
（那要么编译不过，要么被当合法语法收下却永远不命中）。

**三、每个 bin 必须至少有一个取值点能打到。** 这是"激励侧与度量侧同一份分母"
的**准确说法**（不是"一比一"—— 给了显式仓时天然多对一）：

```
用例按 field.value_points() 生成（一个取值点一条 test）
覆盖率按 bins 收（一个仓可能盖住好几个取值点）
```

多对一无害，**空洞致命**：某个仓一个取值点都打不到 → 声明的覆盖率**永远封顶**，
而 covergroup 编译通过、回归跑得过、日志一切正常。由 `run_gaps` 的
`cover_bin_unreachable` 拦。

实测踩过：`cluster_id` 写了 4 个显式仓（`c0..c3`）却**没给 `boundary`** ——
`RangeField` 退化到 `[min, max]` 两个取值点，于是 c1/c2 永远打不到、覆盖率
封顶 50%，而模型、covergroup、日志看上去全都正常。

### 需求追溯

```yaml
- name: queue_level
  cover_id: CP_NPU_QUEUE_001      # 文档里的覆盖点编号（给人）
  requirement: REQ-NPU-001        # 需求编号（追溯矩阵的另一头）
```

生成器派生的名字是 `cp_<信号名>`（给编译器），编号是**文档里的那个**（给人对账）。
两者都进 `coverage_points.json` 与运行级 manifest，所以「哪条需求被谁验了」这条链
（需求 → 覆盖点 → 用例 → 实测命中）是机器可读的。

### 命令

```bash
python -m src.tools.generation.casemodel_tools.cli covergroups \
    specs/apb_uart/casemodel.yaml -m apb_uart
# 3 覆盖点 / 10 bin / 0 cross

python -m src.tools.generation.casemodel_tools.cli covergroups \
    specs/npu_sched/casemodel.yaml -m npu_sched
# 12 覆盖点 / 59 bin / 7 cross（含 binsof 过滤交叉与两级 illegal_bins）
```

主 CLI 同形：`vagent case-model covergroups model.yaml -m apb_uart`。

### 放哪一份、谁优先

`layout.find_case_model` 是**唯一**的判据（原来 verify 与覆盖率侧各读一份，
同一个 run 里两次拿到不同的模型而都不报错）：

| 优先级 | 位置 | 谁写的 |
|---|---|---|
| 1 | `spec["case_model"]` | 设计阶段产出时给的路径 |
| 2 | `specs/<模块>/casemodel.yaml` | **人写的**（放在 spec 旁边，最自然的位置） |
| 3 | `config/casemodel/<模块>.yaml` | 人写的（项目级常备） |
| 4 | `<run>/inputs/casemodel.yaml` | **front 的草稿**（自动生成，兜底） |

**人写的优先于草稿** —— 手写模型是对这份规格的建模结论，草稿只是"没有模型时的
起点"。选了哪一份会打进日志（`case 模型：<路径>`），因为它从运行结果上看不出来。

### 真模型：`specs/npu_sched/casemodel.yaml`

把一份《NPU 指令调度器功能覆盖率计划文档》落成模型的样板，也是**唯一**同时用上
上面全部写法的那份。逐节对应：

| 文档 | 落成 |
|---|---|
| §3.1 的 12 个 CP | 12 个 `dimensions`（一个 CP 一个维度） |
| §3.2 的 `bins` / `illegal_bins` | `cover_bins`（显式仓）/ `cover_illegal` |
| §3.3 的 `X_*` 交叉 | `cross_matrix`（`binsof` 过滤 + `illegal`） |
| §5.1 的 11 个批次 | `themes`（`priority` 是分级回归那四级，批次号写进 `name`） |
| §8 的 CP / REQ 编号 | `cover_id` / `requirement` |

**不进模型的**：§4 的约束、§6 的种子基线、§7 手写的 covergroup —— 那是激励层与
实现层，不是"该测什么"。

### 三层模型 + 分散引用关联（`associate`）

case / 功能覆盖率 / 约束是**三份 yaml**，各答一个问题：

| 文件 | 答什么 |
|---|---|
| **case 模型** `cases.yaml` | **该测什么**：dimensions/values（取值空间）、themes（专题＝批次＋种子）、cross_matrix、`cover_bins`（bin 名**引用**） |
| **覆盖率模型** `coverage.yaml` | **怎么量**：coverpoints（signal + bins）、crosses（`matrix_ref`） |
| **约束模型** `constraint.yaml` | **怎么驱动**：transactions（端口→seq_item）、policies、combinator |

**关联靠名字，不靠位置**（也没加第四份"关联表"—— 那是第四份真相，改了名没人报）：

```
① case.field.cover_bins  ──bin 名──►  coverage.coverpoints[].bins[].name
② case.cross_matrix 键   ──矩阵键──►  coverage.crosses[].matrix_ref
③ 约束.policies[].applies_to ──端口──► 约束.transactions[].name
④ case.themes[].method   ──映射──►   约束.combinator / policies
⑤ 约束.policies[].dimensions ──维度 ID──► coverage.coverpoints[].dimension
```

①② 是**硬边**（error）—— 断了就是"声明的测试点没落成覆盖仓"/"组合关系没被覆盖"；
③④⑤ 是**软边**（warning）。

**为什么要有 ⑤**：前四条只连成一个 "V"（case↔coverage、case↔约束），
**coverage↔约束之间一条边都没有** —— 于是"这条策略驱动的维度到底有没有人量它"
没人答得了。⑤ 用 **dimension ID** 把三角形闭合：case 模型的 `dimensions[].id`
是两边共用的命名空间（覆盖率侧 `coverpoint.dimension`、约束侧
`policy.dimensions`）。**它不追端口名，改追维度 ID** —— 端口↔信号的对应没有
建模（见下），追不了；维度 ID 有。

两处必须归一（实测都踩过）：专题的 `dimensions` 写的是**原始引用**（`指令类型`
这种 name 也行）而覆盖率侧是 `D_type`，得归到 canonical key；
`dimensions: ["*"]` 的语义是**全部维度**，得展开 —— 否则所有维度都会被报成
"没人驱动"。

```bash
python -m src.tools.generation.casemodel_tools.cli associate cases.yaml coverage.yaml [-c constraint.yaml]
# 主 CLI 同形：vagent case-model associate
```

**为什么边 ① 靠 bin 名而不是字段名**：

```
case 模型： fields[].name: 指令类型      ← 建模概念（人可以写中文）
coverage ： signal: instr_type          ← 实现名字（DUT 的端口）
```

它们**本来就不该同名**。实测踩过：按名字找字段 → 全落空 → 取值全投影成 0，
而编译不报错（每个 bin 收的都是 0）。真正的桥是 `cover_bins` 的名字。

**两条纪律**：

- **查"作者声明了什么"要读原始 yaml**，不读解析后的产物 —— 解析会把坏条目丢掉
  （取值解析不了、交叉引用了不存在的 coverpoint），从产物上看不见它们，会让别的边
  报一串**级联误报**（实测：3 个交叉被丢，边 ② 一口气报 6 条"没人引用"）。
- **有 error 就不许渲染 SV**（`renderable: false`）—— 取值投影不出来时给个 0 让 bin
  照生成，收的是**错的数**，比生成不了更坏。

### 约束模型生产者（`constraints`）

`associate` 只**报**边 ④（"专题声明的方法没有对应的约束层形态"）—— 报完还得人去手写
约束模型。这个命令把链路补上：`themes[].method` → `policies` + `combinator`。

```bash
python -m src.tools.generation.casemodel_tools.cli constraints cases.yaml \
    -p apb_master:APB_master_seq_item -o constraint.yaml
# 主 CLI 同形：vagent case-model constraints cases.yaml -p apb_master:APB_master_seq_item
```

产物正好是 `gen_uvm.parse_constraint_model` 认的形状（顶层 `constraint` /
`transactions` / `policies` / `combinator`）—— 丢进它扫描的输入路径就渲染出
`env/cons/` 那 5 个文件（**文件名不参与识别**，认的是顶层那个 `constraint:` 键）。

| 方法 | 策略名后缀 | 组合器模式 |
|---|---|---|
| `D` 定向 | `_directed` | `APPLY_FIRST_MATCH` |
| `G` 组合 | `_combo` | `APPLY_ALL` |
| `SPCL` 专项 | `_special` | `APPLY_SEQUENTIAL` |
| `RND` 随机 | `_random` | `APPLY_WEIGHTED` |
| `RPLY` 回放 | `_replay` | `APPLY_SEQUENTIAL` |

`default_mode` 取**优先级最高那个专题**的方法（P0 在前）—— 出厂行为要跟最该先测的那批
一致，取最松的（一律 `APPLY_ALL`）会让定向批次在默认配置下不再定向。`priority` 在那套
渲染里是**两用的**（`sort_by_priority` 升序 → 小的先应用；`select_weighted` 又拿它当权重
→ 大的更容易选中），P0 取小值在两处都合理。

**它是骨架，不是最终约束**：case 模型有建模语义（专题/维度/方法/优先级），没有协议参数
（地址对齐/容量/握手时序）—— 所以 `params` 为空、策略体是空 `apply`，`gen_uvm` 的语义
校验会逐条提示 `policy 'xxx' has no built-in apply body（自定义逻辑需手填）`。
**结构由工具给，协议由人给**；逻辑补在 `env/cons/` 的策略里（不在这个 yaml，所以重跑
覆盖它是安全的）。

**策略带 `dimensions`**（它驱动哪些维度）—— 那是 `associate` 边 ⑤ 的桥墩，
归一到 canonical key 并把通配 `"*"` 展开（见上一节）。

**在流水线里它是自动生成的**（`verify` 阶段）：`find_spec_yaml` 之后、
`jinja_render` 之前，verify 从 env.yaml 的 agents 推端口 → `build_constraint` →
落 `inputs/yaml/uvm/constraint.yaml`，与 env.yaml 在同一次 `run()` 里渲染出
`env/cons/`。**端口从 `type` 推、不是从 `name`**（`npu_sched_in_master_agent`
→ `npu_sched_in_master_seq_item`；照 `name` 拼出来的类不存在，而错要到 vlog 才报）。
CLI 手跑那条路仍在，两条同一份实现。

⚠️ **策略体目前是空的**：`env_cons_policies.sv.j2` 的 `case (policy_name)` 分支来自
内置名单（`semantic_check.BUILTIN_POLICIES`，8 个**主题名**），与本工具推出来的
`p_th_b02_random`（专题 + 方法）**一个都对不上** —— 于是那个 `case` 一个分支都没有。
**空 `case` 不是"什么都不做"，是 `vlog-13302` 编译错误**（实测 11 策略 = 11 条 error），
所以模板留了一个 `default:`。要让约束真生效，得把内置分支补成按 method 派生的那五类
（`directed` / `combo` / `special` / `random` / `replay`）——**这一条还没做**。

**端口必须显式给**（`-p name:type`，可重复）：case 说字段名、约束说 agent 名 + seq_item
类型，端口名 ↔ 字段名的对应**没有建模**（就是边 ③ 只查得到一半的那半个），推不出来。
**没给端口就不生成** —— 空的 `transactions` 渲染出来的协调序列是个**空壳**（`{% for
trans in transactions %}` 一次都不进，发送循环体是空的），那正是这个仓库最贵的一类 bug。

**失败响亮**：认不出的端口写法、重复端口、认不出的 `method` —— 一律报错拒绝生成，不跳
不猜（跳过就是"给了 3 个端口、生成出 2 个"，而没人会去数）。`METHOD_TO_POLICY`（机器用）
与 `METHOD_TO_CONSTRAINT`（人读）的键集由单测钉住：漏一个的后果很具体 —— `associate`
认得那个方法（不报警），生产者却映射不出策略（拒绝生成）。

### 功能覆盖率计划（`coverage-plan`）

**一份 yaml，与 case 模型同批生成**，把覆盖这件事的四张脸摆在一起：

| | 内容 | 谁读 |
|---|---|---|
| §3 覆盖点 | 谁在采、采什么、bin 是什么、非法仓有哪些 | 生成 covergroup 的人 |
| §5 批次 | 这一批打哪个专题、跑哪个 **test** | 回归 |
| §6 种子管理 | 每一批跑几条才算数（`base` / `count` / `explore`） | 回归 |
| §8 需求追溯 | `REQ-xxx ↔ CP_xxx / X_xxx ↔ 批次` | 签核的人 |

```bash
python -m src.tools.generation.casemodel_tools.cli coverage-plan specs/npu_sched/casemodel.yaml -m npu_sched
# 12 覆盖点 / 59 bin / 7 cross / 11 批次 / 共 195 次运行
```

**为什么要一起生成**：它们同源（都从同一份 case 模型派生），分散在三四个文件里
对账很痛苦 —— 尤其「声明了 12 个覆盖点、回归里只跑了 8 条」这种事，只有把两边
摆在一张表上才看得出来。落盘在 `<run>/coverage/coverage_plan.yaml`（verify 阶段，
与 DUT 探针同一批）。

**种子管理写在专题上**（批次就是专题）：

```yaml
themes:
  - id: TH-B02
    test: npu_type_test
    seeds: {base: 2001, count: 15, explore: 3}   # 跑 15 条基线 + 3 条探索
```

**批次也要有 test 类**（`environment.batches` → `{env}_batch_test.sv`）：

```systemverilog
`GEN_BATCH_TC(npu_type_test, npu_sched_env_gen_test, "TH-B02", "D_type", "RND", "P0")
// 类体只把"这一批打哪几个维度、用什么方法"挂上 config_db —— 消费方（sequence）读它
```

与 `_attr_test.sv` 是**两条平行的路**：那边一条 = 一个属性取值，这边一条 = 一个批次。
**没有这个类，回归里 `+UVM_TESTNAME=npu_type_test` 会撞 `UVM_FATAL (INVTST)`，
而 vsim 仍然 exit 0** —— 跑不起来反而看不出来（`_sim_run_cmd` 的注释记着这个坑）。

**为什么种子声明在模型里**：它不是"怎么跑"的细节，是"**这一批要跑够几条才算数**"
的验证完备性声明 —— 和覆盖点一样属于"该测得够不够"。回归那一侧只是把它铺开成
runtime 参数：`count` 展开成 N 条、各拿 `base + i - 1`、`{{ SEED }}` 落进
`+ntb_random_seed`。实测 `npu_type_test` → `count: 18` + `SEED: 2001`。

追溯矩阵里**复合编号要拆**：`REQ-NPU-002/005` 是"这两条"，后半段是省略前缀的
简写 —— 照 `/` 硬拆会得到一条叫 `005` 的需求，而真正的 `REQ-NPU-005` 仍然没有
交叉。

### 两条采样通道：`sample: stimulus` / `sample: dut`

**先问一个问题：这个信号从哪看得见？** 答案决定了它走哪条通道 —— 分不清就会给
一堆**采不到**的信号生成一份永远不命中的覆盖率模型。

| | `stimulus`（默认） | `dut` |
|---|---|---|
| 信号在哪 | agent 的**事务对象**上 | DUT 里**按名字可见**：输入端口 / 输出端口 / **内部寄存器** |
| 谁采 | `env_cov.sv.j2` 的 `cg_<agent>`（monitor 每笔事务 → `sample()`） | `env_cov.sv.j2` 的 `cg_dut`（`coverpoint vif.<信号>`，时钟沿 + 复位屏蔽） |
| 产物 | `env_cov_bins.yaml` 的 `field_bins` | `coverage/<模块>_cov_if.sv`（bind 的**接口**）+ 契约文件里的 `dut_if` / `dut_bins` |
| 看得到什么 | **只有激励侧** | 内部状态、输出端口 —— monitor 一个都采不到 |
| bin 语法 | `{v}` / `{[a:b]}` | 全量（含 `illegal_bins`） |

```yaml
sampling:                     # sample: dut 的字段靠它生成 bind 语句
  dut_module: npu_sched       # bind 的目标 —— **模块名**，不是实例路径
  clock: clk                  # 默认 clk
  reset: rst_n                # 默认 rst_n；给 null 就不加复位屏蔽

dimensions:
  - id: D_queue
    fields:
      - name: queue_level     # DUT 内部状态
        type: range
        sample: dut           # ← 走 bind 的接口
        width: 6              # 接口端口的位宽；不给按类型推（会记账）
        cover_bins: [...]     # 区间仓 / illegal 在这里同样生效
```

**为什么是 `bind`**：

- monitor 的事务通道**只看得到激励侧** —— 队列水位、依赖类型、发射决策这些内部状态
  与输出端口，它一个都采不到。
- 层次引用（`u_dut.u_sched.queue_level`）要把 tb_top 的实例名写死，换个 bench 就断。
- `bind` 两个问题都没有：挂**模块**上（每个实例自动带一份），端口连接表达式在
  **目标模块作用域**里求值，所以内部名直接就能连（实测 `vlog` + `vopt` 通过）。

**为什么是"接口 + env 组件"，不是"自带 covergroup 的探针模块"**：

`env/<env>_coverage.sv` 被 `include` 进 `env_pkg`，**那里面只能是 class** —— 而 class
够不到 DUT 的信号。所以信号要先被**引出来**：接口 `bind` 进 DUT（只引信号、不采样），
组件持 `virtual <接口>`，`coverpoint vif.<信号>` 采样。这样覆盖率跟着 **UVM 的报告**
走，与事务通道的数在**同一份报告**里。

生成出来的接口长这样（`coverage/npu_sched_cov_if.sv`）：

```systemverilog
interface npu_sched_cov_if (
  input logic clk,
  input logic rst_n,
  input logic [5:0] queue_level,   // 内部信号，直接连
  ...
);
endinterface

bind npu_sched npu_sched_cov_if u_npu_sched_cov_if(.clk(clk), .queue_level(queue_level), ...);
```

组件侧（`env/<env>_coverage.sv`）与挂载侧（`bench/<bench>_tb_top.sv`）**读同一份身份**
（契约文件里的 `dut_if`：类型名 / bind 实例名 / 时钟 / 复位）：

```systemverilog
// env_cov：句柄 + covergroup + 时钟沿采样；取不到句柄就 uvm_fatal
virtual npu_sched_cov_if cov_vif;
covergroup cg_dut; cp_queue_level: coverpoint cov_vif.queue_level { ... } endgroup
task run_phase(uvm_phase phase);
  forever begin @(posedge cov_vif.clk); if (cov_vif.rst_n) cg_dut.sample(); end
endtask

// tb_top：bind 出来的实例在 DUT 作用域里，所以路径 = <DUT 实例>.<bind 实例名>
uvm_config_db#(virtual npu_sched_cov_if)::set(
    null, "*", "cov_vif", u_npu_sched.u_npu_sched_cov_if);
```

两个名字都来自**同一个函数**（`coverage.cov_interface_meta`）并写进同一份契约文件 ——
三处各推一次名字就是"改了三个漏一个"，而漂了的表现是**句柄为空、覆盖率恒 0%，
编译与加载都不报错**。契约里没有 `dut_if` 时**两份模板一个字都不生成**（一致地
"都没有"，而不是单边有）。挂不上则 `uvm_fatal`：**那是接线错误，不是"这次没覆盖率"**。

接口文件会被 `build_filelist_for_tb` 收进编译清单（`coverage/*_cov_if.sv`，排在 RTL
之后 —— `bind` 要求目标模块已声明），所以它是**真编译、真采样、真被 `vcover` 统计**的。
（探针模块 `render_probe` / `coverage/*_probe.sv` 仍在：那是**没有 env 也要收覆盖率**
时的独立通道。管道里只走一条 —— 两个 covergroup 采同一批信号会把签核的数字搅浑，
所以切换通道时会把上一版的探针清掉并记一笔。）

**交叉的两边必须在同一个 covergroup 里**，所以一个 cross 的两侧来源必须一致；
一边 `stimulus` 一边 `dut` 是**表达不了**的，会记账跳过（并提示把另一侧也标成
`sample: dut`）。

**派生信号**（如"相邻两条指令的 opcode 组合"）既不是端口也不是寄存器 —— 用
`sample_expr` 写它对应的表达式，或者让 DUT 自己暴露这个信号（那就不写，采同名）。

### 在流水线里，它被谁收走

**这一段最容易想当然**：本工具能产出一段可编译的 covergroup，但**那段文本如果
没人编译、没人采样，就等于没有**。所以链路的落点要说清：

```
front   写 inputs/casemodel.yaml（模型）
verify  读模型 → inputs/yaml/uvm/env_cov_bins.yaml：
          field_bins（stimulus 那批）/ dut_if + dut_bins（dut 那批的身份与仓）
        读模型 → coverage/<模块>_cov_if.sv（bind 的接口，**落在 filelist 生成之前**）
gen_uvm 读 field_bins → env_cov.sv.j2 里 cp_<字段> 用模型的边界 bin
        （字段名 = 事务字段名 = spec 接口信号名，两边同一个命名空间）
        读 dut_if/dut_bins → env_cov.sv.j2 出 cg_dut；tb_top.sv.j2 挂 config_db
        （**一个读者喂两个模板**，见 gen_uvm.read_env_cov_bins）
ops     build_filelist_for_tb 收 coverage/*_cov_if.sv（排在 RTL 之后）
        → vlog 编译 → bind 把接口挂进 DUT → 组件时钟沿采样
coverage  读 coverage/coverage_points.json 记**声明**；
          vcover -cvg -details 收**实测**（两条通道的 covergroup 在同一份报告里）
```

实测（NPU 调度器，`npu_sched_env_directed_test`）：`cg_dut` 在 ucdb 里是
`/npu_sched_env_pkg/npu_sched_env_coverage/cg_dut`，12 个覆盖点 / 59 个 bin，
一次 1.8us 的定向跑打到 **41.5%**（`cp_instr_type` 4/4、`cp_dep_type` 1/4），
内部的 `queue_level` / `pipeline_state` 都真采到了；`illegal_bins illegal_over`
保持 ZERO（非法仓没被误命中）。

**两条通道为什么不能合并**：`stimulus` 那条**已经跑通**（monitor 每笔事务触发
`write_<agent>` → `sample()`），但它**只看得到激励侧** —— 内部状态与输出端口
它一个都采不到。那部分只能走 bind（见上一节）。实测 `paddr` 的 6 个边界值
渲染成 6 个 bin、编译 `Errors: 0`；NPU 那 12 个信号渲染成带 14 个端口的接口
（12 信号 + 时钟 + 复位）、编译 `Errors: 0`。

**为什么接口落在 verify 而不是 coverage 阶段**：它**要被编译**，而 filelist 是
ops 阶段生成的。写在覆盖率阶段就永远赶不上这一轮 —— 那就是又造一个"看着有、
从没编译过"的产物（这个会话踩过一次）。

### 两个数字不要混

- `analysis/coverage.py` 的**覆盖率**：模型 vs case 表 —— "**用例写全了没有**"。
- `vcover` 的**覆盖率**：仿真打到的 bin / 声明的 bin —— "**仿真打到了没有**"。

前者的 100% 丝毫不保证后者。工作台的「功能覆盖率」页把两者**分列**（声明一列、
实测一列），不合成一个数 —— 合成之后就再也分不出"该测的没测"和"测了的没打中"。

## 测试

```bash
pytest src/tools/generation/casemodel_tools/tests/ -v
```

464 个用例（界面测试搬去工作台之后少了一些，但一条断言都没丢 —— 见下）。
工具自己的测试按层组织在 `src/tools/generation/casemodel_tools/tests/`，
跨层的 Agent 集成测试在仓库根的 `tests/test_casemodel_agent.py`：

| 文件 | 覆盖 |
|------|------|
| `test_domain.py` | Composite（分支/叶子同一接口）、五种字段类型 Strategy、专题三类的派生、优先级排序与空洞 |
| `test_repository.py` | loader 归一化与结构错误、schema 门禁（含递归 children）、case_list 四种输入形状、exporters 三格式往返无损 |
| `test_generation.py` | 五个方法策略各自语义、加权采样、可复现、联动不参与笛卡尔积、互斥剔除、去重、截断计数、专题驱动与交叉组退路 |
| `test_rules.py` | 53 条规则**逐条正反用例**（触发 + 不误报），示例模型的干净/有坑双向断言 |
| `test_analysis.py` | 门面组装、评分不变式（换 case 列表分数不变）、矩阵对称与声明优先、外部核对四方向、闭环无话可说、**文本入口 vs 文件入口结论一致** |
| `test_multi.py` | 两种写法的扇出与覆盖、重复 `object_code` 报错、合并语义（评分算一次 / 树与 case 每对象一份）、`--max-cases` 是每对象上限、单对象时是恒等 |
| `test_uvm_tests.py` | 一条 = 一个取值、维度过滤、边界优先截断、产物形状正好是 `tool_uvm` 认的那个、**不 import `uvm_tools`** |
| `test_coverage.py` | 功能覆盖率方法学：维度→covergroup / 字段→coverpoint / 取值→bin / 显式区间仓 / 两级 illegal / binsof 过滤交叉 / **两条采样通道（stimulus 与 bind 探针）**；两处都**真跑 vlog 编译**；对不上就进 notes |
| `test_cli.py` | 工具自带 CLI 与 `vagent case-model` 的退出码 / 四种格式 / 目录展开 |
| `test_text.py` | 显示宽度对齐（中文占 2 列）、各段文本渲染 |
| `tests/test_casemodel_agent.py`（仓库根） | 三面答案一致、ITool manifest 合法与失败语义、ToolHub 注册与调用 |

界面相关的测试（原 `test_gui.py` / `test_editor.py`）随界面迁到了
`src/workbench/tests/test_casemodel_module.py` 与 `test_casemodel_editor.py` ——
**本包的测试现在一条都不需要 Qt**。那两条最要紧的不变式（保存不改原文、
刷新不碰文本）跟着搬了过去，一条没少。

## 已知边界

- **约束策略体是空的 —— 管道通了，约束还没生效**。`constraints` 生成的是**结构骨架**
  （策略名 / 组合器模式 / 优先级），`apply()` 落到 `default:` 分支什么都不做。
  原因很具体：`env_cons_policies.sv.j2` 的 8 个内置分支按**主题名**（`mem_capacity` …）
  写死，与本工具按**专题 + 方法**推的 `p_th_b02_random` 对不上。要真生效得把那 8 个
  换成按 method 派生的五类 —— **没做**。详见「约束模型生产者」一节的 ⚠️。
  别把"`env/cons/*` 生成了"读成"约束起作用了"。
- **`check <目录>` 会把 case 列表文件报错**。`config/casemodel/examples/` 同时有两类文件，
  `check config/casemodel/examples/` 会因 `fc_real_cases.yaml` 有 `cases:` 而无 `object`/`dimensions`
  报 error。这是刻意的（`check` 的职责就是判断「这份 YAML 是不是合法模型」），
  但批量校验时要指向模型文件。
- **正交性检测靠启发式词表**（`analysis/rules/orthogonality.py` 顶部），换领域要补词。
  「把字段当维度」用 `startswith` 而非 `in`：文档的反例是「维度：尾拍反压」，
  而 `反压持续时间` 里的 `持续` 只是构词成分，用 `in` 会误报。
- **真实 case 核对是单向差集**，不校验 `cover_bins` 与真实仿真覆盖率数据的对应 ——
  核对的是「case 写没写」，不是「仿真跑出来的覆盖率命中没命中」。
  （后者现在有了，但**不在这个工具里**：见「功能覆盖率方法学」一节 —— 实测来自
  `vcover`，本工具只管声明。`cover_bins` 与实测 bin 的**自动对账**仍未做。）
- **`cross_group` 与 `themes` 是两条生成路径**。有 `themes` 时按专题驱动，
  否则退化为按交叉组（老模型不用迁移）；两条路不会同时生效。
- **界面的编辑是「原文编辑」，不是结构化编辑**。不提供在表格里改维度/字段的
  表单 —— 那需要从模型反向生成 YAML，会丢掉注释与格式（见「编辑 YAML」一节）。
  要结构化地看，看其它页面；要改，改原文。
- **编辑器只有语法高亮，没有自动补全**。高亮是启发式的正则（`ui/highlighter.py`），
  认不出多行标量、也分不清引号里的冒号；补全没做 —— 靠 schema 校验脚注 + 保存前
  提示兜底。
