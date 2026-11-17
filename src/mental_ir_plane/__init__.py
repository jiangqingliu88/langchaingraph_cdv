"""唯一 IR 根 —— 总（理解 + 融合） + 分（引擎与契约）。

    src/mental_ir_plane/
    ├── model.py / store.py     理解层（MentalIR）
    ├── dplan/                  设计与模型契约（DesignPlan / dplan_ir_v1）
    ├── unified/                融合层（Mental + DPlan + VPlan）
    ├── contract/ decision/ formal/ interface_timing/
    ├── proposal/ specification_compiler/ vplan/
    └── example/

`model/store` 回答「理解什么」；`unified` 回答「三份输入如何关联」；
其余子包保留契约、计划、用例与执行模型。详见同目录 `README.md`。
原 `src/ir_plane` 已删除。
"""

from .model import (
    Ambiguity,
    Assumption,
    Goal,
    MentalIR,
    Risk,
    SourceAnchor,
    VerificationIntent,
    canonical_hash,
)
from .store import (
    MENTAL_IR_DIR,
    mental_ir_path,
    read_mental_ir,
    write_mental_ir,
)
from .unified import (
    UnifiedIR,
    build_unified_ir,
    dplan_view,
    mental_view,
    read_unified,
    views,
    vplan_view,
    write_unified,
)

__all__ = [
    "Ambiguity",
    "Assumption",
    "Goal",
    "MentalIR",
    "Risk",
    "SourceAnchor",
    "VerificationIntent",
    "canonical_hash",
    "MENTAL_IR_DIR",
    "mental_ir_path",
    "read_mental_ir",
    "write_mental_ir",
    "UnifiedIR",
    "build_unified_ir",
    "mental_view",
    "dplan_view",
    "vplan_view",
    "views",
    "read_unified",
    "write_unified",
]
