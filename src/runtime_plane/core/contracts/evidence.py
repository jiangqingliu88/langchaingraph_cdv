"""EvidenceEnvelope —— 证据包的**基础段**，UVM/SoC/IP 只做 profile。

不强行把三种证据包变成同一种 verdict：
  · UVM profile 保留三态 / caveat / TP 矩阵；
  · SoC profile 的 verdict 写 soc_regression / not_applicable；
  · IP profile 不拿 SoC 覆盖率冒充 measured。

基础段只统一：身份、输入、执行、判定、回放、哈希。谁也不能少，但谁也不必
伪造另一个 profile 的字段。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from src.runtime_plane.core.contracts import versions

EVIDENCE_PROFILES = (
    versions.EVIDENCE_UVM_PROFILE,
    versions.EVIDENCE_SOC_PROFILE,
    versions.EVIDENCE_IP_PROFILE,
)

_REQUIRED = ("schema", "profile", "identity", "inputs", "execution",
             "verdict", "replay", "hashes")
_IDENTITY = ("run_id", "module", "versions")


def build_envelope(*, run_id: str, profile: str, module: str = "",
                   inputs: Optional[Dict[str, Any]] = None,
                   execution: Optional[Dict[str, Any]] = None,
                   verdict: Optional[Dict[str, Any]] = None,
                   replay: Optional[Dict[str, Any]] = None,
                   hashes: Optional[Dict[str, Any]] = None,
                   versions_seen: Optional[Dict[str, Any]] = None,
                   created_at: str = "") -> Dict[str, Any]:
    if profile not in EVIDENCE_PROFILES:
        raise ValueError(f"未知 evidence profile: {profile!r}")
    return {
        "schema": versions.EVIDENCE_ENVELOPE,
        "profile": profile,
        "identity": {
            "run_id": str(run_id or ""),
            "module": str(module or ""),
            "created_at": str(created_at or ""),
            "versions": dict(versions_seen or {}),
        },
        "inputs": dict(inputs or {}),
        "execution": dict(execution or {}),
        "verdict": dict(verdict or {}),
        "replay": dict(replay or {}),
        "hashes": dict(hashes or {}),
    }


def validate_envelope(doc: Any) -> List[Dict[str, str]]:
    """返回问题列表；空列表 = 基础段完整。不校验 profile 的业务语义。"""
    issues: List[Dict[str, str]] = []
    if not isinstance(doc, dict):
        return [{"code": "not_object", "message": "证据 envelope 不是对象"}]
    for key in _REQUIRED:
        if key not in doc:
            issues.append({"code": "missing_field", "message": key})
    if doc.get("schema") != versions.EVIDENCE_ENVELOPE:
        issues.append({"code": "schema", "message": str(doc.get("schema"))})
    if doc.get("profile") not in EVIDENCE_PROFILES:
        issues.append({"code": "profile", "message": str(doc.get("profile"))})
    identity = doc.get("identity")
    if not isinstance(identity, dict):
        issues.append({"code": "identity", "message": "不是对象"})
    else:
        for key in _IDENTITY:
            if key not in identity:
                issues.append({"code": "missing_identity", "message": key})
    for key in ("inputs", "execution", "verdict", "replay", "hashes"):
        if key in doc and not isinstance(doc[key], dict):
            issues.append({"code": "not_object", "message": key})
    return issues
