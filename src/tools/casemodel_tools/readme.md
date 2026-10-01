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
├─ view/            只渲染
│   ├─ text.py          纯文本（CLI）
│   └─ gui/             tkinter
│       ├─ widgets.py   IssueTable / MatrixCanvas / TreeTable
│       ├─ app.py       主窗口（遍历 TABS 建页）
│       └─ tabs/        每个标签页一个组件
├─ agent/           三个接入面                     ← Adapter
│   ├─ adapters.py      语义（吃 YAML 文本、吐 dict）
│   ├─ registry.py      声明式 ToolRegistry + ToolHub 的 ITool
│   └─ langchain_tools.py  @tool 外壳
└─ cli.py           命令行入口
```

**规则可插拔**是这套结构的主要收益：新增一条校验 = 在 `analysis/rules/` 下写一个
`Rule` 子类并 `@register` —— 报告、GUI 规则页、`rules` 命令三处都从注册表读，
一行都不用改。

## 命令

两个入口，能力等价：`python -m src.tools.casemodel_tools.cli`（独立工具）与
`vagent case-model`（主 CLI）。

```bash
# ── 独立入口 ──
python -m src.tools.casemodel_tools.cli check    examples/cpu_pipeline.yaml
python -m src.tools.casemodel_tools.cli analyze  examples/cpu_pipeline.yaml
python -m src.tools.casemodel_tools.cli analyze  examples/cpu_pipeline.yaml \
    --cases examples/fc_real_cases.yaml
python -m src.tools.casemodel_tools.cli tree     examples/cpu_pipeline.yaml   # 组织树 + 专题
python -m src.tools.casemodel_tools.cli matrix   examples/cpu_pipeline.yaml
python -m src.tools.casemodel_tools.cli rules                                # 规则清单
python -m src.tools.casemodel_tools.cli generate examples/cpu_pipeline.yaml \
    --format yaml --out cases.yaml
python -m src.tools.casemodel_tools.cli gui                                  # tkinter 界面

# ── 主 CLI ──
vagent case-model check    examples/cpu_pipeline.yaml
vagent case-model analyze  examples/cpu_pipeline.yaml --cases real.yaml --json
vagent case-model tree     examples/cpu_pipeline.yaml
vagent case-model rules
vagent case-model generate examples/cpu_pipeline.yaml -f csv -o cases.csv
vagent case-model gui
```

退出码：有 error → `1`，模型结构非法 / 文件不存在 → `2`，正常 → `0`。
`check <目录>` 会递归展开 —— 所以 `check examples/` 也会校验到 `fc_real_cases.yaml`，
那是一份 case 列表而不是模型，报 error 是**正确**行为。

## 示例

| 文件 | 说明 | 分数 |
|------|------|------|
| `cpu_pipeline.yaml` | 五段流水组织树 + 6 个专题（P0/P1/P2，含非结构类与随机），218 个 case | **93.8** |
| `cpu_pipeline_flawed.yaml` | 组织树 / 专题层的坑：叶子代号重复、子树死结构、优先级空洞、专题重叠、SPCL 推不动边界、专题选了互斥维度 | **46.7** |
| `fc_flowcontrol.yaml` | 流控，扁平子对象 + 交叉组（老写法）。因为缺整个专题层，分数明显低于 cpu_pipeline | **77.8** |
| `fc_flawed.yaml` | 维度层的坑：把字段当维度、把方法当维度、把检查当对象… | **22.6** |
| `fc_real_cases.yaml` | 外部真实 case 列表，注入 7 类缺陷供 `--cases` 演示 | — |

`fc_flowcontrol.yaml` 是**刻意保留的老写法**：只写一层 `sub_objects`、不声明 `themes`。
它照常工作（生成退化为按交叉组），但分数会因「缺专题层」掉下来 —— 这正好演示了
新模型比旧写法多出来的那层价值。要迁移，把它按流水/能力点加上 `children`、
再按 P0/P1/P2 补上 `themes` 即可。

## 校验规则（51 条）

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
python -m src.tools.casemodel_tools.cli rules          # 全部列出
```

## 第五块：真实 case 反向核对（`--cases`）

前七类规则都是「模型对自己」——生成 case，再拿生成的 case 量模型。这一块换方向：
拿**真实存在的 case 列表**去量模型，回答四个问题。

