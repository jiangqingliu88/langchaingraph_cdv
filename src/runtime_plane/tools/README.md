# `src/tools` 架构 —— 按板块分职责

工具层的第一原则：**生成产物**与**检查/判定**分开。前者可以产生新文件，
后者只读输入并给出结论/报告；两者混在一起会让"谁改了产物"和"谁在判它"
分不清。

板块的单一真相在 [`boards.py`](boards.py)，并由
`tests/test_tools_boards.py` 钉住：**每个工具包只属于一个板块，且没有未登记的工具包**。

| 板块 | 职责 | 当前包 |
|---|---|---|
| **generation** | 产生验证产物（UVM / ISA IR / C 模型） | `uvm_tools`、`isa_ir_tools`、`cmodel_tools` |
| **checking** | 只读/判定（断言） | `assertion_tools` |
| **execution** | 跑 EDA / 回归 | 空（`regression_tools` 已迁到 `src/orchestration_plane/l2/`） |
| **flow** | 跨阶段流程（趋势） | `trend_tools` |
| **integration** | 对外集成（IDE 桥） | `ide_tools` |
| **humanview** | 人读视图（测试点 / Case / 覆盖率 / SVA / SCB） | `aivm_ir`、`case_ir`、`covg_ir`、`sva_ir`、`scb_ir` |
| **common** | 共享底层（哈希、日志、覆盖率采集、LLM 漏斗） | `lib` |

物理目录与板块的当前状态：

```text
src/runtime_plane/tools/
├─ generation/
│  ├─ uvm_tools/         isa_ir_tools/
│  └─ cmodel_tools/
├─ checking/
│  └─ assertion_tools/
├─ execution/             # 板块占位；regression_tools 已迁到 layers/l2
├─ flow/
│  └─ trend_tools/
├─ integration/
│  └─ ide_tools/
├─ humanview/
│  ├─ aivm_ir/  case_ir/
│  ├─ covg_ir/  sva_ir/  scb_ir/
│  └─ verification_md_ir/ # 模板/文档，不是 Python 包
├─ common/
│  └─ lib/
├─ boards.py              # 板块单一真相
└─ _lc_tool_compat.py
```

## 怎么用

```python
from src.generation import uvm_tools, isa_ir_tools
from src.tools.checking import assertion_tools
from src.tools.humanview import case_ir
```

板块包是**懒加载**的：`from src.generation import uvm_tools` 才真正导入
重依赖，`import src.generation` 本身很轻。

## 迁移纪律

- 先登记板块（`boards.py`），再搬目录；
- 搬目录必须同步更新 import 与路径字符串，并跑 `tests/test_tools_boards.py`
  与全量单测；
- 已迁走的包不要留在板块表里；空目录直接删除，别让“旧实现还在”的错觉留下来。
