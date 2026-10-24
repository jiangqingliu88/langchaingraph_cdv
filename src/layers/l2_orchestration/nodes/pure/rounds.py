"""纯函数节点 · 轮次

轮次推进与轮次预算收口 —— 所有**回边**都在 `round_bump` 汇合。
"""
from __future__ import annotations

from typing import Any, Dict

from pathlib import Path
import asyncio

import structlog

from src.layers.l2_orchestration.runtime import (
    recursion_limit,
)
from src.layers.l2_orchestration.state import PipelineState

logger = structlog.get_logger()


async def n_env_arch_check(state: PipelineState, config) -> Dict[str, Any]:
    """env 架构验收：端口归属（静态）+ scoreboard 定向 case（仿真）。

    完全自包含（只读写磁盘），因此不需要状态输入。
    """
    output_root = Path(state.output_root)
    phase = {"name": "env_arch_check", "status": "skipped", "score": 0}
    try:
        from src.tools.generation.uvm_tools.checking.tool_check_env_arch.main import check_env_arch as _check
        from src.tools.common.lib.filelist import build_filelist_for_tb, derive_env_name

        _fl = output_root / "inputs" / "filelists" / "filelist.f"
        if not _fl.exists():
            # 环境名推导有讲究，别在这里手写"取第一个 *_pkg.sv"（那个写法会把
            # 子包 `_parameters_pkg` 当环境包）—— 见 `derive_env_name` 的说明。
            _env_name = derive_env_name(output_root)
            _adir = output_root / "agents"
            _agents = [{"name": d.name} for d in _adir.iterdir() if d.is_dir()] \
                if _adir.exists() else []
            build_filelist_for_tb(output_root, _agents, _env_name, "filelist.f")

        # 把这一轮的仿真业务带下去：波形模式下 scoreboard 那半**关闭**
        #（要波形不要判决，见 `check_scoreboard` 的 docstring）
        _arch = await asyncio.to_thread(_check, str(output_root),
                                       sim_modes=list(state.sim_modes or []))
        _po = _arch.get("port_ownership", {}) or {}
        _sb = _arch.get("scoreboard", {}) or {}
        _status = _arch.get("status", "FAIL")
        _ok = _status == "PASS"
        phase = {
            "name": "env_arch_check",
            "status": "passed" if _ok else ("error" if _status == "EDA_MISSING" else "failed"),
            "score": 100 if _ok else 0,
            "port_ownership": _po.get("status"),
            "scoreboard": _sb.get("status"),
            "reason": (str(_po.get("message", "")) + " | " + str(_sb.get("message", "")))[:240],
        }
        if not _ok:
            logger.warning(f"env 架构验收未通过: {phase['reason']}")
    except Exception as e:
        phase = {"name": "env_arch_check", "status": "error", "score": 0,
                 "reason": str(e)[:160]}
        logger.warning(f"env 架构验收执行失败: {e}")
    return {"phases": [phase]}


async def n_round_bump(state: PipelineState, config) -> Dict[str, Any]:
    """循环闩锁 —— 这就是原来的 `for round_num in range(max_rounds)`。

    round_num / iterations 用 operator.add，所以返回 1 即自增。
    终止不靠递归上限，由各 router 显式检查轮次（见 _have_rounds_left）。
    """
    return {"round_num": 1, "iterations": 1}


def _have_rounds_left(state: PipelineState) -> bool:
    """轮次预算还有没有。

    `n_round_bump` 的 docstring 一直写着"终止靠 router 显式检查轮次（见
    _have_rounds_left）"，但这个函数**从来不存在** —— 于是 `max_rounds` 只被拿去
    算 `recursion_limit`（`_RECURSION_BASE + 12/轮`），没有任何一处真的用它收口。
    后果：覆盖率不达标时闭环一直转，直到 `GraphRecursionError: Recursion limit of
    32 reached`。界面上「冒烟（1 轮）」名副其实地跑了 4 轮，然后以一句框架报错收场。

    `round_num` 在这里已经是**自增之后**的值（router 读到的是本轮更新过的状态），
    所以 `round_num <= max_rounds` 的意思是"这一轮是预算内的，可以跑"。
    """
    return state.round_num <= max(1, state.max_rounds)


