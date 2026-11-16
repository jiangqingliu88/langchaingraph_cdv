"""UVM 构建 Agent + verify 子图/工具循环（迁移自 specialists/uvm）。"""

from src.agent_plane._lazy import make_getattr

__all__ = ['UVMCodingAgent', 'build_verify_subgraph', 'create_agent', 'n_verify_agent']

_LAZY = {
    'UVMCodingAgent': (f"{__name__}.agent", 'UVMCodingAgent'),
    'create_agent': (f"{__name__}.agent", 'create_agent'),
    'build_verify_subgraph': (f"{__name__}.graph", 'build_verify_subgraph'),
    'n_verify_agent': (f"{__name__}.loop", 'n_verify_agent'),
}

__getattr__ = make_getattr(globals(), _LAZY, __name__)
