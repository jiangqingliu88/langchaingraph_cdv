"""四个按产物拆分的生成器入口。"""
from .constraint_gen import annotate_coverage_plan, write_constraint_status
from .coverage_gen import write_coverage_plan
from .env_gen import generate_env

__all__ = [
    "generate_env", "write_coverage_plan",
    "write_constraint_status", "annotate_coverage_plan",
    "generate_regression_yaml",
]


def generate_regression_yaml(*args, **kwargs):
    """门面：实际实现在 `tool_find_spec_yaml/generators/regression_gen`。"""
    from src.tools.generation.uvm_tools.tool_find_spec_yaml.generators.regression_gen import (
        _generate_regression_yaml,
    )
    return _generate_regression_yaml(*args, **kwargs)
