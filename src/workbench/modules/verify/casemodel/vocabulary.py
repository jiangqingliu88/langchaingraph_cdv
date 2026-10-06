"""case 模型的高亮词表 —— **领域知识，不属于通用控件**。

`ui/highlighter.py` 只认「哪些键算骨架、哪些值算枚举」这两个列表；具体是哪些
键，由这个模块告诉它。所以通用高亮器里一行 case 模型的名字都没有。

写错一个词表项的代价只是「颜色不对」，所以这两个列表可以随文档演进随手补，
不需要与 `domain/vocab.py` 严格同步（那里才是权威，这里只是提示）。
"""
from __future__ import annotations

#: 模型的骨架键 —— 六层 + 配置。加粗，让结构一眼可辨
SKELETON_KEYS = (
    "version", "object", "object_cn", "object_code", "sub_objects", "themes",
    "dimensions", "methods", "checks", "cross_matrix", "cross_groups",
    "environment", "generation", "case_defaults",
)

#: 工具认得的枚举值（与 domain.vocab 对齐）—— 写错时颜色会不对，顺手就是提示
ENUM_VALUES = (
    "D", "RND", "G", "RPLY", "SPCL",
    "enum", "range", "set", "weighted", "linkage",
    "required", "optional", "forbidden",
    "P0", "P1", "P2", "P3", "P4", "P5",
    "independent", "linkage", "exclusive",
)
