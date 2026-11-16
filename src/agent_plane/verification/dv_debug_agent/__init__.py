"""调试 Agent + 确定性 DebugExecutor / 受控修复策略（迁移自 specialists/debug）。"""

from src.agent_plane._lazy import make_getattr

__all__ = ['DVDebugAgent', 'DebugExecutor', 'RepairProposal', 'build_debug_subgraph', 'create_agent', 'n_debug_agent', 'stage_patch', 'validate_proposal']

_LAZY = {
    'DVDebugAgent': (f"{__name__}.agent", 'DVDebugAgent'),
    'create_agent': (f"{__name__}.agent", 'create_agent'),
    'DebugExecutor': (f"{__name__}.main", 'DebugExecutor'),
    'RepairProposal': (f"{__name__}.repair_policy", 'RepairProposal'),
    'stage_patch': (f"{__name__}.repair_policy", 'stage_patch'),
    'validate_proposal': (f"{__name__}.repair_policy", 'validate_proposal'),
    'build_debug_subgraph': (f"{__name__}.graph", 'build_debug_subgraph'),
    'n_debug_agent': (f"{__name__}.loop", 'n_debug_agent'),
}

__getattr__ = make_getattr(globals(), _LAZY, __name__)
