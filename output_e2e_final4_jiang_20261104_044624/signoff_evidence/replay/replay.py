#!/usr/bin/env python3
"""离线回放（Tier A）—— **不 import SignOffAI**，只依赖标准库。

用法:  python replay.py [证据包目录]
判据:
  1. 每个文件的 sha256 与 manifest 一致；
  2. package_hash 与"文件集合 + 产物身份"一致；
  3. 由 hard_ok + 未被接受的 caveat 重算三态判定，与记录结论一致。
"""
import hashlib
import json
import sys
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canon(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def main():
    here = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    manifest = json.loads((here / "manifest.json").read_text(encoding="utf-8"))
    issues = []

    for entry in manifest.get("files") or []:
        path = here / entry["path"]
        if not path.is_file():
            issues.append({"check": "missing_file", "path": entry["path"]})
        elif sha256(path) != entry.get("sha256"):
            issues.append({"check": "hash_mismatch", "path": entry["path"]})

    identity = {
        "files": sorted((f["path"], f.get("sha256", "")) for f in manifest.get("files") or []),
        "artifacts": manifest.get("artifacts") or {},
    }
    if hashlib.sha256(canon(identity).encode()).hexdigest() != manifest.get("package_hash"):
        issues.append({"check": "package_hash_mismatch"})
    stored_manifest_hash = manifest.get("manifest_hash")
    calc_manifest_hash = hashlib.sha256(canon(
        {k: v for k, v in manifest.items() if k != "manifest_hash"}).encode()).hexdigest()
    if stored_manifest_hash and stored_manifest_hash != calc_manifest_hash:
        issues.append({"check": "manifest_hash_mismatch"})

    verdict = manifest.get("verdict") or {}
    raw = [c for c in (verdict.get("raw_caveats") or []) if isinstance(c, dict)]
    accepted = set(verdict.get("accepted_codes") or [])
    effective = [c for c in raw if c.get("code") not in accepted]
    hard_ok = bool(verdict.get("hard_ok"))
    recomputed = ("NEEDS_FIX" if not hard_ok
                  else ("PASS_WITH_CAVEAT" if effective else "READY"))
    recorded = verdict.get("verdict")
    if recomputed != recorded:
        issues.append({"check": "verdict_mismatch",
                       "recorded": recorded, "recomputed": recomputed})

    print(json.dumps({
        "ok": not issues,
        "verdict": recorded,
        "recomputed_verdict": recomputed,
        "raw_caveats": len(raw),
        "accepted_caveats": len(accepted),
        "effective_caveats": len(effective),
        "issues": issues,
    }, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
