# SignOffAI Spec 文档格式设计分析

> 日期：2026-08-09  
> 分析范围：手写源 spec、流水线生成 doc、Serializer 数据模型、数据库模型

---

## 1. 格式全景：三套格式共存

项目中存在**三种 Spec 表示形态**，各自格式不同：

### 1.1 形态对比

```
形态 A：手写源 Spec                形态 B：流水线生成 Doc              形态 C：数据库存储
specs/apb_uart/apb_uart_spec.md   output/demo_apb_uart/docs/         doc_documents 表
                                   de/01_specification.md
─────────────────────────────────  ───────────────────────────────  ────────────────────
元数据格式：
  <!-- HTML 注释 -->                 --- YAML frontmatter ---          metadata_json JSON 列

章节结构：
  # 标题                            # 标题                           结构化字段
  ## 1. 概述                       ## 修订历史                       (title/content/level/status)
  ## 2. 功能需求                   ## 1. 概述                       
  ## 3. 接口规范                   ## 2. 功能特性 (FEAT-xxx 表格)   
  ## 4. 时序约束                   ## 3. 接口定义 (IF-xxx 表格)     
  ## 5. 功耗约束                   ## 4. 寄存器映射                 
                                  ## 5. 测试点概览 (TP-xxx)        
                                  ## 6. 覆盖率目标                 
                                  ## 7. 验证架构概览               

需求表达：
  ### 标题 + **级别**：P0          FEAT-xxx 表格行                   doc_requirements 表
  + **描述**：...                   (编号 / 名称 / 描述 / 优先级)    (req_id / description / req_type)
```

**核心问题：三套格式互不兼容，没有一个统一的 Schema 定义。**

---

## 2. 逐层分析

### 2.1 手写源 Spec（形态 A）

**文件**：`specs/apb_uart/apb_uart_spec.md`

```markdown
# APB UART 模块
<!--
  module: apb_uart
  level: BT
  data_width: 8
  requirements: [REQ_APB_UART_001]
-->

## 1. 概述
...

## 2. 功能需求
### APB 寄存器读写
**级别**：P0
**描述**：通过 APB 总线读写 UART 配置寄存器...
**验收标准**：覆盖率 100%

## 3. 接口规范
| 信号 | 位宽 | 方向 | 协议 | 描述 |
|------|------|------|------|------|
| pclk | 1 | INPUT | Clock | APB 时钟 |
| tx   | 1 | OUTPUT | UART | 串行发送 |
```

**优点**：
- 人可读性强，工程师可以直接用 Markdown 编辑器编写
- HTML 注释元数据对渲染不可见，保持文档干净
- 五段式结构（概述/需求/接口/时序/功耗）覆盖了基本验证关注点

**问题**：

| # | 问题 | 严重度 |
|---|------|:---:|
| 1 | **需求没有 ID** — `### APB 寄存器读写` 是标题，没有 `REQ_xxx` 编号；metadata 里声明了 `REQ_APB_UART_001` 但这个 ID 在正文中不存在 | 🔴 |
| 2 | **元数据用 HTML 注释** — `<!-- ... -->` 解析靠手工正则 `re.search(r'<!--\s*(.*?)\s*-->', md, re.DOTALL)`，key:value 解析无引号处理、无类型校验 | 🟡 |
| 3 | **接口表正则脆弱** — `re.findall(r'\|\s*(\w[\w\[\]:]*)\s*\|\s*(\d+)\s*\|...')` 不支持 `preset_n` 这样的下划线、不支持 `paddr[7:0]` 这样的位宽表达式被当成了信号名的一部分 | 🟡 |
| 4 | **时序约束格式不标准** — `| paddr → prdata | ≤ 2 cycle |` 不是工业标准 SDC 格式 | 🟡 |
| 5 | **缺少需求类型** — metadata 没有区分安全需求/功能需求/性能需求 | 🟡 |

### 2.2 流水线生成 Doc（形态 B）

**文件**：`output/demo_apb_uart/docs/de/01_specification.md`

