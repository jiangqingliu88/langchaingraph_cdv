"""心智模型 Agent + Mental IR 生成器（迁移自 specialists/mental_model）。"""

from src.agent_plane._lazy import make_getattr

__all__ = ['MentalIRError', 'MentalModelAgent', 'MentalState', 'PROMPT_VERSION', 'arun', 'build_mental_graph', 'create_agent', 'generate_mental_ir', 'run', 'write_mental_ir']

_LAZY = {
    'MentalModelAgent': (f"{__name__}.agent", 'MentalModelAgent'),
    'create_agent': (f"{__name__}.agent", 'create_agent'),
    'MentalState': (f"{__name__}.graph", 'MentalState'),
    'build_mental_graph': (f"{__name__}.graph", 'build_mental_graph'),
    'PROMPT_VERSION': (f"{__name__}.main", 'PROMPT_VERSION'),
    'MentalIRError': (f"{__name__}.main", 'MentalIRError'),
    'arun': (f"{__name__}.main", 'arun'),
    'generate_mental_ir': (f"{__name__}.main", 'generate_mental_ir'),
    'run': (f"{__name__}.main", 'run'),
    'write_mental_ir': ("src.mental_ir_plane", 'write_mental_ir'),
}

__getattr__ = make_getattr(globals(), _LAZY, __name__)
