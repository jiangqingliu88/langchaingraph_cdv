"""形式验证 Agent + 独立 FormalPlan 生成器（迁移自 specialists/formal）。"""

from src.agent_plane._lazy import make_getattr

__all__ = ['FormalAgent', 'FormalState', 'PROMPT_VERSION', 'SpecialistError', 'arun', 'build_formal_graph', 'create_agent', 'generate_formal_plan', 'run', 'store_formal_plan']

_LAZY = {
    'FormalAgent': (f"{__name__}.agent", 'FormalAgent'),
    'create_agent': (f"{__name__}.agent", 'create_agent'),
    'FormalState': (f"{__name__}.graph", 'FormalState'),
    'build_formal_graph': (f"{__name__}.graph", 'build_formal_graph'),
    'PROMPT_VERSION': (f"{__name__}.main", 'PROMPT_VERSION'),
    'SpecialistError': (f"{__name__}.main", 'SpecialistError'),
    'arun': (f"{__name__}.main", 'arun'),
    'generate_formal_plan': (f"{__name__}.main", 'generate_formal_plan'),
    'run': (f"{__name__}.main", 'run'),
    'store_formal_plan': (f"{__name__}.main", 'store_formal_plan'),
}

__getattr__ = make_getattr(globals(), _LAZY, __name__)
