# `src/tools` 架构 —— 按板块分职责

工具层的第一原则：**生成产物**与**检查/判定**分开。前者可以产生新文件，
后者只读输入并给出结论/报告；两者混在一起会让"谁改了产物"和"谁在判它"
分不清。

板块的单一真相在 `src/tools/boards.py`，并由
`tests/test_tools_boards.py` 钉住：**每个工具包只属于一个板块，且没有未登记的工具包**。

| 板块 | 职责 | 包 |
|---|---|---|
| **generation** | 产生验证产物（UVM / ISA IR / 模型 / 文档） | `uvm_tools`、`isa_ir_tools`、`cmodel_tools`、`scmodel_tools`、`doc_tools` |
| **checking** | 只读/判定（断言、debug、覆盖率分析、spec 校验） | `assertion_tools`、`debug_tools`、`coverage_tools`、`spec_tools` |
| **execution** | 跑 EDA / 回归（不决定生成什么、也不决定签不签） | `regression_tools` |
| **flow** | 跨阶段流程（签核、血缘、趋势） | `flow_tools`、`trend_tools` |
| **integration** | 对外集成（IDE 桥） | `ide_tools` |
| **common** | 共享底层（哈希、日志、覆盖率采集、LLM 漏斗） | `lib` |

物理目录与板块一一对应：

```text
src/tools/
├─ generation/
│  ├─ uvm_tools/         isa_ir_tools/
│  ├─ cmodel_tools/      scmodel_tools/  doc_tools/
├─ checking/
│  ├─ assertion_tools/   debug_tools/    coverage_tools/   spec_tools/
├─ execution/
│  └─ regression_tools/
├─ flow/
│  ├─ flow_tools/        trend_tools/
├─ integration/
│  └─ ide_tools/
├─ common/
│  └─ lib/
├─ boards.py              # 板块单一真相
└─ _lc_tool_compat.py
```

## 怎么用

```python
from src.tools.generation import casemodel_tools
from src.tools.checking import coverage_tools
from src.tools.execution import regression_tools
```

板块包是**懒加载**的：`from src.tools.generation import uvm_tools` 才真正导入
重依赖，`import src.tools.generation` 本身很轻。

## 生成 / 检查的进一步拆分：`uvm_tools`

`uvm_tools` 是最大的混合包，已经先做了一步物理拆分：

```text
src/tools/generation/uvm_tools/
├─ checking/                 # 只读/判定
│  ├─ tool_check_compile
│  ├─ tool_check_static
│  ├─ tool_check_env_arch
│  ├─ tool_check_loopback
│  ├─ tool_check_health
│  └─ tool_quality_report
├─ generation/               # 生成层（parsing / models / render / generators）
├─ tool_uvm/                 # UVM 生成主体
├─ tool_find_spec_yaml/      # spec → YAML / 回归产物
├─ tool_jinja_render/        # 模板渲染
└─ agent_tools.py            # 对 Agent 的薄包装
```

规则：

- **checking 不生成 UVM 代码**，只读产物、返回判定/报告；
- **generation 不写判定结论**，只生产文件/文本；
- 新增 checker 放 `uvm_tools/checking/`；新增生成器放 `uvm_tools/generation/`
  或对应的 `tool_*` 目录。

## 迁移纪律

- 先登记板块（`boards.py`），再搬目录；
- 搬目录必须同步更新 import 与路径字符串，并跑 `tests/test_tools_boards.py`
  与全量单测；
- 未搬完的包**仍然可用**，板块表是"职责声明"，不是"目录必须已迁移"的借口。
