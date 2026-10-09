"""casemodel_tools —— case 属性完备性建模。

按「功能组织树 + P0/P1/P2 专题 + 维度约束组合」把 case 的六层属性显式建模，
case 由属性组合**生成**而不是手写。文档见 readem.md。

分层（依赖只能从上往下）：

    domain/       数据与不变式，不依赖任何 IO。OrgNode（Composite）/
                  Field（Strategy 五种类型化）/ Dimension / Theme / CaseModel
    repository/   取数与落盘。loader（YAML→模型）/ case_list（真实 case 列表）
                  / exporters（属性表→四种格式），都用 Strategy/Repository 模式
    generation/   唯一会造 case 的地方。strategies（五种方法 Strategy）
                  + builder（文档十七节的六步流水线，Builder 模式）
    analysis/     只读判断。specifications（规则可插拔）+ rules/（按分类分模块）
                  + matrix / score / external / facade（Facade 模式）
    text.py       只渲染。纯文本报告（CLI 与界面导出共用）

**本包是纯工具：不含任何面向 LLM 的代码，也没有界面。** 前者在
`src/executors/verify/casemodel/`，后者在验证工作台
（`src/workbench/modules/vms/casemodel/`）—— 分开是为了让工具能在不装 langchain、
**也不装 Qt** 的环境里直接用。

对外入口：
    api.py                        程序化接口（run_validate / run_gaps / run_generate）
    cli.py                        命令行（check / analyze / generate / tree / matrix / rules）
    analysis.analyze()            分析门面
    repository.load_model()       模型加载

用法见 readme.md。
"""
from __future__ import annotations

__version__ = "2.0"
__all__ = ["__version__"]
