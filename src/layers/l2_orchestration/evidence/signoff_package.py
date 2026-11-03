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
from src.core.contracts import versions

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

SCHEMA = versions.EVIDENCE_UVM_PROFILE
POLICY_SCHEMA = "signoff_policy_v1"

#: 策略文件允许的键。未知键 = 拼写错误/过期字段，**不静默忽略**。
POLICY_KEYS = frozenset({
    "schema", "module", "require_ref_model", "require_baseline",
    "accepted_caveats", "caveat_policy", "reward_weights", "_effective_source",
})


class PolicyError(ValueError):
    """签核策略不合 schema —— strict 模式下直接失败。"""

#: 证据包各段要收的**源文件候选**（相对 run 目录）。
#: 不存在就跳过 —— 不写空占位：缺了什么是事实，应该能被看见。
SECTION_FILES: Dict[str, Tuple[str, ...]] = {
    "inputs": (
        "spec.json",
        "inputs/casemodel.yaml",
        "inputs/source_map.json",
        "inputs/yaml/uvm/constraint.yaml",
        "inputs/yaml/uvm/models.yaml",
        "coverage/coverage_plan.yaml",
        "coverage/testpoints.json",
        "coverage/stimulus_plan.json",
        "coverage/association_report.json",
        "coverage/constraint_status.json",
        "signoff_policy.yaml",
        "effective_policy.yaml",
    ),
    "execution": (
        "regression_run/report.json",
        "sim/coverage/coverage_result.json",
        "coverage/tp_matrix.json",
        "coverage/plan_merge_manifest.json",
        "coverage/seed_diversity.json",
        "coverage/sim_reward.json",
        "coverage/knowledge_graph.json",
        "coverage/plan_consistency.json",
        "coverage/round_manifest.json",
        "docs/tool_receipts.jsonl",
        "docs/llm_audit.jsonl",
        # Architecture 2.0：事实日志 / 产物血缘 / 决策成效
        "docs/events.jsonl",
        "docs/provenance.jsonl",
        "docs/provenance_summary.json",
        "coverage/attribution.json",
        "docs/engineering_metrics.json",
        "incremental/plan.json",
        "docs/run_diff.json",
        "decision/evaluations.jsonl",
    ),
    "verdict": (
        # `report.json` 在证据包之后才写（它要带 package_hash），所以不进包；
        # 包里的权威结论是 `manifest.json` 的 `verdict` 段 + `signoff_evidence.json`。
        "signoff_evidence.json",
        "docs/file_change_chain.json",
        "caveats.json",
        # 五维质量门：报告用，不阻断（见 src/core/verification/quality.py）
        "docs/verification_quality.json",
    ),
    # ── Case View（三集合证据）──
    #
    # 签核要能离线回答"这条用例证明了哪些组 / 哪条 SVA / 哪个 scoreboard"，
    # 所以它和 TP 矩阵、覆盖率一样是**签核产出**，不是页面上的一张临时表。
    # `coverage/case_cov/**` 用通配符展开（一条用例一个文件，数量随回归增长）。
    "case_view": (
        "coverage/case_ir.json",
        "coverage/case_group_map.json",
        "coverage/case_checker_map.json",
        "coverage/case_tp.json",
        "coverage/cell_matrix.json",
        "coverage/evd.json",
        "coverage/gates.json",
        "coverage/case_view.json",
        "coverage/case_view.md",
        "coverage/case_view.html",
        "coverage/evidence_manifest.json",
        "coverage/case_cov/**/*.json",
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

def _normalize_accepted(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """两种写法（accepted_caveats / caveat_policy）归一成 code → detail。"""
    accepted: Dict[str, Dict[str, Any]] = {}
    for code, val in (raw.get("accepted_caveats") or {}).items():
        if isinstance(val, dict):
            accepted[str(code)] = {
                "accepted": bool(val.get("accepted")),
                "approver": str(val.get("approver") or ""),
                "reason": str(val.get("reason") or ""),
            }
        else:
            accepted[str(code)] = {"accepted": bool(val),
                                   "approver": "", "reason": ""}
    for item in (raw.get("caveat_policy") or []):
        if isinstance(item, dict) and item.get("code"):
            accepted[str(item["code"])] = {
                "accepted": bool(item.get("accepted")),
                "approver": str(item.get("approver") or ""),
                "reason": str(item.get("reason") or ""),
            }
    return accepted


def _policy_issues(raw: Dict[str, Any],
                   accepted: Dict[str, Dict[str, Any]]) -> List[str]:
    """schema / 未知键 / 类型 / caveat / reward_weights 的静态校验。"""
    issues: List[str] = []
    if not raw:
        return issues
    if raw.get("schema") not in (None, POLICY_SCHEMA):
        issues.append(f"schema 必须是 {POLICY_SCHEMA}，实际 {raw.get('schema')!r}")
    unknown = sorted(set(raw) - POLICY_KEYS)
    if unknown:
        issues.append(f"未知策略键（拼写错误/过期字段）: {unknown}")
    if not isinstance(raw.get("require_ref_model", False), bool):
        issues.append("require_ref_model 必须是布尔值")
    if not isinstance(raw.get("require_baseline", True), bool):
        issues.append("require_baseline 必须是布尔值")
    if not isinstance(raw.get("accepted_caveats", {}), dict):
        issues.append("accepted_caveats 必须是 code → {accepted, approver, reason} 的映射")
    for code, val in accepted.items():
        if val.get("accepted") and (not val.get("approver") or not val.get("reason")):
            issues.append(f"accepted_caveats.{code}: 接受 caveat 必须写 approver 与 reason")
    rw = raw.get("reward_weights")
    if rw is not None:
        if not isinstance(rw, dict):
            issues.append("reward_weights 必须是 compile/regression/coverage 的映射")
        else:
            for key, value in rw.items():
                if key not in ("compile", "regression", "coverage"):
                    issues.append(f"reward_weights 未知键: {key}")
                elif not isinstance(value, (int, float)) or value < 0:
                    issues.append(f"reward_weights.{key} 必须是非负数")
            if all(isinstance(v, (int, float)) for v in rw.values()) \
                    and sum(rw.values()) <= 0:
                issues.append("reward_weights 总和必须大于 0")
    return issues


def _read_policy_doc(path: Path) -> Dict[str, Any] | None:
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:                               # noqa: BLE001 坏策略文件不阻断
        return None
    return doc if isinstance(doc, dict) else None


def load_policy(output_dir: Path, module: str,
                project_root: Optional[Path] = None,
                strict: bool = False) -> Tuple[Dict[str, Any], str]:
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
    # 全局默认 + 模块覆盖：模块文件只写与默认不同的键。
    default_path = root / "config" / "signoff_policy" / "_default.yaml"
    default_raw = dict(_read_policy_doc(default_path) or {})
    module_raw: Dict[str, Any] = {}
    raw: Dict[str, Any] = dict(default_raw)
    source = str(default_path) if raw else ""
    for p in candidates:
        doc = _read_policy_doc(p) if p.is_file() else None
        if doc is not None:
            module_raw = doc
            raw.update(doc)
            source = str(p)
            break

    accepted = _normalize_accepted(raw)
    issues = _policy_issues(raw, accepted)

    if strict and issues:
        raise PolicyError("签核策略不合 schema: " + "；".join(issues))

    # 生效视图：每个键最终值 + 来源（default / module / implicit）。
    effective = {}
    for key, value in raw.items():
        origin = ("module" if key in module_raw
                  else "default" if key in default_raw else "implicit")
        effective[key] = {"value": value, "source": origin}

    policy = {
        "schema": POLICY_SCHEMA,
        "module": module,
        "source": source,
        "policy_hash": sha256_json({"raw": raw, "effective": effective}),
        "effective": effective,
        "require_ref_model": bool(raw.get("require_ref_model", False)),
        "require_baseline": bool(raw.get("require_baseline", True)),
        "accepted_caveats": accepted,
        "issues": issues,
        "raw": raw,
    }
    return policy, source


def write_policy_snapshot(output_dir: Path, policy: Dict[str, Any]) -> str:
    """把实际生效的策略复制进 run 目录（证据包 inputs 会收它）。

    同时写两份：
      · `signoff_policy.yaml` —— 合并后的原始值（兼容旧读者）；
      · `effective_policy.yaml` —— 每个键的最终值 + 来源（default/module/implicit），
        证据包 replay 用它回答“当时到底生效了什么”。
    """
    path = output_dir / "signoff_policy.yaml"
    effective_path = output_dir / "effective_policy.yaml"
    try:
        import yaml

        path.write_text(yaml.safe_dump(policy.get("raw") or {
            "require_ref_model": policy.get("require_ref_model"),
            "require_baseline": policy.get("require_baseline"),
            "accepted_caveats": policy.get("accepted_caveats") or {},
            "_effective_source": policy.get("source") or "default",
        }, allow_unicode=True, sort_keys=False), encoding="utf-8")
        effective_path.write_text(yaml.safe_dump({
            "schema": POLICY_SCHEMA,
            "module": policy.get("module", ""),
            "source": policy.get("source", ""),
            "policy_hash": policy.get("policy_hash", ""),
            "effective": policy.get("effective") or {},
        }, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return str(effective_path)
    except Exception:                               # noqa: BLE001
        return ""


# ═══════════════════════════════════════════════════════════
# 写包
# ═══════════════════════════════════════════════════════════

def _attach_envelope(manifest: Dict[str, Any],
                     files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """给 v2 manifest 补 EvidenceEnvelope 基础段（profile 业务字段原样保留）。"""
    from src.core.contracts.evidence import build_envelope

    manifest["profile"] = SCHEMA
    manifest["envelope"] = build_envelope(
        run_id=str(manifest.get("run") or ""),
        module=str(manifest.get("module") or ""),
        profile=SCHEMA,
        inputs={"framework": manifest.get("framework") or {},
                "policy": manifest.get("policy") or {},
                "versions": manifest.get("versions") or {}},
        execution={"coverage": manifest.get("coverage") or {},
                   "tp_matrix": manifest.get("tp_matrix") or {},
                   "sim_reward": manifest.get("sim_reward") or {},
                   "knowledge_graph": manifest.get("knowledge_graph") or {}},
        verdict=manifest.get("verdict") or {},
        replay={"recipe": "replay/recipe.json", "tier_a": "verdict_recompute"},
        hashes={"package_hash": manifest["package_hash"], "files": len(files)},
        versions_seen={"evidence": SCHEMA})
    return manifest


def _json_file(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _expand(output_dir: Path, rel: str) -> List[Path]:
    """`SECTION_FILES` 的条目 → 真实文件（支持 `**` 通配，如 case_cov/**）。"""
    if not any(ch in rel for ch in "*?["):
        path = output_dir / rel
        return [path] if path.is_file() else []
    try:
        return sorted(p for p in output_dir.glob(rel) if p.is_file())
    except (OSError, ValueError):
        return []


def _previous_index(pkg: Path) -> Dict[str, Dict[str, str]]:
    """上一版包的 `source → {path, sha256}` —— 增量打包的唯一依据。"""
    out: Dict[str, Dict[str, str]] = {}
    for item in _json_file(pkg / "manifest.json").get("files") or []:
        if isinstance(item, dict) and item.get("source"):
            out[str(item["source"])] = {"path": str(item.get("path") or ""),
                                        "sha256": str(item.get("sha256") or "")}
    return out


def _link_or_copy(prev: Path, src: Path, dst: Path) -> None:
    """复用上一版包里的同名同哈希文件：同盘硬链接（O(1)），跨盘退回复制。"""
    try:
        os.link(prev, dst)
    except OSError:
        shutil.copy2(src, dst)


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
    # **增量**：上一版包里已有、且源文件哈希没变的条目直接复用（硬链接），
    # 只复制新增/变化的文件。重跑 audit（例如 case 证据重生成了）时，
    # 两三百份 `case_cov` 不必再全量拷贝一遍。
    previous = _previous_index(final_pkg)
    copied = reused = 0
    for section, candidates in SECTION_FILES.items():
        target_dir = pkg / section
        target_dir.mkdir(parents=True, exist_ok=True)
        for pattern in candidates:
            for src in _expand(output_dir, pattern):
                rel = src.relative_to(output_dir).as_posix()
                # 包内路径：
                #   inputs/ 本来就是 run 的相对路径（`inputs/...` 或 `coverage/...`）；
                #   其余段统一挂到各自段下。
                # 不用 `section/rel` 一刀切 —— 那会拼出 `inputs/inputs/casemodel.yaml`。
                if section == "inputs":
                    dst_rel = (Path(rel).as_posix() if rel.startswith("inputs/")
                               else f"inputs/{Path(rel).as_posix()}")
                else:
                    dst_rel = f"{section}/{Path(rel).as_posix()}"
                dst = pkg / dst_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                digest = sha256_file(src)
                prev = previous.get(rel) or {}
                prev_file = final_pkg / prev["path"] if prev.get("path") else None
                if (prev_file is not None and prev_file.is_file()
                        and prev.get("sha256") == digest):
                    _link_or_copy(prev_file, src, dst)
                    reused += 1
                else:
                    try:
                        shutil.copy2(src, dst)
                    except OSError:
                        continue
                    copied += 1
                files.append({
                    "section": section,
                    "path": dst_rel,
                    "source": rel,
                    "sha256": sha256_file(dst),
                    "size": dst.stat().st_size,
                    "reused": bool(prev and prev.get("sha256") == digest),
                })

    # 生成离线回放脚本（materials 都在包里，脚本不 import 本项目）
    replay_dir = pkg / "replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    (replay_dir / "replay.py").write_text(_REPLAY_SCRIPT, encoding="utf-8")
    recipe = {
        "schema": "signoff_replay_recipe_v2",
        "run": manifest.get("run", output_dir.name),
        "tier_a": {
            "description": "不跑 EDA：校验文件哈希并重算三态判定",
            "command": "python replay/replay.py",
            "requires_eda": False,
            "inputs": [
                "manifest.json",
                "execution/coverage/tp_matrix.json",
                "execution/sim/coverage/coverage_result.json",
            ],
            "checks": [
                "file_sha256", "package_hash", "manifest_hash",
                "verdict_recompute", "tp_matrix_counts", "plan_coverage_pct",
            ],
        },
        "tier_b": {
            "description": "需要 EDA：按回归 YAML 重跑并重新合并覆盖率",
            "requires_eda": True,
            "eda_tools": ["vsim", "vcover"],
            "note": "本包不自动执行 —— 证据复核不应默认依赖重跑仿真",
            "steps": [
                {
                    "name": "regression",
                    "cwd": "regression_run",
                    "command_source": "inputs/yaml/regression.yaml 的 tests[*].run_cmd",
                    "expected_artifacts": ["report.json", "report_summary.txt"],
                },
                {
                    "name": "coverage_merge",
                    "command": "vcover report -cvg -details sim/coverage/plan_merged.ucdb",
                    "expected_artifacts": ["coverage/tp_matrix.json"],
                },
            ],
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
    # 增量打包的自述：这次复制了几份、复用了几份（复用 = 哈希未变）。
    # 写进 manifest 是为了让"包为什么这么快"可回答，而不是靠猜。
    manifest["incremental"] = {"copied": copied, "reused": reused,
                               "files": len(files)}
    manifest["package_hash"] = sha256_json(identity)
    # EvidenceEnvelope 基础段：UVM profile 保留三态/caveat/TP 矩阵，
    # 只补「身份 / 输入 / 执行 / 判定 / 回放 / 哈希」六段共同骨架。
    manifest = _attach_envelope(manifest, files)
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

def load_recipe(package_dir: Path) -> Dict[str, Any]:
    """读 `replay/recipe.json`；缺失/坏文件返回 `{}`。"""
    path = Path(package_dir) / "replay" / "recipe.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def validate_recipe(recipe: Dict[str, Any]) -> List[str]:
    """校验回放 recipe 的最小 schema，供未来自动化 runner 直接消费。

    返回问题列表；空列表 = 可用。**不执行任何命令**。
    """
    issues: List[str] = []
    if not isinstance(recipe, dict):
        return ["recipe 必须是对象"]
    if recipe.get("schema") != "signoff_replay_recipe_v2":
        issues.append(f"recipe.schema 必须是 signoff_replay_recipe_v2，"
                      f"实际 {recipe.get('schema')!r}")
    tier_a = recipe.get("tier_a")
    if not isinstance(tier_a, dict):
        issues.append("recipe.tier_a 必须是对象")
    else:
        if tier_a.get("requires_eda") is not False:
            issues.append("tier_a.requires_eda 必须是 false")
        if not isinstance(tier_a.get("command"), str) or not tier_a["command"]:
            issues.append("tier_a.command 必须是非空字符串")
        for key in ("inputs", "checks"):
            if not isinstance(tier_a.get(key), list):
                issues.append(f"tier_a.{key} 必须是列表")
    tier_b = recipe.get("tier_b")
    if not isinstance(tier_b, dict):
        issues.append("recipe.tier_b 必须是对象")
    else:
        if tier_b.get("requires_eda") is not True:
            issues.append("tier_b.requires_eda 必须是 true")
        if not isinstance(tier_b.get("eda_tools"), list):
            issues.append("tier_b.eda_tools 必须是列表")
        steps = tier_b.get("steps")
        if not isinstance(steps, list) or not steps:
            issues.append("tier_b.steps 必须是非空列表")
        else:
            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    issues.append(f"tier_b.steps[{i}] 必须是对象")
                    continue
                if not step.get("name"):
                    issues.append(f"tier_b.steps[{i}].name 不能为空")
                if not (step.get("command") or step.get("command_source")):
                    issues.append(
                        f"tier_b.steps[{i}] 需要 command 或 command_source")
                if not isinstance(step.get("expected_artifacts"), list):
                    issues.append(
                        f"tier_b.steps[{i}].expected_artifacts 必须是列表")
    return issues


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


def _policy_effective_check(pkg: Path, manifest: Dict[str, Any]):
    path = pkg / "inputs" / "effective_policy.yaml"
    if not path.is_file():
        return None
    try:
        import yaml

        doc = yaml.safe_load(
            path.read_text(encoding="utf-8", errors="replace")) or {}
        recorded = (manifest.get("policy") or {}).get("policy_hash")
        return {
            "check": "policy_effective",
            "ok": bool(recorded) and doc.get("policy_hash") == recorded,
            "recorded": recorded,
            "recomputed": doc.get("policy_hash"),
            "keys": sorted((doc.get("effective") or {}).keys()),
        }
    except Exception as exc:                        # noqa: BLE001
        return {"check": "policy_effective", "ok": False,
                "error": str(exc)[:200]}


def _fact_problem(fact: Dict[str, Any], tps: set,
                  entries: Dict[str, Any], plan_sha: str) -> List[Dict[str, Any]]:
    tp_id = str(fact.get("tp_id") or "")
    if tp_id not in tps:
        return [{"type": "tp_missing", "tp_id": tp_id}]
    problems = []
    if fact.get("plan_sha256") and fact["plan_sha256"] != plan_sha:
        problems.append({"type": "plan_drift", "tp_id": tp_id})
    entry = entries.get(tp_id)
    if fact.get("entry_sha256") and entry is not None:
        digest = hashlib.sha256(json.dumps(
            entry, ensure_ascii=False, sort_keys=True,
            default=str).encode("utf-8")).hexdigest()
        if fact["entry_sha256"] != digest:
            problems.append({"type": "entry_drift", "tp_id": tp_id})
    return problems


def _round_manifest_check(pkg: Path):
    rm_path = pkg / "execution" / "coverage" / "round_manifest.json"
    if not rm_path.is_file():
        return None
    plan_path = pkg / "inputs" / "coverage" / "stimulus_plan.json"
    tp_path = pkg / "inputs" / "coverage" / "testpoints.json"
    plan = (json.loads(plan_path.read_text(encoding="utf-8"))
            if plan_path.is_file() else {})
    tps = {str(t.get("tp_id") or "") for t in
           ((json.loads(tp_path.read_text(encoding="utf-8")).get("testpoints")
             if tp_path.is_file() else []) or []) if isinstance(t, dict)}
    entries = {str(e.get("tp_id") or ""): e for e in
               (plan.get("testpoints") or []) if isinstance(e, dict)}
    rm = json.loads(rm_path.read_text(encoding="utf-8", errors="replace"))
    facts = [f for rnd in rm.get("rounds") or []
             for f in (rnd.get("facts") or [])]
    problems = [p for f in facts
                for p in _fact_problem(f, tps, entries, plan.get("sha256"))]
    return {"check": "round_manifest", "ok": not problems,
            "facts": len(facts), "problems": problems[:10]}


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

    # 生效策略快照：replay 不重新 load 当前 policy，只认当时记下的那份。
    policy_check = _policy_effective_check(pkg, manifest)
    if policy_check:
        checks.append(policy_check)

    # 轮次事实表：per-test 的 plan/entry 哈希必须与包里的 plan 一致
    round_check = _round_manifest_check(pkg)
    if round_check:
        checks.append(round_check)

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


def check_package(package_dir: Path) -> Dict[str, Any]:
    """一次把证据包讲清楚：完整性 + Tier A 重算 + recipe 可用性。

    纯读（不跑 EDA、不写盘），供工作台“校验证据包”按钮与自动化调用。
    """
    pkg = Path(package_dir)
    if not (pkg / "manifest.json").is_file():
        return {"available": False, "package_dir": str(pkg),
                "note": "没有 manifest.json —— 这次运行还没生成证据包"}
    recipe = load_recipe(pkg)
    return {
        "available": True,
        "package_dir": str(pkg),
        "verify": verify_package(pkg),
        "replay": replay_tier_a(pkg),
        "recipe": recipe,
        "recipe_issues": validate_recipe(recipe),
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
