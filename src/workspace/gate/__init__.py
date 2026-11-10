"""Gate —— 确定性裁决；Proposal 进 main 的唯一关卡。"""
from .runner import approve_gate, load_gate, run_gate
from .promote import promote

__all__ = ["run_gate", "load_gate", "approve_gate", "promote"]
