"""契约式子 Agent —— 主 Agent 派发、隔离执行、结构化回收。"""
from .contract import SubagentContract, SubagentResult
from .factory import AGENT_TYPES, build_contract
from .manager import SubagentManager
from .isolation import SubagentWorkspace, ScopedTools

__all__ = ["SubagentContract", "SubagentResult", "AGENT_TYPES",
           "build_contract", "SubagentManager", "SubagentWorkspace",
           "ScopedTools"]
