"""将旧生成器接到 ReAct Tool 协议；不为新角色伪造供应商能力。"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Callable

from .tools import named_tool


def legacy_function_tool(
    name: str, description: str, function: Callable[..., Any], *, root: str | Path, output_root: str = ""
) -> Any:
    """按原函数签名传关键字参数，过滤模型擅自补充的 kwargs。

    未配置输出目录时，不允许借用 ``output_dir`` 作为任意路径逃生口。需要落盘
    的工具必须在构造时给出约束在 workspace/output/review_bundle 内的目录。
    纯内存的现有分析/生成器没有这个限制，但仍走实际调用与错误记录。
    """
    signature = inspect.signature(function)
    location = Path(output_root).resolve() if output_root else None
    workspace = Path(root).resolve()
    if location is not None:
        location.relative_to(workspace)
        first = location.relative_to(workspace).parts[0]
        if first not in {"output", "review_bundle"}:
            raise ValueError(f"{name} 的输出只能在 output/review_bundle 之内")
    for path in location.parents if location is not None else ():
        if path.name in {".git", ".env", ".signoffai", ".venv", "venv_broken", "venv"}:
            raise ValueError("输出目录不能落在受保护的会话或环境目录")

    def call(args: dict[str, Any]) -> Any:
        if location is None and name.startswith(("store_", "write_", "run_")):
            raise ValueError(f"{name} 未配置受限 output_root，拒绝写入或执行")
        allowed = set(signature.parameters)
        kwargs = {key: value for key, value in args.items() if key in allowed}
        missing = [
            n for n, p in signature.parameters.items() if p.default is inspect.Parameter.empty and n not in kwargs
        ]
        if missing:
            raise ValueError(f"{name} 缺少原生成器参数：{missing}")
        for slot in ("root", "output_root", "output_dir", "workdir"):
            if slot in allowed and location is not None and slot not in kwargs:
                if slot == "root":
                    kwargs[slot] = workspace
                else:
                    kwargs[slot] = location
        if location is None:
            for slot in ("root", "output_root", "output_dir", "workdir"):
                if slot in kwargs and kwargs[slot] not in (None, ""):
                    raise ValueError(f"{name} 未配置受限输出目录，拒绝写入 {slot}")
        return function(**kwargs)

    return named_tool(name, description, call)
