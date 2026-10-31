"""SoC 参考工程适配层 —— 把工程输入接到现有 SignOffAI 事实面。

**不是执行引擎**：回归仍由 `InfrastructureManager.run_regression` 跑；本模块只做
三件事：

  1. 读工程输入（spec / interface / verification plan / RTL filelist）；
  2. 开 `RunContext` + `EventStore` + `ArtifactStore`，登记输入与产物；
  3. 落 `soc/soc_run.json`，回答「这次 SoC run 用了哪份 RTL、golden、回归结果、
     波形在哪」。

边界：它不生成 UVM、不做覆盖率闭环、不替代 `verify` 的 LangGraph 路径。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "soc_run_v1"
EVIDENCE_SCHEMA = "soc_evidence_v1"


def _sha(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:                               # noqa: BLE001
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


@dataclass(frozen=True)
class SoCProject:
    root: Path
    spec: Dict[str, Any] = field(default_factory=dict)
    interface_spec: Dict[str, Any] = field(default_factory=dict)
    verification_plan: Dict[str, Any] = field(default_factory=dict)
    filelist: List[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return str(self.spec.get("name") or self.root.name)

    @property
    def rtl_files(self) -> List[Path]:
        return sorted(p for p in (self.root / "rtl").rglob("*.sv") if p.is_file())

    @property
    def rtl_hash(self) -> str:
        h = hashlib.sha256()
        for p in self.rtl_files:
            h.update(p.relative_to(self.root).as_posix().encode("utf-8"))
            h.update(_sha(p).encode("ascii"))
        return h.hexdigest()

    def validate(self) -> Dict[str, Any]:
        required = ("spec/soc_spec.yaml", "spec/interface_spec.yaml",
                    "spec/verification_plan.yaml", "filelist.f",
                    "regression/regression.yaml", "tb/tb_soc_top.sv")
        missing = [rel for rel in required if not (self.root / rel).is_file()]
        missing_files = [rel for rel in self.filelist if not (self.root / rel).is_file()]
        return {"ok": not missing and not missing_files,
                "missing": missing, "filelist_missing": missing_files}


def load_project(root: str | Path) -> SoCProject:
    base = Path(root).resolve()
    filelist: List[str] = []
    fl = base / "filelist.f"
    if fl.is_file():
        for line in fl.read_text(encoding="utf-8", errors="replace").splitlines():
            rel = line.strip()
            if not rel or rel.startswith(("#", "//", "+incdir+")):
                continue
            filelist.append(rel)
    return SoCProject(
        root=base,
        spec=_read_yaml(base / "spec" / "soc_spec.yaml"),
        interface_spec=_read_yaml(base / "spec" / "interface_spec.yaml"),
        verification_plan=_read_yaml(base / "spec" / "verification_plan.yaml"),
        filelist=filelist,
    )


class SoCRun:
    """一次 SoC run 的事实写入器（RunContext/Event/Artifact 的薄包装）。"""

    def __init__(self, project: SoCProject, output_root: str | Path):
        from src.core.runtime.run_context import open_run_context
        from src.core.runtime.events import EventStore
        from src.core.runtime.artifacts import ArtifactStore

        self.project = project
        self.root = Path(output_root).resolve()
        self.ctx = open_run_context(
            self.root, module_id=project.name, rtl_hash=project.rtl_hash,
            spec_hash=_sha(project.root / "spec" / "soc_spec.yaml"),
            simulator="questa")
        self.ctx.paths.ensure()
        (self.root / "soc").mkdir(parents=True, exist_ok=True)
        (self.root / "docs" / "run_context.json").write_text(
            json.dumps(self.ctx.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        self.events = EventStore(self.root, self.ctx.run_id)
        self.artifacts = ArtifactStore(self.root, self.ctx.run_id,
                                       event_store=self.events)
        self._register_inputs()
        self.events.append("soc.project.loaded", source="soc_adapter",
                           payload={"project": str(project.root),
                                    "files": len(project.filelist),
                                    "rtl_hash": project.rtl_hash})

    def _register_inputs(self) -> None:
        for rel in ("spec/soc_spec.yaml", "spec/interface_spec.yaml",
                    "spec/verification_plan.yaml", "filelist.f",
                    "regression/regression.yaml", "golden/gemm_golden.py"):
            self.artifacts.register("soc_input", self.project.root / rel,
                                    producer="soc_adapter")
        for p in self.project.rtl_files:
            self.artifacts.register("rtl", p, producer="soc_project")
        for name in ("a.hex", "b.hex", "c.hex", "meta.json"):
            self.artifacts.register("golden_vector",
                                    self.project.root / "vectors" / name,
                                    producer="gemm_golden")

    def finish(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """登记回归产物、写 `soc/soc_run.json`。返回摘要。"""
        reg = self.root / "regression_run"
        for rel in ("report.json", "report_summary.txt", "report.html"):
            p = reg / rel
            if p.is_file():
                self.artifacts.register("soc_regression", p,
                                        producer="regression")
        waves: List[Dict[str, Any]] = []
        for db in sorted(reg.rglob("waves/*.db")):
            ref = self.artifacts.register("waveform", db, producer="vsim")
            waves.append({"path": ref.path, "sha256": ref.sha256,
                          "size": ref.size})
        for log in sorted(reg.rglob("sim_vsim.log")):
            self.artifacts.register("sim_log", log, producer="vsim")

        status = str(result.get("status") or "")
        summary = {
            "schema": SCHEMA,
            "project": {"root": str(self.project.root),
                        "name": self.project.name,
                        "rtl_hash": self.project.rtl_hash,
                        "rtl_files": len(self.project.rtl_files),
                        "filelist": self.project.filelist},
            "run": self.ctx.to_dict(),
            "regression": {
                "status": status,
                "passed": result.get("passed", 0),
                "failed": result.get("failed", 0),
                "unknown": result.get("unknown", 0),
                "total": result.get("total", 0),
                "report": "regression_run/report.json",
            },
            "waves": waves,
            "artifacts": "artifacts/artifacts.json",
            "events": "docs/events.jsonl",
        }
        path = self.root / "soc" / "soc_run.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        self.artifacts.register("soc_run_manifest", path, producer="soc_adapter")
        self.events.append(
            "soc.regression.finished", source="soc_adapter", status=status,
            payload={"passed": summary["regression"]["passed"],
                     "failed": summary["regression"]["failed"],
                     "total": summary["regression"]["total"],
                     "waves": len(waves)})
        evidence = write_soc_evidence(self.root)
        return {"path": str(path), "status": status, "waves": waves,
                "evidence": evidence, "artifacts": self.artifacts}


def project_info(root: str | Path) -> Dict[str, Any]:
    """GUI/自动化用：工程输入的只读摘要（不跑 EDA）。"""
    project = load_project(root)
    return {
        "root": str(project.root),
        "name": project.name,
        "spec": project.spec,
        "interface_spec": project.interface_spec,
        "verification_plan": project.verification_plan,
        "regression": _read_yaml(project.root / "regression" / "regression.yaml"),
        "filelist": project.filelist,
        "rtl_files": [p.relative_to(project.root).as_posix()
                      for p in project.rtl_files],
        "rtl_hash": project.rtl_hash,
        "validation": project.validate(),
    }


def list_soc_runs(base: str | Path = ".") -> List[Dict[str, Any]]:
    root = Path(base).resolve()
    runs = []
    for p in sorted(root.glob("output_soc_*")):
        if not p.is_dir():
            continue
        doc = load_run_manifest(p)
        if doc:
            runs.append({"run": p.name, "dir": str(p),
                         "status": (doc.get("regression") or {}).get("status"),
                         "mtime": p.stat().st_mtime})
    return sorted(runs, key=lambda r: r["mtime"], reverse=True)


def run_summary(run_root: str | Path) -> Dict[str, Any]:
    root = Path(run_root).resolve()
    doc = load_run_manifest(root)
    wave = find_wave(root)
    return {"available": bool(doc), "dir": str(root),
            "manifest": doc, "wave": str(wave) if wave else "",
            "evidence": verify_soc_evidence(root)}


def run_soc_project(project_root: str | Path,
                    output: str | Path = None) -> Dict[str, Any]:
    """执行一次 SoC 回归（CLI 与 Workbench 共用；不是第二套引擎）。"""
    import os

    from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
    from src.layers.l1_infrastructure.output_config import make_output_root

    root = Path(project_root).resolve()
    project = load_project(root)
    validation = project.validate()
    if not validation["ok"]:
        return {"status": "FAIL", "error": "SoC 工程输入不完整",
                "validation": validation}
    os.environ["SOC_ROOT"] = str(root)
    out_root = make_output_root(str(output) if output else
                                f"output_soc_{root.name}")
    soc_run = SoCRun(project, out_root)
    result = InfrastructureManager(out_root).run_regression(
        reg_yaml=str(root / "regression" / "regression.yaml"), mode="local")
    summary = soc_run.finish(result)
    return {"status": result.get("status"), "result": result,
            "summary": summary, "output_root": str(out_root),
            "validation": validation}


def load_run_manifest(run_root: str | Path) -> Dict[str, Any]:
    return _read_json(Path(run_root) / "soc" / "soc_run.json")


def _canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def _copy_evidence(tmp: Path, section: str, rel: str, base: Path,
                   entries: List[Dict[str, Any]]) -> None:
    src = base / rel
    if not src.is_file():
        return
    dst = tmp / section / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    entries.append({"section": section, "path": f"{section}/{rel}",
                    "sha256": _sha(dst), "size": dst.stat().st_size})


def _collect_evidence_files(tmp: Path, root: Path, proj_root: Path,
                            run_doc: Dict[str, Any],
                            entries: List[Dict[str, Any]]) -> None:
    for rel in ("spec/soc_spec.yaml", "spec/interface_spec.yaml",
                "spec/verification_plan.yaml", "regression/regression.yaml",
                "filelist.f"):
        _copy_evidence(tmp, "inputs", rel, proj_root, entries)
    for folder, pattern in (("vectors", "*"), ("rtl", "*.sv"), ("tb", "*.sv")):
        for p in sorted((proj_root / folder).rglob(pattern)):
            _copy_evidence(tmp, "inputs", p.relative_to(proj_root).as_posix(),
                           proj_root, entries)
    for rel in ("soc/soc_run.json", "artifacts/artifacts.json",
                "docs/events.jsonl", "docs/run_context.json",
                "regression_run/report.json",
                "regression_run/report_summary.txt"):
        _copy_evidence(tmp, "execution", rel, root, entries)
    for p in sorted((root / "regression_run").rglob("sim_vsim.log")):
        _copy_evidence(tmp, "execution", p.relative_to(root).as_posix(),
                       root, entries)
    for wave in run_doc.get("waves") or []:
        _copy_evidence(tmp, "wave", str(wave.get("path") or ""), root, entries)


def write_soc_evidence(run_root: str | Path) -> Dict[str, Any]:
    """把 SoC run 收成可交换的 `signoff_evidence/`（独立 schema）。

    不是 UVM 的 `signoff_evidence_v2`：没有三态 verdict/TP 矩阵；这里回答
    「这次 SoC 回归用了哪份 RTL/golden、跑了什么、波形在哪、结果是什么」。
    """
    root = Path(run_root).resolve()
    run_doc = load_run_manifest(root)
    if not run_doc:
        return {}
    pkg = root / "signoff_evidence"
    tmp = root / "signoff_evidence.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)

    entries: List[Dict[str, Any]] = []
    proj_root = Path(str((run_doc.get("project") or {}).get("root") or root))
    _collect_evidence_files(tmp, root, proj_root, run_doc, entries)

    manifest = {
        "schema": EVIDENCE_SCHEMA,
        "run": run_doc.get("run") or {},
        "project": run_doc.get("project") or {},
        "regression": run_doc.get("regression") or {},
        "waves": run_doc.get("waves") or [],
        "files": entries,
    }
    manifest["package_hash"] = hashlib.sha256(_canon({
        "files": sorted((f["path"], f["sha256"]) for f in entries),
    }).encode("utf-8")).hexdigest()
    manifest["manifest_hash"] = hashlib.sha256(
        _canon({k: v for k, v in manifest.items() if k != "manifest_hash"})
        .encode("utf-8")).hexdigest()
    (tmp / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    old = root / "signoff_evidence.old"
    shutil.rmtree(old, ignore_errors=True)
    if pkg.exists():
        pkg.replace(old)
    tmp.replace(pkg)
    shutil.rmtree(old, ignore_errors=True)
    return {"path": str(pkg / "manifest.json"),
            "package_hash": manifest["package_hash"],
            "files": len(entries)}


def verify_soc_evidence(run_root: str | Path) -> Dict[str, Any]:
    """逐文件哈希 + package_hash 校验（不跑 EDA）。"""
    root = Path(run_root).resolve()
    pkg = root / "signoff_evidence"
    try:
        manifest = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "issues": [{"check": "missing_manifest"}],
                "files": 0}
    issues: List[Dict[str, Any]] = []
    for f in manifest.get("files") or []:
        p = pkg / str(f.get("path") or "")
        if not p.is_file():
            issues.append({"check": "missing_file", "path": f.get("path")})
        elif _sha(p) != f.get("sha256"):
            issues.append({"check": "hash_mismatch", "path": f.get("path")})
    identity = {"files": sorted((f.get("path"), f.get("sha256"))
                                for f in manifest.get("files") or [])}
    if hashlib.sha256(_canon(identity).encode("utf-8")).hexdigest() \
            != manifest.get("package_hash"):
        issues.append({"check": "package_hash_mismatch"})
    return {"ok": not issues, "issues": issues,
            "files": len(manifest.get("files") or []),
            "package_hash": manifest.get("package_hash", ""),
            "regression": manifest.get("regression") or {}}


def find_wave(run_root: str | Path) -> Optional[Path]:
    doc = load_run_manifest(run_root)
    for item in doc.get("waves") or []:
        p = Path(run_root) / str(item.get("path") or "")
        if p.is_file():
            return p
    root = Path(run_root)
    for pat in ("regression_run/**/waves/*.db",
                "regression_run/**/waves/*.wlf"):
        found = sorted(root.glob(pat), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        if found:
            return found[0]
    return None
