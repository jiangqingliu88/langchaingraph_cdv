"""Coverage Closure —— 应用服务 facade（CLI 与 Workbench 共用）。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional


def run_dir_from_coverage(path: str | Path) -> Path:
    p = Path(path)
    return p.parent if p.name == "coverage" else p


def find_spec(project: str | Path, module: str) -> Optional[Path]:
    project = Path(project)
    for pattern in (f"specs/{module}/*.md", "specs/*/*.md"):
        for p in sorted(project.glob(pattern)):
            if p.is_file():
                return p
    return None


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8", newline="\n")


def _execute_closure(project, run_dir: Path, target: float, spec, rtl,
                     config, output) -> Dict[str, Any]:
    from src.layers.l1_infrastructure.output_config import make_output_root
    from src.layers.l2_orchestration.execution import PipelineExecutionService
    from src.layers.l2_orchestration.governance.approval import create_approval_gate

    run_dir = Path(run_dir)
    rtl_dir = Path(rtl) if rtl else (run_dir / "rtl" if (run_dir / "rtl").is_dir() else None)
    spec_path = Path(spec) if spec else None
    if spec_path is None:
        try:
            spec_doc = json.loads((run_dir / "spec.json").read_text(encoding="utf-8"))
            module = str(spec_doc.get("design_name") or spec_doc.get("module") or "")
        except (OSError, ValueError):
            module = ""
        spec_path = find_spec(project, module)
    spec_text = spec_path.read_text(encoding="utf-8") if spec_path else ""
    out_root = make_output_root(str(output) if output else f"output_closure_{run_dir.name}")
    if config:
        from src.layers.l3_decision.vplan import (
            load_project, materialize_project_inputs)
        materialize_project_inputs(load_project(config), out_root)

    async def _run():
        return await PipelineExecutionService.get_instance().run_closed_loop_streaming(
            spec_text=spec_text, output_root=out_root, target=target,
            design_style="baseline", approval_gate=create_approval_gate("auto"),
            rtl_dir=str(rtl_dir or ""), checkpointing=False)

    asyncio.run(_run())
    from src.core.incremental.run_diff import write_run_diff
    diff = write_run_diff(run_dir, Path(make_output_root(out_root)))
    return {"run_id": Path(make_output_root(out_root)).name,
            "after": diff.get("current", {}).get("coverage", {}),
            "before": diff.get("baseline", {}).get("coverage", {}),
            "deltas": diff.get("deltas", {}), "run_diff": diff.get("path", "")}


def run_closure(*, project: str | Path = ".", coverage: str | Path,
                target: float = 98.0, spec=None, rtl=None, config=None,
                output=None, execute: bool = False) -> Dict[str, Any]:
    from src.core.closure.plan import write_closure_plan

    run_dir = run_dir_from_coverage(coverage)
    plan = write_closure_plan(run_dir, target)
    result = None
    if execute:
        if not plan["actions"] and plan["current_coverage"] >= target:
            result = {"skipped": True, "reason": "已达标"}
        else:
            result = _execute_closure(project, run_dir, target, spec, rtl, config, output)
            _write_json(run_dir / "closure" / "result.json", result)
            plan["execute_result"] = result
            _write_json(Path(plan["path"]), plan)
    return {"plan": plan, "result": result, "run_dir": str(run_dir)}
