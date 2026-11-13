"""Evidence v2 —— 完整性 / 有效性 / 可信度分开判断。

文件存在 ≠ 证据有效；哈希对得上 ≠ 结论可信。这里只做**确定性**检查：

  · completeness：必需 section 是否齐全；
  · validity：每个文件是否存在、sha256 是否匹配；
  · trust：manifest 是否带 package_hash / envelope / manifest_hash；
  · staleness：provenance 里的输入 hash 与当前输入是否一致。

不调用 LLM、不修改证据包。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_INCOMPLETE = "INCOMPLETE"

REQUIRED_SECTIONS = ("inputs", "execution")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def evaluate_package(package: str | Path,
                     required_sections: Iterable[str] = REQUIRED_SECTIONS
                     ) -> Dict[str, Any]:
    package = Path(package)
    manifest_path = package / "manifest.json"
    if not manifest_path.is_file():
        return {"schema": "evidence_audit_v2", "status": STATUS_INCOMPLETE,
                "reason": "signoff_evidence/manifest.json 不存在",
                "completeness": {"ok": False, "missing_sections": list(required_sections)},
                "validity": {"ok": False, "checked": 0, "missing": [], "mismatch": []},
                "trust": {"ok": False}}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8",
                                                     errors="replace"))
    except (OSError, ValueError) as exc:
        return {"schema": "evidence_audit_v2", "status": STATUS_FAIL,
                "reason": f"manifest 不可读: {exc}",
                "completeness": {"ok": False, "missing_sections": []},
                "validity": {"ok": False, "checked": 0, "missing": [], "mismatch": []},
                "trust": {"ok": False}}

    files = [f for f in (manifest.get("files") or []) if isinstance(f, dict)]
    sections = {str(f.get("section") or "") for f in files}
    missing_sections = [s for s in required_sections if s not in sections]

    missing: List[str] = []
    mismatch: List[Dict[str, str]] = []
    for entry in files:
        rel = str(entry.get("path") or "")
        if not rel:
            continue
        path = package / rel
        if not path.is_file():
            missing.append(rel)
            continue
        expected = str(entry.get("sha256") or "")
        if expected and _sha256(path) != expected:
            mismatch.append({"path": rel, "expected": expected})

    trust_keys = ("package_hash", "envelope", "manifest_hash")
    trust = {k: bool(manifest.get(k)) for k in trust_keys}
    trust_ok = all(trust.values())

    validity_ok = not missing and not mismatch
    completeness_ok = not missing_sections and bool(files)
    if not validity_ok:
        status, reason = STATUS_FAIL, "证据文件缺失或哈希不匹配"
    elif not completeness_ok:
        status, reason = STATUS_INCOMPLETE, "必需 section 不完整"
    elif not trust_ok:
        status, reason = STATUS_INCOMPLETE, "manifest 缺少 package_hash/envelope/manifest_hash"
    else:
        status, reason = STATUS_PASS, "证据完整、有效、可追溯"

    return {
        "schema": "evidence_audit_v2",
        "status": status,
        "reason": reason,
        "completeness": {"ok": completeness_ok,
                         "sections": sorted(sections),
                         "missing_sections": missing_sections},
        "validity": {"ok": validity_ok, "checked": len(files),
                     "missing": missing, "mismatch": mismatch},
        "trust": {"ok": trust_ok, **trust},
    }


def stale_inputs(provenance: str | Path,
                 current: Dict[str, str]) -> List[Dict[str, Any]]:
    """provenance 中 artifact 节点与当前输入 hash 不一致 → 失效列表。

    `current`：`{相对路径: sha256}`。没有出现在 `current` 的节点不判断
    （不知道当前值就不冒充失效）。
    """
    path = Path(provenance)
    if not path.is_file():
        return []
    stale: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("kind") != "artifact":
            continue
        attrs = row.get("attrs") or {}
        rel = str(attrs.get("path") or attrs.get("source") or row.get("label") or "")
        rel = rel.replace("\\", "/")
        expected = str(row.get("sha256") or "")
        if rel in current and expected and current[rel] != expected:
            stale.append({"path": rel, "recorded": expected,
                          "current": current[rel], "node": row.get("id")})
    return stale


def hash_inputs(paths: Iterable[str | Path], root: str | Path = ".") -> Dict[str, str]:
    root = Path(root)
    out: Dict[str, str] = {}
    for p in paths:
        path = Path(p)
        rel = path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
        if path.is_file():
            out[rel] = _sha256(path)
    return out


__all__ = [
    "REQUIRED_SECTIONS", "STATUS_FAIL", "STATUS_INCOMPLETE", "STATUS_PASS",
    "evaluate_package", "hash_inputs", "stale_inputs",
]
