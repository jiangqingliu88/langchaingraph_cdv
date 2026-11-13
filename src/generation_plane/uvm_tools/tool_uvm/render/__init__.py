"""渲染层 —— 只做 Jinja2 渲染，不判断业务。

`render_checked` 在渲染前校验 ctx 是否包含模板声明的全部 key。这是
`generate_utils` 那个坑的结构化修复：模板支持 `body`、生成器却没传，
以前会静默渲染成 TODO 空壳；现在缺 key 直接抛错。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable


class CtxContractError(ValueError):
    """模板需要的 ctx key 缺失。"""


def render_checked(renderer: Any, template: str, ctx: Dict[str, Any],
                   required_keys: Iterable[str]) -> str:
    """校验 required_keys 后渲染。`None` 视为缺失（模板里 `{% if %}` 会吞掉它）。"""
    missing = [k for k in required_keys if ctx.get(k) is None]
    if missing:
        raise CtxContractError(
            f"模板 {template} 缺少 ctx 键：{'、'.join(missing)} —— "
            f"渲染会静默变成空壳，拒绝生成")
    return renderer.render(template, ctx)


# pragma custom 区域注入（从 gen_uvm 搬出的渲染件）
from .region_injector import (  # noqa: E402,F401
    BANNER, BANNER_MARKER, REGION_MARKER, MergeBlockInfo, MergeFileReport,
    RegionError, RegionInjector, TOOL_VERSION, _make_banner,
)
from .file_ops import (  # noqa: E402,F401
    _clean_generated, _is_generated_file, _write_report_json,
    backup_merge_source,
)
from .templates import (  # noqa: E402,F401
    AGENT_LOOPBACK_TEMPLATES, BENCH_TEMPLATES, CMODEL_TEMPLATES,
    ENVIRONMENT_ATTR_TEST_TEMPLATES, ENVIRONMENT_BATCH_TEST_TEMPLATES,
    ENVIRONMENT_REG_TEST_TEMPLATES, ENVIRONMENT_ROOT_TEMPLATES,
    ENVIRONMENT_SEQ_TEMPLATES, ENVIRONMENT_TEST_TEMPLATES,
    ENV_CONSTRAINT_TEMPLATES, HARNESS_TEMPLATES, INTERFACE_TEMPLATES,
    _split_template_entry,
)
from .jinja_renderer import (  # noqa: E402,F401
    COMPANY_TRADEMARK, COPYRIGHT_YEAR, JinjaRenderer, _attr_slug,
    attr_class_slug, attr_int_value, attr_key, reproducible_now,
)

__all__ = [
    "CtxContractError", "render_checked",
    "BANNER", "BANNER_MARKER", "REGION_MARKER", "MergeBlockInfo",
    "MergeFileReport", "RegionError", "RegionInjector", "TOOL_VERSION",
    "_make_banner",
    "_clean_generated", "_is_generated_file", "_write_report_json",
    "backup_merge_source",
    "AGENT_LOOPBACK_TEMPLATES", "BENCH_TEMPLATES", "CMODEL_TEMPLATES",
    "ENVIRONMENT_ATTR_TEST_TEMPLATES", "ENVIRONMENT_BATCH_TEST_TEMPLATES",
    "ENVIRONMENT_REG_TEST_TEMPLATES", "ENVIRONMENT_ROOT_TEMPLATES",
    "ENVIRONMENT_SEQ_TEMPLATES", "ENVIRONMENT_TEST_TEMPLATES",
    "ENV_CONSTRAINT_TEMPLATES", "HARNESS_TEMPLATES", "INTERFACE_TEMPLATES",
    "_split_template_entry",
    "COMPANY_TRADEMARK", "COPYRIGHT_YEAR", "JinjaRenderer", "_attr_slug",
    "attr_class_slug", "attr_int_value", "attr_key", "reproducible_now",
]
