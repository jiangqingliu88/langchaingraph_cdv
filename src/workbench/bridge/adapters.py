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

#: 失败用例集合分批缩小 —— 原签名 `bisect_failed_tests(input_json)`
#: （原名 bisect_test，易被误读成 git bisect 那样的版本溯源；见工具 docstring）
bisect_failed_tests = json_input(_debug_main.bisect_failed_tests)


# ═══════════════════════════════════════════════════════════════
# 流程结构 —— 读领域自己的阶段模型
# ═══════════════════════════════════════════════════════════════

def stage_flow() -> dict:
    """闭环流程的**结构**：7 个阶段组 + 各自成员节点 + 那条回边。

    **为什么放在这里而不是 `src/tools/`**：工具层不许 import 层代码
    （见 `tool_layer_architecture.md` §4.1 的三层职责）。`src/workbench/` 是
    唯一允许同时 import 两边的例外，所以"把领域阶段模型翻译成界面吃得下的
    dict"这件事落在 bridge 里。

    数据来自 `stages.py` 的 `grouped()` —— 那份表本来就是"按概念顺序排、供界面
    建树"的。**别在界面侧再抄一份阶段清单**：抄了就是第二份真相，改了图没改界面
    就没人发现。
    """
    from src.layers.l2_orchestration import stages

    groups = [{"id": gid, "title": gtitle,
               "nodes": [{"id": s.id, "title": s.title, "executor": s.executor,
                          "round_scoped": s.round_scoped} for s in specs]}
              for gid, gtitle, specs in stages.grouped()]
    return {
        "groups": groups,
        #: 每轮跑完不达标就回边的位置 —— `graph.py` 里是
        #: `action → round_bump → ops`，即「决策与收敛」转回「编译与仿真」。
        #: 拓扑的权威定义在 `graph.py`；这里只标出**给界面画回边用**的那一条。
        "loop": {"from": "converge", "to": "exec"},
    }
