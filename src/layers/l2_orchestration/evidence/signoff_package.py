"""签核证据包 v2 —— **可交换、可自校验、可离线回放**。

## v1 缺的是什么

`signoff_evidence.json`（v1）把结论收成了一份 JSON，但它仍然是
"SignOffAI 自己说自己"：

  · 没有**版本绑定** —— 数字变了，没人知道是工具变了、库变了还是模型变了；
  · 没有**固定目录布局** —— 收件人得先读代码才知道哪些文件是证据；
  · 没有**离线回放** —— 要复核结论必须装 SignOffAI；
  · 路径是绝对的 —— 换台机器证据就"对不上"。

v2 的做法是三件事：

  1. **目录即契约**：`manifest.json / inputs/ / execution/ / verdict/ / replay/`；
  2. **每个文件都带 sha256**，`package_hash` 覆盖"文件集合 + 产物身份"；
  3. **生成一份不依赖 SignOffAI 的 `replay/replay.py`**（只 use stdlib），
     它重算哈希、重算三态判定，并打印与记录结论是否一致。

## 两种回放

  · **Tier A（默认）**：不跑 EDA，用记录下来的 `tp_matrix` / `coverage_result`
    重算判定 —— 回答"结论是否由这些证据支持"。
  · **Tier B（可选）**：有 EDA 时重跑回归。`replay/recipe.json` 记录命令与
    seed，但 v1 不自动执行（避免把"证据复核"变成"再跑一遍仿真"）。

## 与 `manifest.py` 的分工

`manifest.py` 是**执行轨迹**的 manifest（phase/字段级哈希，服务 `dump`）；
本模块是**签核结论**的证据包。两者都在 `evidence/` 下，但读者不同：
前者回答"这一轮怎么跑出来的"，后者回答"凭什么签/不签"。
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = "signoff_evidence_v2"

#: 证据包各段要收的**源文件候选**（相对 run 目录）。
#: 不存在就跳过 —— 不写空占位：缺了什么是事实，应该能被看见。
SECTION_FILES: Dict[str, Tuple[str, ...]] = {
    "inputs": (
        "spec.json",
        "inputs/casemodel.yaml",
        "inputs/yaml/uvm/constraint.yaml",
        "inputs/yaml/uvm/models.yaml",
        "coverage/coverage_plan.yaml",
        "coverage/testpoints.json",
        "coverage/association_report.json",
        "coverage/constraint_status.json",
        "signoff_policy.yaml",
    ),
    "execution": (
        "regression_run/report.json",
        "sim/coverage/coverage_result.json",
        "coverage/tp_matrix.json",
        "coverage/plan_merge_manifest.json",
        "coverage/seed_diversity.json",
        "coverage/sim_reward.json",
        "coverage/knowledge_graph.json",
        "docs/tool_receipts.jsonl",
        "docs/llm_audit.jsonl",
    ),
    "verdict": (
        # `report.json` 在证据包之后才写（它要带 package_hash），所以不进包；
        # 包里的权威结论是 `manifest.json` 的 `verdict` 段 + `signoff_evidence.json`。
        "signoff_evidence.json",
        "docs/file_change_chain.json",
        "caveats.json",
    ),
}


def sha256_file(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False,
                   default=str).encode("utf-8")).hexdigest()


def _rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def collect_versions() -> Dict[str, Any]:
    """工具链版本绑定 —— 数字变化时先回答"是谁变了"。

    不假装知道所有版本：`vlog -version` 超时/不存在就记 `available: false`，
    不编一个版本号。包版本能读到的读，读不到留空。
    """
    versions: Dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "signoffai": "",
        "questa": {"available": False, "version": ""},
        "packages": {},
    }
    try:
        import importlib.metadata as md

        for pkg in ("pydantic", "jinja2", "langgraph", "langchain-core"):
            try:
                versions["packages"][pkg] = md.version(pkg)
            except Exception:                       # noqa: BLE001
                versions["packages"][pkg] = ""
    except Exception:                               # noqa: BLE001
        pass
    try:
        from config.settings import questa_exe

        vlog = questa_exe("vlog.exe")
        if os.path.exists(vlog):
            proc = subprocess.run([vlog, "-version"], capture_output=True,
                                  text=True, errors="replace", timeout=8)
            out = ((proc.stdout or "") + (proc.stderr or "")).strip()
            versions["questa"] = {"available": True,
                                  "version": out.splitlines()[0][:160] if out else ""}
    except Exception as e:                          # noqa: BLE001
        versions["questa"] = {"available": False, "version": "", "error": str(e)[:160]}
    return versions


# ═══════════════════════════════════════════════════════════
# 模块策略
# ═══════════════════════════════════════════════════════════

def load_policy(output_dir: Path, module: str,
                project_root: Optional[Path] = None) -> Tuple[Dict[str, Any], str]:
    """按模块加载签核策略（caveat 接受 / 是否要求参考模型与基线）。

    查找顺序（**第一个存在的赢**）：
      1. `<run>/signoff_policy.yaml` —— 本次运行显式带的；
      2. `<repo>/specs/<module>/signoff_policy.yaml` —— 与规格同版本；
      3. `<repo>/config/signoff_policy/<module>.yaml` —— 全局兜底。

    没有策略文件时返回**保守默认**：不要求参考模型（否则所有历史 run 都被
    阻断），但要求基线（RTL 存在时）且**不接受任何 caveat**。
    """
    root = Path(project_root or ".")
    candidates = [
        output_dir / "signoff_policy.yaml",
        root / "specs" / str(module) / "signoff_policy.yaml",
        root / "config" / "signoff_policy" / f"{module}.yaml",
    ]
    source = ""
    raw: Dict[str, Any] = {}
    for p in candidates:
        if p.is_file():
            try:
                import yaml

                doc = yaml.safe_load(p.read_text(encoding="utf-8", errors="replace"))
                if isinstance(doc, dict):
                    raw, source = doc, str(p)
                    break
            except Exception:                       # noqa: BLE001 坏策略文件不阻断
                continue

    accepted: Dict[str, Dict[str, Any]] = {}
    for code, val in (raw.get("accepted_caveats") or {}).items():
        if isinstance(val, dict):
            accepted[str(code)] = {
                "accepted": bool(val.get("accepted")),
                "approver": str(val.get("approver") or ""),
                "reason": str(val.get("reason") or ""),
            }
        else:
            accepted[str(code)] = {"accepted": bool(val), "approver": "", "reason": ""}
    for item in (raw.get("caveat_policy") or []):
        if isinstance(item, dict) and item.get("code"):
            accepted[str(item["code"])] = {
                "accepted": bool(item.get("accepted")),
                "approver": str(item.get("approver") or ""),
                "reason": str(item.get("reason") or ""),
            }

    issues: List[str] = []
    if raw:
        if not isinstance(raw.get("require_ref_model", False), bool):
            issues.append("require_ref_model 必须是布尔值")
        if not isinstance(raw.get("require_baseline", True), bool):
            issues.append("require_baseline 必须是布尔值")
        if not isinstance(raw.get("accepted_caveats", {}), dict):
            issues.append("accepted_caveats 必须是 code → {accepted, approver, reason} 的映射")
        for code, val in accepted.items():
            if val.get("accepted") and (not val.get("approver") or not val.get("reason")):
                issues.append(f"accepted_caveats.{code}: 接受 caveat 必须写 approver 与 reason")

    policy = {
        "schema": "signoff_policy_v1",
        "module": module,
        "source": source,
        "require_ref_model": bool(raw.get("require_ref_model", False)),
        "require_baseline": bool(raw.get("require_baseline", True)),
        "accepted_caveats": accepted,
        "issues": issues,
        "raw": raw,
    }
    return policy, source


def write_policy_snapshot(output_dir: Path, policy: Dict[str, Any]) -> str:
    """把实际生效的策略复制进 run 目录（证据包 inputs 会收它）。"""
    path = output_dir / "signoff_policy.yaml"
    try:
        import yaml

        path.write_text(yaml.safe_dump(policy.get("raw") or {
            "require_ref_model": policy.get("require_ref_model"),
            "require_baseline": policy.get("require_baseline"),
            "accepted_caveats": policy.get("accepted_caveats") or {},
            "_effective_source": policy.get("source") or "default",
        }, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return str(path)
    except Exception:                               # noqa: BLE001
        return ""


# ═══════════════════════════════════════════════════════════
# 写包
# ═══════════════════════════════════════════════════════════

def write_package(output_dir: Path, manifest: Dict[str, Any],
                  project_root: Optional[Path] = None) -> Dict[str, Any]:
    """把 v2 证据包写到 `<run>/signoff_evidence/`，返回带哈希的 manifest。

    `manifest` 由 audit 提供（已含 verdict / tp_matrix / coverage / versions
    的语义部分）；本函数负责**文件身份**与**目录布局**。
    """
    output_dir = Path(output_dir).resolve()
    root = Path(project_root or ".").resolve()
    final_pkg = output_dir / "signoff_evidence"
    # **原子写**：先写临时目录，manifest 最后写，再整体改名。
    # 中途失败只会留下 `signoff_evidence.tmp/`（下一次覆盖），不会出现
    # "看起来有包、实际缺文件"的半成品。
    pkg = output_dir / "signoff_evidence.tmp"
    shutil.rmtree(pkg, ignore_errors=True)
    pkg.mkdir(parents=True, exist_ok=True)

    files: List[Dict[str, Any]] = []
    for section, candidates in SECTION_FILES.items():
        target_dir = pkg / section
        target_dir.mkdir(parents=True, exist_ok=True)
        for rel in candidates:
            src = output_dir / rel
            if not src.is_file():
                continue
            # 包内路径：
            #   inputs/ 本来就是 run 的相对路径（`inputs/...` 或 `coverage/...`）；
            #   execution/、verdict/ 统一挂到各自段下。
            # 不用 `section/rel` 一刀切 —— 那会拼出 `inputs/inputs/casemodel.yaml`。
            if section == "inputs":
                dst_rel = (Path(rel).as_posix() if rel.startswith("inputs/")
                           else f"inputs/{Path(rel).as_posix()}")
            else:
                dst_rel = f"{section}/{Path(rel).as_posix()}"
            dst = pkg / dst_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
            except OSError:
                continue
            files.append({
                "section": section,
                "path": dst_rel,
                "source": rel,
                "sha256": sha256_file(dst),
                "size": dst.stat().st_size,
            })

    # 生成离线回放脚本（materials 都在包里，脚本不 import 本项目）
    replay_dir = pkg / "replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    (replay_dir / "replay.py").write_text(_REPLAY_SCRIPT, encoding="utf-8")
    recipe = {
        "schema": "signoff_replay_recipe_v1",
        "run": manifest.get("run", output_dir.name),
        "tier_a": "python replay/replay.py",
        "tier_b": {
            "note": "需要 EDA 环境；本包不自动执行（证据复核不应依赖重跑仿真）",
            "regression_dir": "regression_run",
            "coverage_cmd": "vcover report -cvg -details sim/coverage/plan_merged.ucdb",
        },
        "seeds": manifest.get("seeds") or [],
    }
    (replay_dir / "recipe.json").write_text(
        json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")

    for sub in ("replay/replay.py", "replay/recipe.json"):
        p = pkg / sub
        files.append({"section": "replay", "path": sub, "source": "",
                      "sha256": sha256_file(p), "size": p.stat().st_size})

    # `package_hash` 覆盖"文件集合 + 身份"，与绝对路径无关 —— 换机器仍可核。
    identity = {
        "files": sorted((f["path"], f["sha256"]) for f in files),
        "artifacts": manifest.get("artifacts") or {},
    }
    manifest = dict(manifest)
    manifest["schema"] = SCHEMA
    manifest["files"] = files
    manifest["package_hash"] = sha256_json(identity)
    # `package_dir` 必须在算 `manifest_hash` **之前**定下来 ——
    # 否则哈希漏掉一个字段，回读复核必然 mismatch（实测踩过）。
    manifest["package_dir"] = _rel(final_pkg, root)
    manifest["manifest_hash"] = sha256_json(
        {k: v for k, v in manifest.items() if k != "manifest_hash"})
    (pkg / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")

    # 整体替换：旧包先挪开，再换新包，最后删旧包。
    old_pkg = output_dir / "signoff_evidence.old"
    shutil.rmtree(old_pkg, ignore_errors=True)
    if final_pkg.exists():
        os.replace(final_pkg, old_pkg)
    os.replace(pkg, final_pkg)
    shutil.rmtree(old_pkg, ignore_errors=True)
    return manifest


_REPLAY_SCRIPT = r'''#!/usr/bin/env python3
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
'''


# ═══════════════════════════════════════════════════════════
# 校验 / 回放 / 双环境比较
# ═══════════════════════════════════════════════════════════

def _load_manifest(package_dir: Path) -> Dict[str, Any]:
    doc = json.loads((Path(package_dir) / "manifest.json")
                     .read_text(encoding="utf-8", errors="replace"))
    return doc if isinstance(doc, dict) else {}


def verify_package(package_dir: Path) -> Dict[str, Any]:
    """逐文件哈希 + package_hash 校验（Python 侧；与离线脚本同一判据）。"""
    pkg = Path(package_dir)
    if not (pkg / "manifest.json").is_file():
        return {"ok": False, "issues": [{"check": "missing_manifest"}]}
    manifest = _load_manifest(pkg)
    issues: List[Dict[str, Any]] = []
    for key in ("schema", "run", "verdict", "files",
                "package_hash", "manifest_hash"):
        if key not in manifest:
            issues.append({"check": "missing_manifest_field", "field": key})
    for entry in manifest.get("files") or []:
        path = pkg / entry["path"]
        if not path.is_file():
            issues.append({"check": "missing_file", "path": entry["path"]})
        elif sha256_file(path) != entry.get("sha256"):
            issues.append({"check": "hash_mismatch", "path": entry["path"]})
    identity = {
        "files": sorted((f["path"], f.get("sha256", ""))
                        for f in manifest.get("files") or []),
        "artifacts": manifest.get("artifacts") or {},
    }
    if sha256_json(identity) != manifest.get("package_hash"):
        issues.append({"check": "package_hash_mismatch"})
    stored_manifest_hash = manifest.get("manifest_hash")
    calc_manifest_hash = sha256_json(
        {k: v for k, v in manifest.items() if k != "manifest_hash"})
    if stored_manifest_hash and stored_manifest_hash != calc_manifest_hash:
        issues.append({"check": "manifest_hash_mismatch"})
    return {"ok": not issues, "issues": issues,
            "package_hash": manifest.get("package_hash", ""),
            "verdict": (manifest.get("verdict") or {}).get("verdict")}


def replay_tier_a(package_dir: Path) -> Dict[str, Any]:
    """离线重算判定（Tier A）—— 与生成的 `replay.py` 同一套规则。"""
    from .verdict import decide_verdict, effective_caveats

    pkg = Path(package_dir)
    manifest = _load_manifest(pkg)
    verdict = manifest.get("verdict") or {}
    raw = [c for c in (verdict.get("raw_caveats") or []) if isinstance(c, dict)]
    accepted = set(verdict.get("accepted_codes") or [])
    effective = effective_caveats(raw, accepted)
    hard_ok = bool(verdict.get("hard_ok"))
    recomputed = decide_verdict(hard_ok=hard_ok, raw_caveats=raw,
                                accepted_codes=accepted)
    integrity = verify_package(pkg)

    # 用记录下来的 tp_matrix 重算摘要，核对 manifest 里的数字没被改
    checks: List[Dict[str, Any]] = []
    tp_path = pkg / "execution" / "coverage/tp_matrix.json"
    if tp_path.is_file():
        tp = json.loads(tp_path.read_text(encoding="utf-8", errors="replace"))
        recorded_tp = manifest.get("tp_matrix") or {}
        recomputed_counts = tp.get("counts") or {}
        checks.append({
            "check": "tp_matrix_counts",
            "ok": recomputed_counts == (recorded_tp.get("counts") or {}),
            "recorded": recorded_tp.get("counts"),
            "recomputed": recomputed_counts,
        })
    cov_path = pkg / "execution" / "sim/coverage/coverage_result.json"
    if cov_path.is_file():
        cov = json.loads(cov_path.read_text(encoding="utf-8", errors="replace"))
        plan = cov.get("plan_coverage") or {}
        recorded = (manifest.get("coverage") or {}).get("plan_pct")
        checks.append({
            "check": "plan_coverage_pct",
            "ok": plan.get("functional_pct") == recorded,
            "recorded": recorded,
            "recomputed": plan.get("functional_pct"),
        })

    ok = (integrity["ok"] and recomputed == verdict.get("verdict")
          and all(c.get("ok") for c in checks))
    return {
        "ok": ok,
        "recorded_verdict": verdict.get("verdict"),
        "recomputed_verdict": recomputed,
        "effective_caveats": [c.get("code") for c in effective],
        "integrity": integrity,
        "checks": checks,
    }


def compare_packages(a: Path, b: Path) -> Dict[str, Any]:
    """双环境判定一致性 —— 同一份证据在两种环境各判一次，比较结论。

    比较的是**结论层**（verdict / 覆盖率 / TP 计数 / 关键版本），不是整份
    manifest：文件哈希天然会因环境差异而变，那不是"判定不一致"。
    """
    ma, mb = _load_manifest(a), _load_manifest(b)
    va = (ma.get("verdict") or {}).get("verdict")
    vb = (mb.get("verdict") or {}).get("verdict")
    ca = (ma.get("coverage") or {}).get("plan_pct")
    cb = (mb.get("coverage") or {}).get("plan_pct")
    ta = (ma.get("tp_matrix") or {}).get("counts") or {}
    tb = (mb.get("tp_matrix") or {}).get("counts") or {}
    diffs: List[Dict[str, Any]] = []
    if va != vb:
        diffs.append({"field": "verdict", "a": va, "b": vb})
    if ca != cb:
        diffs.append({"field": "coverage.plan_pct", "a": ca, "b": cb})
    if ta != tb:
        diffs.append({"field": "tp_matrix.counts", "a": ta, "b": tb})
    return {
        "schema": "signoff_dual_environment_v1",
        "consistent": not diffs,
        "diffs": diffs,
        "verdict_a": va, "verdict_b": vb,
        "environment_a": (ma.get("versions") or {}).get("platform"),
        "environment_b": (mb.get("versions") or {}).get("platform"),
    }
