"""UVM 自动化验证 —— 应用服务 facade。

CLI `verify` 与 Workbench 的 UVM 服务入口都应调这里；内部仍复用
`PipelineExecutionService`，不另造引擎。
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional


async def run_verify_async(*, spec_text: str = "", output_root: str = "output",
                           target: Optional[float] = None, max_rounds: int = 5,
                           design_style: str = "baseline",
                           bypass_design_model: bool = False,
                           rtl_dir: str = "", casemodel: str = "",
                           sim_modes=None, manual_gate: bool = True,
                           approval: str = "threshold",
                           checkpointing: bool = True) -> Dict[str, Any]:
    from src.layers.l2_orchestration.execution import PipelineExecutionService
    from src.layers.l2_orchestration.governance.approval import create_approval_gate
    from src.layers.l1_infrastructure.layout import casemodel_path
    from src.layers.l1_infrastructure.output_config import make_output_root

    out = make_output_root(output_root)
    if casemodel:
        dest = casemodel_path(out)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(Path(casemodel).read_text(encoding="utf-8"), encoding="utf-8")
    service = PipelineExecutionService.get_instance()
    return await service.run_closed_loop_streaming(
        spec_text=spec_text, output_root=out, target=target,
        max_rounds=int(max_rounds), design_style=design_style,
        bypass_design_model=bool(bypass_design_model),
        sim_modes=list(sim_modes or []) or None,
        manual_gate=bool(manual_gate),
        rtl_dir=str(rtl_dir or ""),
        approval_gate=create_approval_gate(approval),
        checkpointing=bool(checkpointing))


def run_verify(**kwargs) -> Dict[str, Any]:
    return asyncio.run(run_verify_async(**kwargs))
