"""纯函数节点 · 动作落地（不调 executor 的那几个）

收敛 / 放宽约束 / 扩种 —— 只改状态标志，真正的执行在下游节点。
"""
from __future__ import annotations

from typing import Any, Dict

from datetime import datetime
from pathlib import Path

import structlog

from src.layers.l2_orchestration.runtime import (
    _rt,
)
from src.layers.l2_orchestration.state import PipelineState

logger = structlog.get_logger()


async def n_apply_converge(state: PipelineState, config) -> Dict[str, Any]:
    """达标收敛：保存黄金基线 + 版本固化（git tag + 清单），然后离开循环。"""
    rt = _rt(config)
    action = state.action()
    phases = []
    _excl = state.exclude_effect.get("excluded", 0)
    _note = (f"（有效覆盖率 {state.effective_coverage}%，Exclude {_excl} 点）"
             if _excl else "")
    logger.info(f"闭环收敛: 覆盖率 {state.final_coverage}% ≥ {state.target}%{_note}")

    try:
        from src.layers.l1_infrastructure.golden_baseline import save_golden_baseline
        golden = save_golden_baseline(Path(state.output_root),
                                     {"functional": state.final_coverage}, state.target)
        if golden:
            logger.info(f"黄金基线已保存: {golden}")
            phases.append({"name": "golden_baseline", "status": "saved", "path": golden})
    except Exception as e:
        logger.warning(f"黄金基线保存失败: {e}")

    try:
        rt.infra.write_version_manifest({
            "final_coverage": state.final_coverage,
            "effective_coverage": state.effective_coverage,
            "exclude_effect": state.exclude_effect,
            "target": state.target, "iterations": state.iterations,
        })
        tag = f"signoff_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        tr = rt.infra.git_tag(tag, f"coverage {state.final_coverage}%")
        if tr.get("tagged"):
            logger.info(f"版本已打 tag: {tag}")
            phases.append({"name": "git_tag", "status": "tagged", "tag": tag})
    except Exception as e:
        logger.warning(f"版本固化失败: {e}")

    return {"interrupted": True, "terminal_reason": "converged", "phases": phases}


async def n_apply_relax(state: PipelineState, config) -> Dict[str, Any]:
    rt = _rt(config)
    action = state.action()
    # 放宽约束：文本级修改 transaction 约束，下一轮重新编译仿真
    rt.service._relax_transaction_constraints(
        state.output_root, (action.params or {}).get("gaps", []))
    logger.info(f"放宽约束: {action.reason}")
    return {}


async def n_apply_expand_seeds(state: PipelineState, config) -> Dict[str, Any]:
    action = state.action()
    count = int((action.params or {}).get("count", 100))
    logger.info(f"扩种 → seed += {count}（覆盖率停滞，尝试新随机激励）")
    return {"seed": count}


