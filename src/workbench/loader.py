"""点号路径工厂解析 —— 清单里写的 `factory` 字符串 → 真正的类。

清单存的是字符串（`"src.workbench.modules.debug.sim_log:SimLogModule"`），
好处是模块可以被注释掉、可以让用户自己换实现；代价是需要一层解析。
这一层就是它，而且**只在用到时才 import** —— 清单里列了但没启用的模块，
不会因为依赖缺失而拖垮启动。

为什么不让清单直接写 `python -c` 之外的表达式：那等于把清单变成可执行
代码，审计时没法一眼看出它会加载什么。冒号路径是能 grep 的。
"""
from __future__ import annotations

import importlib
from typing import Any


class FactoryError(ImportError):
    """工厂路径解析失败 —— 消息里带上原字符串，方便直接改清单。"""


def resolve(dotted: str) -> Any:
    """`"a.b.c:Name"` 或 `"a.b.c.Name"` → 该对象。

    两种写法都认：冒号形式是显式的（属性名里不可能有点，不会有歧义），
    点号形式是给手滑写惯了的人兜底。优先按冒号切，没有再逐段回退。
    """
    text = (dotted or "").strip()
    if not text:
        raise FactoryError("工厂路径是空的")

    if ":" in text:
        module_name, _, attr = text.partition(":")
        if not module_name or not attr:
            raise FactoryError(f"工厂路径格式不对：{text!r}（应为 模块:类名）")
        return _attr(module_name, attr, text)

    # 没有冒号：从左到右试「切在哪一段」 —— 命中第一个能 import 的前缀。
    parts = text.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        module_name, attr = ".".join(parts[:cut]), ".".join(parts[cut:])
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        return _attr_from(module, attr, text)
    raise FactoryError(f"工厂路径解析不了：{text!r}")


def _attr(module_name: str, attr: str, original: str) -> Any:
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise FactoryError(f"模块 import 不了（{original!r}）：{exc}") from exc
    return _attr_from(module, attr, original)


def _attr_from(module: Any, attr: str, original: str) -> Any:
    try:
        target = module
        for part in attr.split("."):
            target = getattr(target, part)
    except AttributeError as exc:
        raise FactoryError(f"模块里没有这个名字（{original!r}）：{exc}") from exc
    return target
