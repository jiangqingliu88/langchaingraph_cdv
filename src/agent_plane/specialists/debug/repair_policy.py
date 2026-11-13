"""受控修复边界（M4）—— Agent 可以提修复，但不能碰签核事实。

规则：

  · 只能写 staging，不能写项目根 / 证据包 / 契约 / 预算；
  · proposal 必须带诊断证据与 rationale；
  · 路径必须是项目内相对路径，拒绝 `..` / 绝对路径 / symlink 逃逸；
  · 应用后必须由 Engine 重新验证 —— 本模块不宣布 PASS。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

#: 这些前缀/文件是签核事实或治理配置，修复不能直接改。
PROTECTED_PREFIXES = (
    "signoff_evidence/",
    ".signoffai/",
    "contract/",
    "coverage/",
    "config/",
    ".git/",
)
PROTECTED_NAMES = {
    "manifest.json", "report.json", "run.json", "soc_run.json",
    ".env", ".jwt_secret",
}


@dataclass
class RepairProposal:
    target: str
    patch: str
    rationale: str
    diagnosis_evidence: List[str] = field(default_factory=list)
    author: str = "agent"
    max_bytes: int = 512 * 1024


def _is_protected(rel: str) -> bool:
    rel = rel.replace("\\", "/").lstrip("./")
    if rel in PROTECTED_NAMES:
        return True
    if Path(rel).name in PROTECTED_NAMES:
        return True
    return any(rel.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def validate_proposal(proposal: RepairProposal,
                      project_root: str | Path = ".") -> Dict[str, Any]:
    issues: List[str] = []
    target = str(proposal.target or "").replace("\\", "/")
    if not target:
        issues.append("target 为空")
    if Path(target).is_absolute():
        issues.append("target 不能是绝对路径")
    if ".." in Path(target).parts:
        issues.append("target 不能包含 ..")
    if _is_protected(target):
        issues.append(f"target 属于保护路径：{target}")
    if not str(proposal.patch or "").strip():
        issues.append("patch 为空")
    if len(str(proposal.patch or "").encode("utf-8")) > proposal.max_bytes:
        issues.append("patch 超过大小上限")
    if not str(proposal.rationale or "").strip():
        issues.append("缺少 rationale")
    if not proposal.diagnosis_evidence:
        issues.append("缺少 diagnosis_evidence（修复必须有证据）")
    root = Path(project_root).resolve()
    if target and not issues:
        resolved = (root / target).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            issues.append("target 逃逸出项目根")
    return {"ok": not issues, "issues": issues, "target": target}


def stage_patch(proposal: RepairProposal, staging_root: str | Path,
                project_root: str | Path = ".") -> Dict[str, Any]:
    """把修复写进 staging；**绝不写项目根**。返回 Engine 复验所需的引用。"""
    check = validate_proposal(proposal, project_root)
    if not check["ok"]:
        return {"ok": False, "issues": check["issues"]}
    from src.runtime_plane.core.runtime.atomic import atomic_write_text

    root = Path(project_root).resolve()
    staging = Path(staging_root).resolve()
    target = (staging / check["target"]).resolve()
    try:
        target.relative_to(staging)
    except ValueError:
        return {"ok": False, "issues": ["staging 路径逃逸"]}
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, proposal.patch)
    digest = hashlib.sha256(proposal.patch.encode("utf-8")).hexdigest()
    record = {
        "schema": "repair_proposal_v1",
        "target": check["target"],
        "project_root": str(root),
        "staging_path": str(target),
        "patch_sha256": digest,
        "rationale": proposal.rationale,
        "diagnosis_evidence": list(proposal.diagnosis_evidence),
        "author": proposal.author,
        "requires_engine_verification": True,
        "status": "STAGED",
    }
    (staging / "proposal.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return {"ok": True, **record}


def proposal_from_dict(doc: Dict[str, Any]) -> RepairProposal:
    return RepairProposal(
        target=str(doc.get("target") or ""),
        patch=str(doc.get("patch") or ""),
        rationale=str(doc.get("rationale") or ""),
        diagnosis_evidence=[str(x) for x in (doc.get("diagnosis_evidence") or [])],
        author=str(doc.get("author") or "agent"),
        max_bytes=int(doc.get("max_bytes") or 512 * 1024),
    )


__all__ = [
    "PROTECTED_NAMES", "PROTECTED_PREFIXES", "RepairProposal",
    "proposal_from_dict", "stage_patch", "validate_proposal",
]
