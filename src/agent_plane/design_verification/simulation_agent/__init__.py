"""仿真/单测 Agent + 纯 SV testbench 生成与执行（迁移自 specialists/unit_testing）。"""

from src.agent_plane._lazy import make_getattr

__all__ = ['PROMPT_VERSION', 'SimulationAgent', 'SpecialistError', 'UnitTestState', 'arun', 'build_unit_test_graph', 'create_agent', 'generate_tb', 'run', 'run_async']

_LAZY = {
    'SimulationAgent': (f"{__name__}.agent", 'SimulationAgent'),
    'create_agent': (f"{__name__}.agent", 'create_agent'),
    'UnitTestState': (f"{__name__}.graph", 'UnitTestState'),
    'build_unit_test_graph': (f"{__name__}.graph", 'build_unit_test_graph'),
    'PROMPT_VERSION': (f"{__name__}.main", 'PROMPT_VERSION'),
    'SpecialistError': (f"{__name__}.main", 'SpecialistError'),
    'arun': (f"{__name__}.main", 'arun'),
    'generate_tb': (f"{__name__}.main", 'generate_tb'),
    'run': (f"{__name__}.main", 'run'),
    'run_async': (f"{__name__}.main", 'run_async'),
}

__getattr__ = make_getattr(globals(), _LAZY, __name__)
