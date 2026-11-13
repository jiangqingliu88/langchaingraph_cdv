"""子 Agent 结果验证 —— COMPLETED ≠ 结论被接受。

除了交付物，还核对 finding 的 file/line/signal 是否真实存在于工程：
`confidence=0.98` 不能代替证据。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List

from .contract import SubagentContract, SubagentResult


def _check_finding(finding: dict, project_root: str | Path | None,
                   issues: List[str]) -> None:
    fid = str(finding.get("id") or "?")
    file_ref = str(finding.get("file") or "").strip()
    if not file_ref:
        if finding.get("signal") or finding.get("finding"):
            issues.append(f"finding {fid} 缺少文件定位")
        return
    base = Path(project_root) if project_root else Path.cwd()
    path = Path(file_ref)
    if not path.is_absolute():
        path = base / path
    if not path.is_file():
        issues.append(f"finding {fid} 文件不存在：{file_ref}")
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        issues.append(f"finding {fid} 文件读不出：{file_ref} ({exc})")
        return
    line = int(finding.get("line") or 0)
    if line and (line < 1 or line > len(lines)):
        issues.append(f"finding {fid} 行号越界：{file_ref}:{line}")
    signal = str(finding.get("signal") or "").strip()
    if signal and signal not in "\n".join(lines):
        issues.append(f"finding {fid} 信号未在文件中出现：{signal}")


def validate_result(contract: SubagentContract, result: SubagentResult,
                    workspace: Any, *,
                    project_root: str | Path | None = None) -> List[str]:
    issues: List[str] = []
    if result.task_id != contract.task_id:
        issues.append(f"task_id 不一致：{result.task_id} != {contract.task_id}")
    if result.status not in ("COMPLETED", "BLOCKED", "FAILED", "TIMEOUT",
                             "CANCELLED"):
        issues.append(f"未知结果状态：{result.status}")
    if result.status == "COMPLETED" and not str(result.summary).strip():
        issues.append("COMPLETED 但没有 summary")
    artifacts = set(workspace.list_artifacts()) if workspace is not None else set()
    declared = set(result.artifacts or [])
    for name in contract.deliverables:
        if name not in artifacts and name not in declared:
            issues.append(f"缺少交付物：{name}")
    for finding in result.findings or []:
        if isinstance(finding, dict):
            _check_finding(finding, project_root, issues)
    if result.status == "COMPLETED" and result.unresolved:
        # 不是错误：显式未决项比假装完成强；主 Agent 会带着它继续。
        issues.append(f"有 {len(result.unresolved)} 个未决项（需主 Agent 处理）")
    return issues


__all__ = ["validate_result"]
