"""UVM 自动化验证 —— 应用服务 facade（**CLI / Workbench 的唯一入口**）。

预检（输出目录 / VPlan 挂载 / 全量回归开关 / 增量基线）统一在
`VerifyRequest.prepare()`，这里只负责构造请求、调引擎、补上 `output_root`。

    CLI      → run_verify_async / run_multi_module_async（本模块）
    GUI      → run_service（同一份 VerifyRequest，只是换成后台线程）
    引擎     → PipelineExecutionService（**不从这里以外的地方直连**）

不另造引擎：两个入口最终都调同一个 `run_closed_loop_streaming`。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional


async def run_verify_async(*, spec_text: str = "", spec_file: str = "",
                           output_root: str = "output",
                           target: Optional[float] = None, max_rounds: int = 5,
                           design_style: str = "baseline",
                           bypass_design_model: bool = False,
                           rtl_dir: str = "", vplan: str = "",
                           sim_modes=None, manual_gate: bool = True,
                           approval: str = "threshold",
                           checkpointing: bool = True,
                           full_regression: bool = False,
                           incremental_from: str = "",
                           origin: str = "service") -> Dict[str, Any]:
    from src.orchestration_plane.l2.execution import PipelineExecutionService
    from src.orchestration_plane.l2.verify_request import VerifyRequest

    request = VerifyRequest(
        spec_text=spec_text, spec_file=spec_file, output_root=output_root,
        target=target,
        max_rounds=int(max_rounds), design_style=design_style,
        bypass_design_model=bool(bypass_design_model),
        sim_modes=list(sim_modes or []) or None, manual_gate=bool(manual_gate),
        rtl_dir=str(rtl_dir or ""), vplan=str(vplan or ""),
        approval=approval, checkpointing=bool(checkpointing),
        full_regression=bool(full_regression),
        incremental_from=str(incremental_from or ""),
        origin=str(origin or "service"),
    )
    # VPlan execute 的 `-o` 是**精确运行目录**：VPlan 输入必须挂在该目录下
    # （`<run>/inputs/vplan/`），不能再追加时间戳另起一个目录。
    run_root = request.prepare(root=output_root if vplan else None)
    service = PipelineExecutionService.get_instance()
    with request.incremental_env():
        result = await service.run_closed_loop_streaming(
            spec_text=request.resolved_spec(), output_root=str(run_root),
            target=request.target, max_rounds=request.max_rounds,
            design_style=request.design_style,
            bypass_design_model=request.bypass_design_model,
            sim_modes=list(request.sim_modes or []) or None,
            manual_gate=request.manual_gate,
            rtl_dir=request.rtl_dir,
            approval_gate=request.approval_gate(),
            checkpointing=request.checkpointing)
    if isinstance(result, dict):
        result.setdefault("output_root", str(run_root))
    return result


async def run_multi_module_async(module_specs: List[dict],
                                 output_root: str = "output",
                                 target: Optional[float] = None,
                                 max_rounds: int = 5,
                                 design_style: str = "baseline",
                                 max_concurrency: int = 4,
                                 approval: str = "threshold") -> List[dict]:
    """多模块软件流水 —— 与单模块**同一个引擎**，只是并发调度。"""
    from src.orchestration_plane.l2.execution import PipelineExecutionService
    from src.orchestration_plane.l2.verify_request import VerifyRequest

    request = VerifyRequest(output_root=output_root, target=target,
                            max_rounds=int(max_rounds),
                            design_style=design_style, approval=approval)
    service = PipelineExecutionService.get_instance()
    return await service.run_multi_module(
        module_specs=module_specs, output_root=str(request.output_root or "output"),
        target=target, max_rounds=int(max_rounds), design_style=design_style,
        max_concurrency=int(max_concurrency),
        approval_gate=request.approval_gate())


def run_verify(**kwargs) -> Dict[str, Any]:
    return asyncio.run(run_verify_async(**kwargs))


def run_multi_module(**kwargs) -> List[dict]:
    return asyncio.run(run_multi_module_async(**kwargs))


__all__ = ["run_multi_module", "run_multi_module_async", "run_verify",
           "run_verify_async"]
