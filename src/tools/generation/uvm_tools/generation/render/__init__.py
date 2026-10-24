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


__all__ = ["CtxContractError", "render_checked"]
