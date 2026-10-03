"""参数整形 —— 把「吃一个 JSON 字符串」的工具包成「吃关键字参数」的。

`src/tools/debug_tools` 里有几个工具签名是 `fn(input_json: str = "") -> str`：
参数被打包成一个 JSON 字符串（那是给 LLM 的 function-calling 准备的形状，
模型只能传字符串）。界面这边传的是「一个输出目录、一串信号名」，硬要自己
`json.dumps` 再传，等于把调用约定抄进每个模块里。

包一层之后，清单里的绑定就和其它工具一样：

    registry.call("debug.collect_waveform", output_dir="output", signals="clk,rst_n")

**不改变原工具**：这一层只做参数整形，返回的 JSON 字符串照旧由
`binding.normalize` 解释。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from src.tools.debug_tools import main as _debug_main


def json_input(fn: Callable[..., Any]) -> Callable[..., Any]:
    """把 `fn(input_json)` 包成 `wrapper(**kwargs)`。"""

    def wrapper(**kwargs: Any) -> Any:
        return fn(json.dumps(kwargs, ensure_ascii=False))

    wrapper.__name__ = getattr(fn, "__name__", "wrapped")
    wrapper.__doc__ = getattr(fn, "__doc__", None)
    return wrapper


#: 波形收集 —— 原签名 `collect_waveform(input_json)`
collect_waveform = json_input(_debug_main.collect_waveform)

#: 失败用例二分 —— 原签名 `bisect_test(input_json)`
bisect_test = json_input(_debug_main.bisect_test)
