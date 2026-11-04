"""校验规则集 —— 每条规则一个 Rule 子类，用 @register 自动登记。

按分类分模块（与 analysis.issues 的 CATEGORY_* 一一对应）：
    references.py     引用完整性
    orthogonality.py  层级正交性（文档十八、十九节）
    org_tree.py       功能组织树
    themes.py         专题（P0/P1/P2）
    cross.py          维度交叉矩阵
    coverage.py       取值覆盖
    environment.py    环境指纹与检查项

新增规则：在本目录下写一个 Rule 子类并 @register 即可 ——
报告、GUI、规则清单三处都从规格注册表读，不用改动它们。
"""
