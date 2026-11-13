"""Verify Mode —— 确定性 Engine 的统一 facade。

Agent 也可以调用同一内核（`run_verify` 工具）；这个 facade 用于 CLI
`--mode verify` / `vagent work --mode verify`，以及 CI。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from src.workbench.api.verify_service import run_verify


def run_goal(goal: str, *, output_root: str = "output",
             target_coverage: Optional[float] = None,
             max_rounds: int = 1, design_style: str = "baseline",
             manual_gate: bool = False, approval: str = "auto",
             checkpointing: bool = False, sim_modes: Optional[list] = None,
             vplan: str = "", rtl_dir: str = "",
             bypass_design_model: bool = False,
             **kwargs: Any) -> Dict[str, Any]:
    text = str(goal or "").strip()
    path = Path(text)
    common = dict(
        output_root=output_root, target=target_coverage,
        max_rounds=int(max_rounds), design_style=design_style,
        manual_gate=bool(manual_gate), approval=approval,
        checkpointing=bool(checkpointing), sim_modes=sim_modes,
        rtl_dir=rtl_dir, bypass_design_model=bypass_design_model,
        origin="mode_verify",
    )
    if vplan or (path.exists() and path.is_dir()):
        result = run_verify(vplan=vplan or text, **common)
    elif path.exists() and path.is_file():
        result = run_verify(spec_file=text, **common)
    else:
        result = run_verify(spec_text=text, **common)
    result = dict(result or {})
    result.setdefault("mode", "verify")
    return result


def exit_code(result: Dict[str, Any]) -> int:
    if result.get("interrupted"):
        return 1
    verdict = str(result.get("verdict") or "").upper()
    if verdict in ("READY", "PASS", "PASS_WITH_CAVEAT"):
        return 0
    if result.get("converged"):
        return 0
    return 0 if not result else 1


def render(result: Dict[str, Any]) -> None:
    print(f"verify: verdict={result.get('verdict') or '?'} "
          f"converged={result.get('converged')} "
          f"coverage={result.get('final_coverage') or result.get('coverage') or '?'}")
    root = result.get("output_root") or result.get("run_dir")
    if root:
        print(f"  run: {root}")


__all__ = ["run_goal", "exit_code", "render"]
