"""
真实覆盖率收集 —— 编译 + 仿真 + vcover merge/report

用法:
    python -m src.runtime_plane.tools.common.lib.collect_real_coverage <output_dir> [--top apb_uart_bench_tb_top]
"""
import os, subprocess, json, sys, re
import builtins
from typing import Optional
from pathlib import Path

from config.settings import questa_exe, questa_home

# 解析 / 合并 / 种子分析在 L3；这里用**延迟包装**保留同名 API，避免
# tools → l3 的模块级静态依赖（Phase 3）。调用方仍可 `from ... import`。
def _parse_cvg_bin_hits(*args, **kwargs):
    from src.ir_plane.decision.evidence.cvg_parse import (
        _parse_cvg_bin_hits as _impl,
    )
    return _impl(*args, **kwargs)


def _parse_cvg_details(*args, **kwargs):
    from src.ir_plane.decision.evidence.cvg_parse import (
        _parse_cvg_details as _impl,
    )
    return _impl(*args, **kwargs)


def _parse_cvg_text(*args, **kwargs):
    from src.ir_plane.decision.evidence.cvg_parse import (
        _parse_cvg_text as _impl,
    )
    return _impl(*args, **kwargs)


def merge_regression_coverage(*args, **kwargs):
    from src.ir_plane.decision.evidence.coverage_merge import (
        merge_regression_coverage as _impl,
    )
    return _impl(*args, **kwargs)


def analyze_seed_diversity(*args, **kwargs):
    from src.ir_plane.decision.evidence.seed_diversity import (
        analyze_seed_diversity as _impl,
    )
    return _impl(*args, **kwargs)


# ── 兼容入口：实现在 coverage_collect / coverage_matrix ──
from .coverage_collect import (  # noqa: F401
    _discover_dut_name, _parse_vcover_text, build_rtl_filelist,
    compile_with_coverage, parse_coverage_report, parse_toggle_details, run,
    simulate_with_coverage,
)
from .coverage_matrix import (  # noqa: F401
    _artifact_manifest, _case_cov_matrix, _lookup_hits, _owned_bins,
    _read_testpoints, _semantic_validations, _stage_of, _status_for,
    _tp_matrix,
)
