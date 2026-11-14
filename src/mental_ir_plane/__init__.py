"""Mental IR —— agent 的「心智模型」结构化表达。

与 `src/ir_plane/` 的 Case/Execution/Evidence IR 不同，这里回答的是**理解层**
的问题：规格到底要求验证什么？哪些前提是假设？哪些点还没说清？验证意图如何
落到证据上？它由 `agent_plane/specialists/mental` 生成，供人审阅，也可以作为
verify / coverage 的上下文。

只保留模型与落盘，不复制 `ir_plane` 的实现。
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
]
