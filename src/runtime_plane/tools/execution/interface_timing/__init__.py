"""真实 RTL 工具适配：只在外部仿真实际执行时出具 runtime evidence。"""

from .simulator import SimulationResult, simulate

__all__ = ["SimulationResult", "simulate"]