```markdown
---
document_id: SPEC-DOC-001
title: "设计需求规格书"
project: "ALU IP"
version: 1.0
---
# 设计需求规格书
| 项目 | 内容 |
|------|------|
| **文档ID** | `SPEC-DOC-001` |

## 修订历史
| 版本 | 日期 | 作者 | 变更说明 |

## 1. 概述
## 2. 功能特性        ← 改名为"功能特性"，用 FEAT-xxx 编号
## 3. 接口定义        ← 改名为"接口定义"，用 IF-xxx 编号
## 4. 寄存器映射      ← 手写 spec 中没有这个章节
## 5. 测试点概览      ← 手写 spec 中没有这个章节
## 6. 覆盖率目标      ← 手写 spec 中没有这个章节
## 7. 验证架构概览    ← 手写 spec 中没有这个章节
```

**与手写 spec 的差异**：

| 维度 | 手写 Spec（形态 A） | 生成 Doc（形态 B） | 兼容？ |
|------|-------------------|-------------------|:---:|
| 元数据格式 | `<!-- HTML 注释 -->` | `--- YAML frontmatter ---` | ❌ |
| 需求章节名 | `## 2. 功能需求` | `## 2. 功能特性` | ❌ |
| 需求编号 | 无（仅标题） | FEAT-xxx | ❌ |
| 接口章节名 | `## 3. 接口规范` | `## 3. 接口定义` | ❌ |
| 接口编号 | 无 | IF-xxx | ❌ |
| 寄存器映射 | 无 | `## 4. 寄存器映射` | ❌ |
| 测试点 | 无 | `## 5. 测试点概览 (TP-xxx)` | ❌ |
| 覆盖率目标 | 无 | `## 6. 覆盖率目标` | ❌ |
| 验证架构 | 无 | `## 7. 验证架构概览` | ❌ |

**形态 B 是"超集"——它在形态 A 的基础上增加了大量流水线产出的信息。但两种格式的章节名不统一，导致 `DocumentSerializer.md_to_doc()` 无法正确解析生成的文档。**

### 2.3 Serializer 数据模型（`doc_serializer.py`）

```python
StructuredDocument:
    meta: DocumentMeta        # module/level/parent/process/frequency/data_width/interfaces/requirements/sub_modules
    overview: str             # 概述文本
    requirements: [RequirementItem]  # title/level/req_type/description/acceptance
    interfaces: [InterfaceSpec]      # name/width/direction/protocol/description
    timing_constraints: [TimingConstraint]  # signal_a/signal_b/relation/cycles/description
    power_constraints: [PowerConstraint]    # mode/power_mw/description
```

**设计问题**：

| # | 问题 | 位置 |
|---|------|------|
| 1 | **`RequirementItem` 没有 `req_id` 字段** — 只有 `title/level/req_type/description/acceptance`，但 metadata 里有 `requirements: [REQ_xxx]` | `RequirementItem` dataclass |
| 2 | **`req_type` 是自由字符串** — 类型是 `str` 而非 `Enum`，`_parse_requirements` 里用 `re.search(r'[A-Z]+', line)` 提取，极易误匹配 | `_parse_requirements()` |
| 3 | **`InterfaceSpec` 缺少关键字段** — 没有 clock domain、reset domain、CDC 标记、信号分组 | `InterfaceSpec` dataclass |
| 4 | **`TimingConstraint` 不是 SDC 格式** — `signal_a/signal_b/relation/cycles` 是内部抽象，无法直接导出为标准 SDC Tcl 脚本 | `TimingConstraint` dataclass |
| 5 | **`DocumentMeta.extra` 兜底导致 schema 退化** — 任意 key:value 都能塞进 `extra`，失去了 schema 校验的意义 | `DocumentMeta.extra: dict` |
| 6 | **元数据解码只用 HTML 注释** — `md_to_doc` 只解析 `<!-- -->` 格式，流水线生成的 YAML frontmatter 格式（`---...---`）完全不被识别 | `_parse_metadata()` |

### 2.4 数据库模型（`models.py`）

```
DocDocument          — path / title / content / level / status / tags / metadata_json
DocVersion           — document_id / version / content / content_hash / change_summary
DocRequirement       — req_id / description / req_type / line_number / is_covered / coverage_json
```

**设计问题**：

