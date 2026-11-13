"""Job 期望输出登记 —— 「跑完应该有哪些文件」与「实际缺了什么」。

执行层可以声明 `vlog` 应产出 `simv`、`vsim` 应产出 `sim_vsim.log`。
JobSupervisor 本身不判断语义；这里只做**登记与缺口暴露**，缺口进质量门
的 evidence 维度，不在这里炸流程。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from src.runtime_plane.core.jobs.spec import JobResult
from src.runtime_plane.core.runtime.artifacts import ArtifactStore, ArtifactRef


@dataclass
class OutputSpec:
    name: str
    path: str
    kind: str = "output"
    required: bool = True
    when: str = "always"          # always | exit0


class OutputRegistry:
    def __init__(self) -> None:
        self._expected: Dict[str, List[OutputSpec]] = {}

    def expect(self, job_id: str, name: str,
               specs: Sequence[Any] = ()) -> None:
        out: List[OutputSpec] = []
        for spec in specs:
            if isinstance(spec, OutputSpec):
                out.append(spec)
            elif isinstance(spec, dict):
                out.append(OutputSpec(
                    name=str(spec.get("name") or spec.get("path") or ""),
                    path=str(spec.get("path") or ""),
                    kind=str(spec.get("kind") or "output"),
                    required=bool(spec.get("required", True)),
                    when=str(spec.get("when") or "always")))
            elif isinstance(spec, (list, tuple)) and len(spec) >= 2:
                out.append(OutputSpec(name=str(spec[0]), path=str(spec[1])))
        if out:
            self._expected[job_id] = out

    def expected_for(self, job_id: str) -> List[OutputSpec]:
        return list(self._expected.get(job_id) or [])

    def finalize(self, result: JobResult, store: ArtifactStore) -> Dict[str, Any]:
        """登记存在的输出，返回 {registered, missing}。"""
        registered: List[Dict[str, Any]] = []
        missing: List[Dict[str, Any]] = []
        cwd = Path(result.cwd) if result.cwd else Path.cwd()
        skipped_by_status = result.status not in ("completed",)
        for spec in self._expected.get(result.job_id) or []:
            if spec.when == "exit0" and skipped_by_status:
                continue
            path = Path(spec.path)
            if not path.is_absolute():
                path = cwd / path
            if path.is_file():
                ref: ArtifactRef = store.register(
                    spec.kind, path, producer=f"job:{result.name}", round=0)
                registered.append({"name": spec.name, "path": ref.path,
                                   "sha256": ref.sha256, "kind": spec.kind})
            elif spec.required:
                missing.append({"job_id": result.job_id, "name": spec.name,
                                "path": str(path), "required": True})
        return {"registered": registered, "missing": missing}