```
真实 case 核对 —— 源 examples/fc_real_cases.yaml
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

## GUI（tkinter）

```bash
python -m src.tools.casemodel_tools.cli gui examples/cpu_pipeline.yaml
```

十个标签页：概览、组织树 / 专题、层级正交性、维度交叉矩阵、取值覆盖、
环境与检查、Case 属性表、真实 case 核对、Schema 校验、规则清单。

界面不含任何分析逻辑 —— 它只是 `AnalysisResult` 的一层视图，所以能脱离 GUI 单独
测试，导出报告也直接复用 CLI 的渲染器（两处不会各说各话）。

> **为什么是 tkinter**：`CLAUDE.md` 明确禁止 Web 前端开发。tkinter 是标准库、
> 零新增依赖，符合「个人级 CLI 工具」的定位。

## Agent 接入面

三个面**共用 `agent/adapters.py` 的实现与同一批工具名**，所以不会各给一个答案
（有测试固定）：

| 接入面 | 位置 | 用途 |
|--------|------|------|
| LangChain `@tool` | `agent/langchain_tools.py` | 用 `_lc_tool_compat.tool`，langchain-core 1.x 下仍可直接调用 |
| 声明式 `ToolRegistry` | `agent/registry.ensure_casemodel_tool_registry()` | 由 `agents/agent_tools.py` 汇总，BaseAgent 据此 wrap + 校验 |
| `ToolHub` 的 `ITool` | `agent/registry.register_casemodel_tools(hub)` | 带 manifest / 风险等级 / 审计追踪 |

| 工具 | 用途 |
|------|------|
| `casemodel_validate(yaml_text)` | Schema 校验结果 |
| `casemodel_gaps(yaml_text, max_cases=None, cases_text=None)` | 全量完备性分析；给 `cases_text` 时追加反向核对 |
| `casemodel_generate(yaml_text, max_cases=None, seed=None)` | case 属性表 |

风险等级一律 `safe`（纯计算，不写盘、不起子进程）。按 ADR-3 的凭证约定，
`verified_by` 是 `"none"` —— 确定性工具本身无「外部验证」概念，但结论由输入 YAML
唯一决定，所以可复现。工具名用下划线而非 `a.b` 点号：点号会被带进 OpenAI
function-calling 的 `function.name`，那是非法字符（有测试固定）。

## 测试

```bash
pytest src/tools/casemodel_tools/tests/ -v
```

274 个用例，按层组织：

| 文件 | 覆盖 |
|------|------|
| `test_domain.py` | Composite（分支/叶子同一接口）、五种字段类型 Strategy、专题三类的派生、优先级排序与空洞 |
| `test_repository.py` | loader 归一化与结构错误、schema 门禁（含递归 children）、case_list 四种输入形状、exporters 三格式往返无损 |
| `test_generation.py` | 五个方法策略各自语义、加权采样、可复现、联动不参与笛卡尔积、互斥剔除、去重、截断计数、专题驱动与交叉组退路 |
| `test_rules.py` | 51 条规则**逐条正反用例**（触发 + 不误报），示例模型的干净/有坑双向断言 |
| `test_analysis.py` | 门面组装、评分不变式（换 case 列表分数不变）、矩阵对称与声明优先、外部核对四方向、闭环无话可说 |
| `test_surfaces.py` | 三面答案一致、ITool manifest 合法与失败语义、独立 CLI 与 `vagent` 的退出码/格式 |
| `test_view.py` | 显示宽度对齐（中文占 2 列）、各段渲染、GUI 十页构建与交互 |

## 已知边界

- **`check <目录>` 会把 case 列表文件报错**。`examples/` 同时有两类文件，
  `check examples/` 会因 `fc_real_cases.yaml` 有 `cases:` 而无 `object`/`dimensions`
  报 error。这是刻意的（`check` 的职责就是判断「这份 YAML 是不是合法模型」），
  但批量校验时要指向模型文件。
- **正交性检测靠启发式词表**（`analysis/rules/orthogonality.py` 顶部），换领域要补词。
  「把字段当维度」用 `startswith` 而非 `in`：文档的反例是「维度：尾拍反压」，
  而 `反压持续时间` 里的 `持续` 只是构词成分，用 `in` 会误报。
- **真实 case 核对是单向差集**，不校验 `cover_bins` 与真实仿真覆盖率数据的对应 ——
  核对的是「case 写没写」，不是「仿真跑出来的覆盖率命中没命中」。
- **`cross_group` 与 `themes` 是两条生成路径**。有 `themes` 时按专题驱动，
  否则退化为按交叉组（老模型不用迁移）；两条路不会同时生效。
- **GUI 只读不写**。改模型要在 YAML 里改，界面不做编辑（避免两处真相）。