| # | 问题 |
|---|------|
| 1 | **`DocDocument.content` 存完整 Markdown** — 与 `StructuredDocument` 不关联，两者独立维护 |
| 2 | **`DocRequirement` 是扁平表** — 没有与 `DesignFeature` / `Testpoint` 的外键关联，只能通过 `req_id` 字符串匹配 |
| 3 | **`metadata_json` 是黑洞** — JSON 列无 schema 约束，任何数据都能塞入 |
| 4 | **缺少 Spec → Design → Testpoint 的正式外键链路** — `DesignModule` / `DesignFeature` / `DocRequirement` 之间没有数据库级外键 |

---

## 3. 格式不一致的影响链

```
手写 Spec (HTML注释)                Serializer 只认 HTML 注释
       │                                    │
       ├─ metadata: 有 REQ_xxx 但正文没有 ──┼── RequirementItem 没有 req_id 字段
       ├─ section 名: "功能需求"            │
       └─ 接口: 表格格式                    │
                                            │
生成 Doc  (YAML frontmatter)               │   数据库 (metadata_json)
       │                                    │        │
       ├─ section 名: "功能特性" ───────────┼────────┤  三者互不兼容
       ├─ 编号: FEAT/IF/TP-xxx             │        │
       └─ 多了: 寄存器/测试点/覆盖率/架构    │        │
```

**结果**：从手写 Spec → 流水线生成 Doc → 数据库存储，每一步都是格式断裂点。Serializer 只能解析手写格式，生成的 Doc 无法 round-trip。

---

## 4. 与工业标准的差距

### 4.1 缺失的字段（对比 IP-XACT / 企业内部 Spec 模板）

| 真实 IC Spec 必有内容 | SignOffAI 当前状态 |
|------|------|
| **需求 ID**（REQ_xxx，唯一可追溯） | ❌ 只在 metadata 声明，正文无 |
| **需求溯源**（parent requirement） | ⚠️ meta.parent 有，但 RequirementItem 无 parent_id |
| **时钟域信息**（per-signal） | ❌ 完全没有 |
| **复位域信息** | ❌ 完全没有 |
| **CDC 路径标注** | ❌ 完全没有 |
| **配置参数**（Verilog parameter/generic） | ❌ 完全没有 |
| **性能目标**（latency/throughput） | ❌ 完全没有 |
| **面积目标**（gate count / μm²） | ❌ 完全没有 |
| **安全等级**（ASIL / SIL） | ❌ 完全没有 |
| **依赖关系**（依赖哪些其他模块） | ❌ 只存在于 meta.sub_modules |
| **形式化属性**（SVA / PSL 引用） | ❌ 完全没有 |
| **接口协议版本**（AMBA 版本等） | ❌ InterfaceSpec 无 version 字段 |

### 4.2 需求建模的差距

```
真实 IC 需求模型:
  Requirement
    id: REQ_UART_BT_001          ← 全局唯一 ID
    parent: REQ_UART_IT_001      ← 父子层级
    type: FUNCTIONAL | SAFETY | PERFORMANCE | POWER | TIMING
    priority: P0 | P1 | P2 | P3
    asil: QM | A | B | C | D    ← 功能安全等级
    description: str
    acceptance_criteria: str     ← 可量化的验收标准
    verification_method: str     ← 验证方法
    status: DRAFT | APPROVED | VERIFIED | CLOSED
    test_points: [TP-xxx]        ← 关联测试点
    source_doc: str              ← 来源文档
    rationale: str               ← 需求理由（为什么需要）
    assumptions: [str]           ← 前提假设

SignOffAI RequirementItem:
    title: str                   ← 中文标题
    level: str                   ← P0/P1/P2
    req_type: str                ← 自由字符串
    description: str             
    acceptance: str              
    # 没有 id、没有 parent、没有 asil、没有 status、没有关联
```

**差距：SignOffAI 的需求模型只有 5 个字段，真实需求模型需要 15+ 个字段。**

---

## 5. 问题等级汇总

| 等级 | 数量 | 典型问题 |
|:---:|:---:|------|
| 🔴 严重 | 4 | 需求无 ID、三套格式不兼容、Serializer 不能 round-trip、metadata 只认 HTML 注释 |
| 🟡 中等 | 7 | 接口信号正则脆弱、时序格式非标准、req_type 自由字符串、extra 黑洞列、缺少外键链路、clk/rst 域缺失、CDC 缺失 |
| 🟢 轻微 | 3 | 章节名双语混用、字段命名不统一（level vs priority）、元数据 key 无白名单 |

