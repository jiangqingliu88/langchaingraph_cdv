"""功能覆盖率 Agent + 只读覆盖率工具/子图（迁移自 specialists/functional_coverage）。"""

from src.agent_plane._lazy import make_getattr

__all__ = ['FunctionalCoverageAgent', 'ListCoverageFilesTool', 'ReadCoverageTool', 'build_coverage_subgraph', 'build_coverage_tools', 'create_agent', 'n_coverage_agent']

_LAZY = {
    'FunctionalCoverageAgent': (f"{__name__}.agent", 'FunctionalCoverageAgent'),
    'create_agent': (f"{__name__}.agent", 'create_agent'),
    'ReadCoverageTool': (f"{__name__}.tools", 'ReadCoverageTool'),
    'ListCoverageFilesTool': (f"{__name__}.tools", 'ListCoverageFilesTool'),
    'build_coverage_tools': (f"{__name__}.tools", 'build_coverage_tools'),
    'build_coverage_subgraph': (f"{__name__}.graph", 'build_coverage_subgraph'),
    'n_coverage_agent': (f"{__name__}.loop", 'n_coverage_agent'),
}

__getattr__ = make_getattr(globals(), _LAZY, __name__)
