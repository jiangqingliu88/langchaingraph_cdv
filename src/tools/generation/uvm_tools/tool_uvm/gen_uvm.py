#!/usr/bin/env python3
"""gen_uvm.py
Generate UVM SystemVerilog from YAML interface and environment descriptions.

**兼容门面**：实现已按 parsing → models → render → generators 拆分到
`uvm_tools/generation/`，新代码请直接从 `generation.*` 导入。

这里**只保留仍被旧调用方使用的名字**（按全仓 `from ...gen_uvm import X`
统计，不是全量 re-export）—— 旧路径不再无限期背历史包袱。
`python gen_uvm.py` / `python -m ...gen_uvm` 入口照旧。
"""

from __future__ import annotations

from pathlib import Path

try:
    import yaml  # noqa: F401  (旧调用方按名 import；缺依赖时给一句人话)
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: PyYAML is required. Install with: pip install pyyaml"
    ) from exc

try:  # 包内导入（python -m 路径）
    from ..generation.constants import DEFAULT_META, TEMPLATES_DIR, __version__
    from ..generation.generators.cli import main
    from ..generation.generators.orchestrator import (
        SUPPORTED_TOOL_TYPES, UVMGenerator, generate_uvm,
    )
    from ..generation.generators.tasks import AgentRenderTask, EnvironmentRenderTask
    from ..generation.models import (
        AgentModel, BenchAgentEntry, BenchModel, ConstraintModel, EnvironmentModel,
        HarnessModel,
    )
    from ..generation.parsing.environment_specs import (
        _normalize_agents_list, _normalize_batches, _normalize_harness,
        _normalize_register_model, _normalize_scoreboards, _normalize_subenvs,
        _normalize_tests, _normalize_typedefs,
    )
    from ..generation.parsing.yaml_loader import YAMLLoader
    from ..generation.render.jinja_renderer import (
        JinjaRenderer, attr_class_slug, attr_int_value, attr_key,
    )
    from ..generation.render.region_injector import (
        BANNER_MARKER, REGION_MARKER, RegionError, RegionInjector, _make_banner,
    )
except ImportError:  # 直接脚本执行（python gen_uvm.py）
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from generation.constants import (  # type: ignore[no-redef]
        DEFAULT_META, TEMPLATES_DIR, __version__,
    )
    from generation.generators.cli import main  # type: ignore[no-redef]
    from generation.generators.orchestrator import (  # type: ignore[no-redef]
        SUPPORTED_TOOL_TYPES, UVMGenerator, generate_uvm,
    )
    from generation.generators.tasks import (  # type: ignore[no-redef]
        AgentRenderTask, EnvironmentRenderTask,
    )
    from generation.models import (  # type: ignore[no-redef]
        AgentModel, BenchAgentEntry, BenchModel, ConstraintModel, EnvironmentModel,
        HarnessModel,
    )
    from generation.parsing.environment_specs import (  # type: ignore[no-redef]
        _normalize_agents_list, _normalize_batches, _normalize_harness,
        _normalize_register_model, _normalize_scoreboards, _normalize_subenvs,
        _normalize_tests, _normalize_typedefs,
    )
    from generation.parsing.yaml_loader import YAMLLoader  # type: ignore[no-redef]
    from generation.render.jinja_renderer import (  # type: ignore[no-redef]
        JinjaRenderer, attr_class_slug, attr_int_value, attr_key,
    )
    from generation.render.region_injector import (  # type: ignore[no-redef]
        BANNER_MARKER, REGION_MARKER, RegionError, RegionInjector, _make_banner,
    )


if __name__ == "__main__":
    raise SystemExit(main())
