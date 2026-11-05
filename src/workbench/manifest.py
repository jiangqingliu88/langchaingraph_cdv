"""读界面清单 —— YAML 文本 → `WorkbenchManifest`。

错误处理是这里的全部价值。清单是**用户手写的**，所以最常见的失败不是
「程序有 bug」而是「键名拼错 / 缩进错了 / 引用了一个不存在的 group」。
这几种都必须变成**一句话能照着改**的消息，而不是 pydantic 的原始 traceback：

    清单解析失败：config/workbench.yaml
      · modules.0.area: Input should be 'center', 'left', 'right' or 'bottom'
      · modules.1.group: 模块 'debug.bisect' 的 group='dbg' 不在 groups 里…

顺带一提：本模块不 import Qt，所以「清单写得对不对」可以脱离界面单独回答。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

import yaml
from pydantic import ValidationError

from .spec import WorkbenchManifest


class ManifestError(ValueError):
    """清单读不进来 / 不合契约。消息是给人看的，多行。"""

    def __init__(self, source: str, detail: str) -> None:
        self.source = source
        self.detail = detail
        super().__init__(f"清单解析失败：{source}\n{detail}")


def load_manifest(path: Any) -> WorkbenchManifest:
    """从文件读清单。文件不存在 / YAML 语法错 / 不符合契约都会抛 ManifestError。"""
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(str(target), f"  · 读不了文件：{exc}") from exc
    return load_manifest_text(text, source=str(target))


def load_manifest_text(text: str, source: str = "<文本>") -> WorkbenchManifest:
    """从字符串读清单 —— 测试与「粘贴一份清单进来试试」用这个。"""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(source, f"  · YAML 语法错：{exc}") from exc

    if data is None:
        raise ManifestError(source, "  · 文件是空的 —— 至少要写出 modules 列表")
    if not isinstance(data, dict):
        raise ManifestError(
            source,
            f"  · 顶层应是一个映射（键值对），实际是 {type(data).__name__}")

    try:
        return WorkbenchManifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestError(source, _format_errors(exc.errors())) from exc


def _format_errors(errors: List[dict]) -> str:
    """把 pydantic 的错误列表压成「字段路径: 说明」的若干行。

    `model_validator` 抛出的 ValueError 会被 pydantic 统一冠上
    `Value error, ` 前缀且 `loc` 为空 —— 那层包装对读消息的人没有信息量，
    去掉；本来就没有字段路径的（跨字段校验），也不用硬编一个。
    """
    lines: List[str] = []
    for err in errors:
        loc = ".".join(str(part) for part in err.get("loc", ()))
        message = str(err.get("msg", "")).removeprefix("Value error, ")
        lines.append(f"  · {f'{loc}: ' if loc else ''}{message}")
    return "\n".join(lines) or "  · 未知错误"


def try_load_manifest(path: Any) -> tuple:
    """`(manifest, error)` 二选一 —— 给「不要抛异常」的调用方用。

    启动时想「清单坏了也要把窗口开出来，用内置默认清单兜底」就会用这个：
    抛异常的话用户看到的是闪退，而不是「清单坏了，先用默认的」。
    """
    try:
        return load_manifest(path), None
    except ManifestError as exc:
        return None, exc


def builtin_manifest() -> WorkbenchManifest:
    """兜底清单 —— 清单文件丢了也要能起一个能干活的窗口。

    故意做得很小：只有三条业务线的分组，没有模块。界面会提示「清单为空」，
    用户按「文件 → 载入清单」即可。给一个假的模块列表反而会让人以为加载
    成功了。
    """
    from .spec import GroupSpec

    return WorkbenchManifest(
        groups=[
            GroupSpec(id="debug", title="调试技术", order=10),
            GroupSpec(id="ide", title="集成设计环境", order=20),
            GroupSpec(id="vms", title="验证管理系统", order=30),
        ],
        modules=[],
    )


def describe(manifest: Optional[WorkbenchManifest]) -> str:
    """一行摘要 —— 状态栏与日志用。"""
    if manifest is None:
        return "清单：无"
    return (f"清单：{len(manifest.enabled_modules())} 个模块 / "
            f"{len(manifest.groups)} 条业务线")