---

## 6. 建议的统一 Spec Schema

### 6.1 统一元数据格式：YAML frontmatter

```
废弃:  <!-- module: xxx -->  (HTML 注释)
采用:  ---
      id: SPEC-UART-BT-001
      module: apb_uart
      level: BT
      ...
      ---
       (YAML frontmatter，业界标准 Jekyll/Hugo/Pandoc)
```

### 6.2 统一需求模型

```python
@dataclass
class Requirement:
    id: str                          # "REQ_UART_BT_001"
    parent_id: str = ""              # 父需求 ID
    title: str = ""
    description: str = ""
    req_type: RequirementType = RequirementType.FUNCTIONAL
    priority: str = "P0"              # P0/P1/P2/P3
    asil: str = "QM"                 # QM/A/B/C/D
    acceptance: str = ""
    verification_method: str = ""     # simulation/formal/assertion
    status: str = "draft"
    source_doc: str = ""             # 来源文档路径
    rationale: str = ""
    assumptions: List[str] = field(default_factory=list)
    test_point_ids: List[str] = field(default_factory=list)
```

### 6.3 完整接口模型

```python
@dataclass
class InterfaceSpec:
    name: str                        # pclk
    width: int = 1
    direction: str = "INPUT"
    protocol: str = ""               # APB/AXI/UART
    protocol_version: str = ""       # AMBA 3.0
    clock_domain: str = ""           # pclk
    reset_domain: str = ""           # preset_n
    is_cdc: bool = False             # 跨时钟域标记
    cdc_sync_method: str = ""        # 2-FF / FIFO / handshake
    description: str = ""
    signal_group: str = ""           # APB control / APB data / UART
```

### 6.4 统一章节名

```
## 1. 概述
## 2. 功能需求        ← 统一用"功能需求"（不用"功能特性"）
## 3. 接口规范        ← 统一用"接口规范"（不用"接口定义"）
## 4. 寄存器映射      ← 新增
## 5. 时序约束
## 6. 功耗约束
## 7. 安全约束        ← 新增
## 8. 测试点          ← 新增
## 9. 覆盖率目标      ← 新增
## 10. 验证架构       ← 新增
```

### 6.5 Serializer 双向兼容

```python
class DocumentSerializer:
    def md_to_doc(self, md_text: str) -> StructuredDocument:
        # 同时支持 HTML 注释和 YAML frontmatter
        metadata = self._parse_yaml_frontmatter(md_text) or self._parse_html_comment(md_text)
    
    def doc_to_md(self, doc: StructuredDocument) -> str:
        # 统一输出 YAML frontmatter
```

---

## 7. 实施建议

| 阶段 | 行动 | 影响范围 |
|:---:|------|------|
| **立即** | 在 `RequirementItem` 中增加 `req_id` 字段 | `doc_serializer.py` |
| **立即** | 统一元数据格式为 YAML frontmatter，兼容 HTML 注释 | `_parse_metadata()` |
| **本周** | 统一 10 个标准章节名，冻结为常量 | `doc_serializer.py` + `pipeline_docs.py` |
| **本周** | `req_type` 改为 Enum（FUNCTIONAL/PERFORMANCE/TIMING/POWER/SAFETY/ERROR） | `doc_serializer.py` |
| **本月** | 扩展 `RequirementItem` 到 15 字段完整模型 | `doc_serializer.py` + `models.py` |
| **本月** | 建立 Spec → Design → Testpoint 的外键链路 | `models.py` |
| **下月** | 支持 SDC 格式导出（TimingConstraint → SDC Tcl） | 新增 `sdc_exporter.py` |
| **下月** | 增加 ASIL/安全字段 | `doc_serializer.py` |

---

## 8. 一句话总结

> **Spec 格式的核心问题是"三个筒仓"：手写 spec（HTML 注释）、生成 doc（YAML frontmatter）、数据库（JSON 列）各说各话。首先统一元数据格式和章节名，然后在 RequirementItem 中加入 `req_id`，再扩展到 15 字段的完整需求模型。当前 5 字段模型比起真实 IC 需求管理需要的 15+ 字段，缺口超过 60%。**
