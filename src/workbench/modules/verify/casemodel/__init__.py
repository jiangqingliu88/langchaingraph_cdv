"""case 属性完备性建模 —— 归属「验证构建」业务线（清单里 `group: verify`）。

理论的出发点是：**case 由属性组合生成，而不是手写**。传统写法把属性塞进
case 名（`tc_fc_recv_max_len_tail_bp_full_rnd_01`），信息密度高但无法检索、
无法组合、层级错位后必然重复。这个模块把属性显式建模，于是两个最核心的问题
变成了可操作的东西：

  · **正交属性怎么 cross** —— 「维度交叉矩阵」页：专题先选范围，`cross_matrix`
    再约束这些维度哪些必须一起变（★）、哪些可选（○）、哪些互斥（✗）
  · **覆盖率怎么收敛** —— 「取值覆盖」页：分母是字段声明的取值点，分子是被
    case 命中的；缺口按维度列出来，联动派生字段单独标灰（它不是真缺口）

底层工具在 `src/tools/casemodel_tools/`（纯计算、零 LLM 依赖），这个包只做界面。

```
casemodel/
├─ module.py       CasemodelModule —— 11 个页面的容器与全部建模逻辑
├─ page.py         页面基类（Template Method：build / refresh / clear）
├─ pages/          11 个页面，一个文件一个
├─ models.py       领域 Qt 模型（case 属性表、功能组织树）
└─ vocabulary.py   高亮用的领域词表
```
"""
from __future__ import annotations

from .module import CasemodelModule

__all__ = ["CasemodelModule"]
