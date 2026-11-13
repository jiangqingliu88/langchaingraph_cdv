"""EDA 证据层 —— 跑验证、读结构化报告、对比前后、把缺口拆成子目标。

证据不是模型自述：这里只读 EDA/框架落盘的产物（regression_stages.json、
coverage_result.json、coverage_holes.json、closure_plan.json、contract_manifest.json），
并给每个文件算 sha256。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]

_EVIDENCE_FILES = (
    "regression_stages.json",
    "sim/coverage/coverage_result.json",
    "coverage/coverage_holes.json",
    "status/closure_plan.json",
    "contract/contract_manifest.json",
)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_map(root: Path) -> Dict[str, Any]:
    files, hashes = {}, {}
    for rel in _EVIDENCE_FILES:
        path = root / rel
        if path.is_file():
            files[rel] = str(path)
            hashes[rel] = _sha256(path)
    return {"files": files, "hashes": hashes}


def _regression(root: Path) -> Dict[str, Any]:
    stages = _read_json(root / "regression_stages.json")
    rows = [{"name": s.get("name"), "status": s.get("status"),
             "passed": int(s.get("passed") or 0),
             "failed": int(s.get("failed") or 0),
             "total": int(s.get("total") or 0)}
            for s in (stages.get("stages") or [])]
    return {"status": str(stages.get("status") or "MISSING"),
            "blocked_at": str(stages.get("blocked_at") or ""),
            "stages": rows, "failed": sum(row["failed"] for row in rows)}


def _coverage(root: Path) -> Dict[str, Any]:
    coverage = _read_json(root / "sim/coverage/coverage_result.json")
    plan = coverage.get("plan_coverage") or {}
    code = coverage.get("code_coverage_plan") or {}
    return {"functional_pct": float(plan.get("functional_pct") or 0.0),
            "merged": int(plan.get("merged") or 0),
            "stores": int(plan.get("stores") or 0),
            "code": {"branch_pct": float(code.get("branch_pct") or 0.0),
                     "toggle_pct": float(code.get("toggle_pct") or 0.0),
                     "statement_pct": float(code.get("statement_pct") or 0.0)},
            "tp": (coverage.get("tp_matrix") or {}).get("counts") or {}}


def _holes(root: Path) -> Dict[str, Any]:
    holes = _read_json(root / "coverage/coverage_holes.json")
    return {"counts": holes.get("counts") or {},
            "holes": (holes.get("holes") or [])[:20]}


def _closure(root: Path) -> Dict[str, Any]:
    closure = _read_json(root / "status/closure_plan.json")
    return {"continue": bool(closure.get("continue")),
            "closure_rate": float(closure.get("closure_rate") or 0.0),
            "total": int(closure.get("total") or 0),
            "done": int(closure.get("done") or 0),
            "actions": (closure.get("actions") or [])[:20]}


def _contracts(root: Path) -> Dict[str, Any]:
    manifest = _read_json(root / "contract/contract_manifest.json")
    return {"contract_id": str(manifest.get("contract_id") or ""),
            "obligations": int(manifest.get("obligations") or 0),
            "cases": int(manifest.get("cases") or 0)}


def collect_evidence(run_dir: str | Path, *, target: float = 0.0) -> Dict[str, Any]:
    """把一个 run 的结构化结果压成可裁决的证据包（只读）。"""
    root = Path(run_dir).expanduser().resolve()
    evidence: Dict[str, Any] = {
        "run_dir": str(root), "exists": root.is_dir(),
        "target": float(target or 0.0), "hashes": {}, "files": {},
    }
    if not root.is_dir():
        return evidence
    evidence.update(_file_map(root))
    evidence["regression"] = _regression(root)
    evidence["coverage"] = _coverage(root)
    evidence["holes"] = _holes(root)
    evidence["closure"] = _closure(root)
    evidence["contracts"] = _contracts(root)
    evidence["functional_met"] = (
        evidence["coverage"]["functional_pct"] >= evidence["target"]
        if evidence["target"] > 0 else False)
    return evidence


def _as_evidence(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return collect_evidence(str(value))


def _delta(first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, float]:
    c1, c2 = first.get("coverage") or {}, second.get("coverage") or {}
    code1, code2 = c1.get("code") or {}, c2.get("code") or {}
    holes1 = (first.get("holes") or {}).get("counts", {}).get("holes") or 0
    holes2 = (second.get("holes") or {}).get("counts", {}).get("holes") or 0
    return {
        "functional_pct": round(float(c2.get("functional_pct") or 0)
                                - float(c1.get("functional_pct") or 0), 2),
        "branch_pct": round(float(code2.get("branch_pct") or 0)
                            - float(code1.get("branch_pct") or 0), 2),
        "toggle_pct": round(float(code2.get("toggle_pct") or 0)
                            - float(code1.get("toggle_pct") or 0), 2),
        "regression_failed": int((second.get("regression") or {}).get("failed") or 0)
                             - int((first.get("regression") or {}).get("failed") or 0),
        "holes": int(holes2) - int(holes1),
    }


def compare_evidence(before: Any, after: Any) -> Dict[str, Any]:
    """before/after 可以是证据包或 run 目录。"""
    first, second = _as_evidence(before), _as_evidence(after)
    delta = _delta(first, second)
    return {
        "schema": "eda_evidence_compare_v1",
        "before": first.get("run_dir", ""),
        "after": second.get("run_dir", ""),
        "delta": delta,
        "improved": (delta["functional_pct"] > 0
                     or delta["regression_failed"] < 0
                     or delta["holes"] < 0),
        "target": second.get("target", first.get("target", 0)),
        "functional_pct": (second.get("coverage") or {}).get("functional_pct", 0),
        "met": bool(second.get("functional_met")),
    }


def decompose_coverage(evidence: Dict[str, Any], target: float,
                       *, max_subgoals: int = 6) -> List[Dict[str, Any]]:
    """把覆盖率缺口拆成子目标：优先 closure actions，退化为 holes 分组。"""
    actual = float((evidence.get("coverage") or {}).get("functional_pct") or 0)
    if target <= 0 or actual >= target:
        return []
    titles: List[str] = []
    for action in (evidence.get("closure") or {}).get("actions") or []:
        target_name = str(action.get("target") or action.get("action") or "")
        if target_name and target_name not in titles:
            titles.append(f"{action.get('action', 'ACTION')}: {target_name}")
        if len(titles) >= max_subgoals - 1:
            break
    if not titles:
        seen = set()
        for hole in (evidence.get("holes") or {}).get("holes") or []:
            key = f"{hole.get('dimension')}/{hole.get('coverpoint')}"
            if key not in seen:
                seen.add(key)
                titles.append(f"补齐覆盖点 {key}")
            if len(titles) >= max_subgoals - 1:
                break
    if not titles:
        titles.append(f"补齐覆盖率 {actual:.2f}% → {target:.2f}%")
    titles.append(f"重跑验证并收集证据（目标 functional ≥ {target:.2f}%）")
    return [{"id": f"G{index}", "title": title,
             "success": "该缺口在重跑证据中闭合（命令/日志/覆盖数据）"}
            for index, title in enumerate(titles[:max_subgoals], 1)]


def _export_sources(root: Path) -> tuple[Path, str, List[Path], bool]:
    """优先导出 v2 签核证据包；没有时退回结构化证据文件（complete=False）。"""
    package = root / "signoff_evidence"
    if package.is_dir() and (package / "manifest.json").is_file():
        files = sorted(p for p in package.rglob("*")
                       if p.is_file() and not p.name.startswith("."))
        return package, "signoff_evidence", files, True
    wanted = set(_EVIDENCE_FILES) | {"report.json", "signoff_evidence.json",
                                     "workspace_verify.log", "caveats.json"}
    files = sorted(path for rel in wanted
                   for path in [root / rel] if path.is_file())
    return root, "run", files, False


def _zip_entry(rel: str, data: bytes) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def export_evidence(run_dir: str | Path,
                    out_zip: str | Path | None = None) -> Dict[str, Any]:
    """把 run 的证据导出成可交换 zip（固定时间戳，内容可复算）。

    只读 run 目录；zip 默认落在 `<run>/export/`。没有 `signoff_evidence/`
    时导出结构化证据文件，并在返回里标 `complete=False`（不伪装成签核包）。
    """
    root = Path(run_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"run 目录不存在：{root}")
    source, kind, files, complete = _export_sources(root)
    if not files:
        return {"ok": False, "run_dir": str(root), "complete": False,
                "reason": "没有可导出的证据文件（先跑 run_verify/collect_evidence）"}
    out = (Path(out_zip).expanduser().resolve() if out_zip else
           root / "export" / f"{kind}_package.zip")
    out.parent.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            data = path.read_bytes()
            rel = path.relative_to(source).as_posix()
            rows.append({"path": rel, "bytes": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()})
            archive.writestr(_zip_entry(rel, data), data)
        manifest = {
            "schema": "signoff_evidence_export_v1",
            "run_dir": root.name, "source": kind, "complete": complete,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": rows,
            "package_hash": hashlib.sha256(json.dumps(
                rows, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False,
                                    indent=2).encode("utf-8")
        archive.writestr(_zip_entry("export_manifest.json", manifest_bytes),
                         manifest_bytes)
    return {"ok": True, "run_dir": str(root), "source": kind,
            "complete": complete, "files": len(rows),
            "bytes": out.stat().st_size, "sha256": _sha256(out),
            "zip_path": str(out), "package_hash": manifest["package_hash"]}


def run_verify(project: str | Path, run_dir: str | Path, *,
               target: float = 0.0, timeout: int = 1800,
               allow_unreviewed: bool = True) -> Dict[str, Any]:
    """用现有 vplan execute 跑一轮验证，返回证据包；失败也返回证据（如果有）。"""
    project = Path(project).expanduser().resolve()
    run = Path(run_dir).expanduser().resolve()
    run.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-B", "-m", "src.workbench.cli.commands", "vplan", "execute",
               str(project), "-o", str(run), "--max-rounds", "1", "--sim-mode", "cov"]
    if allow_unreviewed:
        command.append("--allow-unreviewed")
    started = time.time()
    try:
        completed = subprocess.run(
            command, cwd=str(REPO_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
        code = completed.returncode
        output = (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired as exc:
        code = 124
        output = f"TIMEOUT after {timeout}s\n{exc.stdout or ''}"
    log = run / "workspace_verify.log"
    try:
        log.write_text(output, encoding="utf-8")
    except OSError:
        log = run
    evidence = collect_evidence(run, target=target)
    return {
        "ok": code == 0,
        "exit_code": code,
        "run_dir": str(run),
        "log": str(log),
        "elapsed_s": round(time.time() - started, 1),
        "command": command,
        "allow_unreviewed": allow_unreviewed,
        "evidence": evidence,
    }
