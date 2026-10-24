"""编译层 —— DSL → IR 的流水线（文档 §3.5 的六步）。

分层：import `domain` + `repository` 的产物。

导出名带后缀（`annotate_transactions` / `solve_transactions` / `plan_schedule`）
是为了**不与子模块同名** —— 同名的后果是 `from . import annotate` 拿到函数而不是
模块，报出一句自相矛盾的 `'function' object has no attribute ...`。

**`sequencer.py` 是全包唯一允许出现随机的地方** —— 其余模块 `import random`
会被 `tests/test_layering.py` 的源码守卫抓出来。

    resources ──► 可玩池 = memmap ∩ DSL ∩ 事务硬约束（§3.12.7）
    allocator ──► 地址分配（T3；无解即编译期失败）
    solver    ──► L0 硬合法 → L1 场景子集 → L2 意图偏置（只调权重）
    templates ──► 声明 → 实例（配对的落点：指令组一起造）
    epochs    ──► L3 时间窗编排 + 同步点
    annotate  ──► wait_done / expect_rd + ref 核对 + 观测点纪律
    pipeline  ──► 唯一编排者
"""
from .allocator import (DTYPE_BYTES, Allocation, AllocationPlan, allocate,
                        element_size, tensor_bytes)
from .annotate import (AnnotationResult, annotate as annotate_transactions,
                       check_observation_discipline)
from .epochs import Schedule, plan_epochs as plan_schedule, split_epochs
from .pipeline import CompileOutput, CompileReport, compile_dsl
from .resources import PlayPool, PlaySpace, build_play_space
from .sequencer import Draw, Sequencer
from .solver import (SolveResult, TxnChoice, candidate_specs, mask_from_cores,
                     solve as solve_transactions)
from .templates import instantiate, instantiate_all, ref, ref_set

__all__ = [
    "allocate", "Allocation", "AllocationPlan", "tensor_bytes", "element_size",
    "DTYPE_BYTES",
    "build_play_space", "PlaySpace", "PlayPool",
    "Sequencer", "Draw",
    "solve_transactions", "SolveResult", "TxnChoice", "candidate_specs",
    "mask_from_cores",
    "instantiate", "instantiate_all", "ref", "ref_set",
    "plan_schedule", "split_epochs", "Schedule",
    "annotate_transactions", "AnnotationResult",
    "check_observation_discipline",
    "compile_dsl", "CompileOutput", "CompileReport",
]
