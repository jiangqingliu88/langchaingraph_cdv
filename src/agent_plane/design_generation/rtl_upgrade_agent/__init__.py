"""RTL 升级 Agent + 窄沙箱设计工具/子图（迁移自 specialists/rtl_designer）。"""

from src.agent_plane._lazy import make_getattr

__all__ = ['RTLUpgradeAgent', 'build_design_subgraph', 'build_design_tools', 'create_agent', 'n_design_agent']

_LAZY = {
    'RTLUpgradeAgent': (f"{__name__}.agent", 'RTLUpgradeAgent'),
    'create_agent': (f"{__name__}.agent", 'create_agent'),
    'build_design_tools': (f"{__name__}.tools", 'build_design_tools'),
    'build_design_subgraph': (f"{__name__}.graph", 'build_design_subgraph'),
    'n_design_agent': (f"{__name__}.loop", 'n_design_agent'),
}

__getattr__ = make_getattr(globals(), _LAZY, __name__)
