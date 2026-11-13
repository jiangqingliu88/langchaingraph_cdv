"""纯函数节点 · 动作落地（不调 executor 的那几个）

收敛 / 放宽约束 / 扩种 —— 只改状态标志，真正的执行在下游节点。
"""
from __future__ import annotations

from typing import Any, Dict

from datetime import datetime
from pathlib import Path

import structlog

from src.orchestration_plane.l2.runtime import (
    _rt,
)
from src.orchestration_plane.l2.state import PipelineState

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
        from src.runtime_plane.infrastructure.golden_baseline import save_golden_baseline
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
    """扩种：把**回归的基准种子**顺移一段，让下一轮跑没跑过的随机流。

    ⚠️ 这个动作原来是个**静默空转**：它只写 `state.seed`，而那个字段**只被当
    覆盖 agent 的输入**用（`run.py` 的 `{"seed": state.seed}`），回归的 `SEED`
    是写死的 `12345` + case 模型声明的 `base` —— 于是账上记着"扩了种"，仿真跑的
    还是同一批随机流。实测：闭环六轮，覆盖率**每轮钉在 56.2**，而每轮 ucdb 的
    sha256 各不相同（数据在采，采的是同一批激励）。

    现在把偏移**累加**着落到 `coverage/seed_expand.json`（单调递增，不覆盖历史），
    回归生成时读它加到每条 test 的基准种子上（见 `_seed_offset` / `_seed_lines`）。
    """
    import json as _json

    action = state.action()
    count = int((action.params or {}).get("count", 100))
    path = Path(state.output_root) / "coverage" / "seed_expand.json"
    prev = 0
    try:
        if path.is_file():
            prev = int((_json.loads(path.read_text(encoding="utf-8",
                                                    errors="replace")) or {}).get("offset", 0))
    except Exception:                                      # noqa: BLE001 读坏了从头算
        prev = 0
    offset = prev + count
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps(
            {"round": state.round_num, "action": action.action_type,
             "delta": count, "offset": offset},
            ensure_ascii=False), encoding="utf-8")
    except Exception as e:                                  # noqa: BLE001
        logger.warning(f"扩种偏移落盘失败（下一轮仍跑原种子）: {e}")
    logger.info(f"扩种 → 种子偏移 {prev} → **{offset}**（+{count}）"
                f"—— 下一轮回归的每条 test 基准种子顺移 {offset}，"
                f"跑的是没跑过的随机流")
    return {"seed": offset}


