"""回归产物生成器门面 —— 实际实现在 tool_find_spec_yaml/generators。

搬迁分两步：先把稳定入口放到 `generation/generators`，实现仍留在原处，
避免一次性搬动 600 行依赖（`_load_spec` 等）。后续实现迁入后本文件改 import。
"""
from src.tools.generation.uvm_tools.tool_find_spec_yaml.generators.regression_gen import (  # noqa: F401
    _dedupe_loopback_tests, _generate_regression_yaml, _is_agent_active,
    _seed_lines, _seed_offset, _seed_plan, _tp_regression_lines,
)
