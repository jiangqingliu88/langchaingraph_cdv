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
        return sorted(p for p in (self.root / "npu").rglob("*.sv") if p.is_file())

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
            # 这次集成**消费了哪些 IP 发布包**（版本/哈希/是否还对得上）。
            # 签核时靠它回答"用的 IP 到底是不是已发布的那一版"。
            "consumed_ips": soc_ip_binding(self.project.root),
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
        "ip_manifest": _read_yaml(project.root / "spec" / "ip_manifest.yaml"),
        "filelist": project.filelist,
        "rtl_files": [p.relative_to(project.root).as_posix()
                      for p in project.rtl_files],
        "rtl_hash": project.rtl_hash,
        "validation": project.validate(),
    }


def list_ips(root: str | Path) -> List[Dict[str, Any]]:
    """IP 清单 → 带文件存在性/hash 的列表（只读）。"""
    base = Path(root).resolve()
    doc = _read_yaml(base / "spec" / "ip_manifest.yaml")
    out: List[Dict[str, Any]] = []
    for ip in doc.get("ips") or []:
        if not isinstance(ip, dict):
            continue
        files = [str(x) for x in (ip.get("rtl") or [])]
        present = [f for f in files if (base / f).is_file()]
        missing = [f for f in files if not (base / f).is_file()]
        out.append({
            **ip,
            "rtl_files": files,
            "rtl_present": present,
            "rtl_missing": missing,
            "rtl_hash": hashlib.sha256("".join(
                _sha(base / f) for f in present).encode("ascii")).hexdigest()
            if present else "",
        })
    return out


def ip_info(root: str | Path, ip_id: str) -> Dict[str, Any]:
    for ip in list_ips(root):
        if str(ip.get("id") or "") == str(ip_id or ""):
            return ip
    return {}


def ip_plan(root: str | Path, ip_id: str = "") -> Dict[str, Any]:
    doc = _read_yaml(Path(root).resolve() / "spec" / "ip_verification_plan.yaml")
    plans = doc.get("ips") or {}
    if ip_id:
        return plans.get(str(ip_id)) or {}
    return plans


def latest_soc_run(root: str | Path = ".") -> str:
    """最近一次**真正的 SoC run** —— IP / C 用例 run 不算。

    IP run 也会写 `soc/soc_run.json`（见 `run_ip_regression`），
    如果这里只取"最新的 output_*"，一次 IP 回归就会变成"最新 SoC run"，
    其它 IP 的 TP 状态会被拿去做单 IP 的 run 里查 —— 两条业务线会互相污染。
    """
    for run in list_soc_runs(root):
        if run.get("kind") == "soc":
            return str(run["dir"])
    return ""


def latest_ip_run(root: str | Path, ip_id: str) -> str:
    """该 IP 最近一次 IP 级 run（`output_ip_*` / `ip/ip_run.json`）。"""
    for run in list_soc_runs(root):
        if run.get("kind") == "ip" and str(run.get("ip_id") or "") == str(ip_id or ""):
            return str(run["dir"])
    return ""


def _tp_status(run_root: Path, tp_ids: List[str]) -> List[Dict[str, Any]]:
    matrix = _read_json(run_root / "coverage" / "tp_matrix.json")
    rows = {str(r.get("tp_id") or ""): r for r in (matrix.get("rows") or [])
            if isinstance(r, dict)}
    out = []
    for tp_id in tp_ids:
        row = rows.get(str(tp_id))
        out.append({"tp_id": tp_id,
                    "status": str((row or {}).get("status") or "NOT_IN_MATRIX"),
                    "test": str((row or {}).get("test") or "")})
    return out


def _ip_status_source(root: str | Path, ip_id: str,
                      run_root: str | Path) -> tuple:
    """IP 状态该读哪次 run：显式 run > 该 IP 自己的 IP run > 最近 SoC run。

    只看 SoC run 会把"消费者跑没跑"当成"供应方验没验" —— 两条业务线的
    结论必须各算各的。
    """
    ip_run = latest_ip_run(root, ip_id)
    if run_root:
        same = bool(ip_run) and Path(run_root).resolve() == Path(ip_run).resolve()
        return str(run_root), "ip_run" if same else "soc_run"
    if ip_run:
        return ip_run, "ip_run"
    soc = latest_soc_run(root)
    return soc, ("soc_run" if soc else "none")


def ip_status(root: str | Path, ip_id: str,
              run_root: str | Path = "") -> Dict[str, Any]:
    """IP 的验证/发布状态 —— 从最近 SoC run 的 TP 矩阵推导。"""
    ip = ip_info(root, ip_id)
    plan = ip_plan(root, ip_id)
    source, source_kind = _ip_status_source(root, ip_id, run_root)
    if not ip:
        return {"ip_id": ip_id, "status": "NO_IP", "release_ready": False}
    if not source:
        return {"ip": ip, "plan": plan, "source_run": "",
                "source_kind": "none",
                "status": "NO_RUN", "release_ready": False,
                "testpoints": [], "evidence_ok": False}
    run = Path(source)
    doc = load_run_manifest(run)
    reg = (doc.get("regression") or {})
    tp_ids = [str(x) for x in (plan.get("testpoints") or [])]
    tps = _tp_status(run, tp_ids)
    observed = bool(tp_ids) and all(
        t["status"] in ("HIT", "OBSERVED", "BACKDOOR_HIT") for t in tps)
    has_tp = any(t["status"] != "NOT_IN_MATRIX" for t in tps)
    report = _read_json(run / "regression_run" / "report.json")
    task_status = {str(t.get("name")): str(t.get("status"))
                   for t in (report.get("tasks") or []) if isinstance(t, dict)}
    tests = [{"name": t, "status": task_status.get(t, "NOT_RUN")}
             for t in (plan.get("tests") or [])]
    tests_pass = bool(tests) and all(t["status"] == "pass" for t in tests)
    run_pass = str(reg.get("status") or "").upper() == "PASS"
    evidence = verify_soc_evidence(run)
    basis = "tp_matrix" if has_tp else "test_result"
    if not tp_ids:
        status = "NO_PLAN"
    elif not run_pass or not tests_pass:
        status = "FAILED"
    elif has_tp and observed and evidence.get("ok"):
        status = "VERIFIED"
    elif not has_tp and tests_pass and evidence.get("ok"):
        # v0.1 SoC 路径没有 TP 矩阵；测试通过 + 证据包完整只能说明
        # “该 IP 的集成 test 通过”，不能冒充逐 TP 命中。
        status = "TEST_PASS"
    else:
        status = "PARTIAL"
    return {
        "ip": ip, "plan": plan, "source_run": source,
        "source_kind": source_kind,
        "status": status, "verification_basis": basis,
        "release_ready": bool(status in ("VERIFIED", "TEST_PASS")
                              and ip.get("status") == "released"),
        "testpoints": tps, "tests": tests,
        "evidence_ok": bool(evidence.get("ok")),
        "evidence_package_hash": evidence.get("package_hash", ""),
        "regression": reg,
    }


def write_ip_evidence(root: str | Path, ip_id: str,
                      run_root: str | Path = "") -> Dict[str, Any]:
    """把 IP 的 TP 状态 + 来源 run + 证据包身份写成 `ip_evidence/<ip>.json`。"""
    status = ip_status(root, ip_id, run_root)
    source = Path(status.get("source_run") or "")
    if not source.is_dir():
        return {}
    out_dir = source / "ip_evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{ip_id}.json"
    body = {"schema": "ip_evidence_v1", "ip_id": ip_id,
            "source_run": source.name, **status}
    body["sha256"] = hashlib.sha256(_canon(body).encode("utf-8")).hexdigest()
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return {"path": str(path), "sha256": body["sha256"],
            "status": body.get("status"),
            "release_ready": body.get("release_ready", False)}


# ── IP 发布契约（ip_release_v1）──────────────────────────────────
#
# 两条业务线的协作靠**一份带哈希的发布包**，不靠清单里那个手填的
# `status: released`：
#
#   IP 团队  build  → `spec/ip_releases/<ip>.json`（进版本库，是契约）
#   SoC 团队 每次 run 记录消费了哪些包的哪个哈希 → 签核时校验绑定
#
# 覆盖率两边口径不同（IP 内部 vs 集成场景），包里带 `methodology` 与
# `coverage.basis`，两边数字**不相加、不互相顶替**。

DEFAULT_RELEASE_CRITERIA = (
    {"id": "tests_pass", "required": True},
    {"id": "evidence_ok", "required": True},
    {"id": "testpoints_observed", "required": True},
    # 独立 IP TB 落地前（M2）没有 IP 级覆盖测量，不阻断发布 —— 但状态是
    # `unknown` 不是 `pass`，包里如实记着。
    {"id": "coverage_min", "required": False,
     "note": "IP 独立 TB（M2）落地前按 SoC 子集计，不阻断发布"},
)


def _release_path(root: str | Path, ip_id: str) -> Path:
    return Path(root).resolve() / "spec" / "ip_releases" / f"{ip_id}.json"


def ip_release_package(root: str | Path, ip_id: str) -> Dict[str, Any]:
    """读 IP 发布包（没有就返回空 dict，调用方按"未发布"处理）。"""
    return _read_json(_release_path(root, ip_id))


def _ip_coverage_block(plan: Dict[str, Any]) -> Dict[str, Any]:
    cov = plan.get("coverage") or {}
    return {
        "strategy": str(cov.get("strategy") or "soc_subset"),
        # None ≠ 0：还没测就写 None，不拿 SoC 的数字冒充 IP 覆盖。
        "measured": False,
        "basis": "soc_subset",
        "target": cov.get("target"),
        "functional_pct": None,
        "coverpoints": cov.get("coverpoints") or [],
    }


def _eval_release_criterion(cid: str, status: Dict[str, Any]) -> tuple:
    if cid == "tests_pass":
        tests = status.get("tests") or []
        if not tests:
            return "unknown", "plan 没有登记 tests"
        bad = [str(t.get("name")) for t in tests if t.get("status") != "pass"]
        return ("pass", "") if not bad else ("fail", "未通过：" + "、".join(bad))
    if cid == "evidence_ok":
        return ("pass", "") if status.get("evidence_ok") else \
            ("fail", "证据包缺失或哈希不一致")
    if cid == "testpoints_observed":
        tps = status.get("testpoints") or []
        if not tps:
            return "unknown", "plan 没有 testpoints"
        hit = ("HIT", "OBSERVED", "BACKDOOR_HIT")
        bad = [str(t.get("tp_id")) for t in tps if t.get("status") not in hit]
        return ("pass", "") if not bad else ("fail", "未命中：" + "、".join(bad))
    if cid == "coverage_min":
        return "unknown", "IP 级覆盖尚未测量（basis=soc_subset）"
    return "unknown", f"未知准则 {cid}"


def _release_criteria(plan: Dict[str, Any],
                      status: Dict[str, Any]) -> List[Dict[str, Any]]:
    declared = plan.get("release_criteria") or list(DEFAULT_RELEASE_CRITERIA)
    out = []
    for item in declared:
        spec = item if isinstance(item, dict) else {"id": str(item)}
        cid = str(spec.get("id") or "")
        state, detail = _eval_release_criterion(cid, status)
        out.append({"id": cid, "required": bool(spec.get("required", True)),
                    "status": state, "detail": detail or str(spec.get("note") or "")})
    return out


def build_ip_release(root: str | Path, ip_id: str, run_root: str | Path = "",
                     released_by: str = "") -> Dict[str, Any]:
    """生成 IP 发布包（`spec/ip_releases/<ip>.json`）。

    **不伪造结论**：准则没过的包照样写盘，但 `released=false`，
    `blocking` 列出卡住的是哪几条 —— 发布与否由人看这张单子决定。
    """
    ip = ip_info(root, ip_id)
    if not ip:
        return {"ok": False, "error": f"IP 不在清单里：{ip_id}"}
    plan = ip_plan(root, ip_id)
    status = ip_status(root, ip_id, run_root)
    source = str(status.get("source_run") or "")
    if not source:
        return {"ok": False, "error": f"IP {ip_id} 还没有可用 run（先跑 ip.run）"}
    criteria = _release_criteria(plan, status)
    blocking = [c["id"] for c in criteria
                if c["required"] and c["status"] != "pass"]
    pkg = {
        "schema": "ip_release_v1",
        "ip_id": ip_id,
        "name": ip.get("name", ""),
        "team": ip.get("team", ""),
        "owner": ip.get("owner", ""),
        "version": ip.get("version", ""),
        "methodology": plan.get("methodology") or "ip_cdv",
        "rtl_hash": ip.get("rtl_hash", ""),
        "source_run": Path(source).name,
        "source_kind": status.get("source_kind", ""),
        "coverage": _ip_coverage_block(plan),
        "criteria": criteria,
        "waivers": plan.get("waivers") or [],
        "released": not blocking,
        "blocking": blocking,
        "released_by": released_by or ip.get("owner", ""),
        "evidence": {"package_hash": status.get("evidence_package_hash", "")},
    }
    pkg["sha256"] = hashlib.sha256(_canon(pkg).encode("utf-8")).hexdigest()
    path = _release_path(root, ip_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return {"ok": True, "released": pkg["released"], "path": str(path),
            "sha256": pkg["sha256"], "criteria": criteria,
            "blocking": blocking, "package": pkg}


def verify_ip_release(root: str | Path, ip_id: str) -> Dict[str, Any]:
    """校验发布包：自身哈希 / 是否放行 / 与清单 RTL hash 是否还绑得住。"""
    ip = ip_info(root, ip_id)
    pkg = ip_release_package(root, ip_id)
    if not pkg:
        return {"ok": False, "issues": [{"check": "missing_release"}],
                "package": {}}
    body = {k: v for k, v in pkg.items() if k != "sha256"}
    issues: List[Dict[str, Any]] = []
    if hashlib.sha256(_canon(body).encode("utf-8")).hexdigest() != pkg.get("sha256"):
        issues.append({"check": "package_hash_mismatch"})
    if not pkg.get("released"):
        issues.append({"check": "not_released", "blocking": pkg.get("blocking")})
    if ip and pkg.get("rtl_hash") != ip.get("rtl_hash"):
        issues.append({"check": "rtl_hash_mismatch",
                       "release": pkg.get("rtl_hash", "")[:16],
                       "manifest": str(ip.get("rtl_hash", ""))[:16]})
    return {"ok": not issues, "issues": issues, "package": pkg}


def _binding_state(ip: Dict[str, Any], pkg: Dict[str, Any]) -> str:
    if not pkg:
        return "MISSING" if str(ip.get("status")) == "released" else "UNRELEASED"
    if not pkg.get("released"):
        return "NOT_RELEASED"
    if pkg.get("rtl_hash") != ip.get("rtl_hash"):
        return "STALE"
    return "OK"


def soc_ip_binding(root: str | Path) -> List[Dict[str, Any]]:
    """SoC 视角：这次集成的每个 IP 绑的是哪个发布包、还对不对得上。"""
    rows = []
    for ip in list_ips(root):
        ip_id = str(ip.get("id") or "")
        pkg = ip_release_package(root, ip_id)
        rows.append({
            "ip_id": ip_id,
            "manifest_status": ip.get("status", ""),
            "manifest_version": ip.get("version", ""),
            "release_version": pkg.get("version", "") if pkg else "",
            "release_hash": pkg.get("sha256", "") if pkg else "",
            "state": _binding_state(ip, pkg),
        })
    return rows


def soc_ip_release_matrix(root: str | Path,
                          run_root: str | Path = "") -> List[Dict[str, Any]]:
    return [ip_status(root, str(ip.get("id") or ""), run_root)
            for ip in list_ips(root)]


def run_ip_regression(project_root: str | Path, ip_id: str,
                      output: str | Path = None) -> Dict[str, Any]:
    """按 IP verification plan 的 tests 跑一次回归，并落 IP 证据。"""
    import os

    from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
    from src.layers.l1_infrastructure.output_config import make_output_root

    root = Path(project_root).resolve()
    project = load_project(root)
    plan = ip_plan(root, ip_id)
    tests = [str(t) for t in (plan.get("tests") or [])]
    if not plan:
        return {"status": "FAIL", "error": f"IP 不在验证计划里: {ip_id}"}
    if not tests:
        return {"status": "FAIL", "error": f"IP {ip_id} 没有登记 tests"}
    os.environ["SOC_ROOT"] = str(root)
    out_root = make_output_root(str(output) if output else f"output_ip_{ip_id}")
    soc_run = SoCRun(project, out_root)
    result = InfrastructureManager(out_root).run_regression(
        reg_yaml=str(root / "regression" / "regression.yaml"), mode="local",
        tests=",".join(tests))
    summary = soc_run.finish(result)
    evidence = write_ip_evidence(root, ip_id, out_root)
    # summary 里带 ArtifactStore 活对象（给调用方用的）；落盘前去掉。
    safe_summary = {k: v for k, v in summary.items() if k != "artifacts"}
    ip_doc = {"schema": "ip_run_v1", "ip_id": ip_id,
              "tests": tests, "result": result,
              "soc_summary": safe_summary, "ip_evidence": evidence}
    path = Path(out_root) / "ip" / "ip_run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ip_doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return {"status": result.get("status"), "result": result,
            "output_root": str(out_root), "summary": summary,
            "ip_evidence": evidence, "ip_run": str(path)}


def list_soc_runs(base: str | Path = ".") -> List[Dict[str, Any]]:
    root = Path(base).resolve()
    runs = []
    for p in sorted(root.glob("output_*")):
        if not p.is_dir():
            continue
        # IP run 也有 `soc/soc_run.json`（子集回归），必须**先认 ip_run.json**，
        # 否则它会以 kind="soc" 冒充 SoC run，混进 SoC 的 run 选择器。
        ip_doc = _read_json(p / "ip" / "ip_run.json")
        if ip_doc:
            result = ip_doc.get("result") or {}
            runs.append({"run": p.name, "dir": str(p), "kind": "ip",
                         "ip_id": ip_doc.get("ip_id", ""),
                         "status": result.get("status"),
                         "mtime": p.stat().st_mtime})
            continue
        doc = load_run_manifest(p)
        if doc:
            runs.append({"run": p.name, "dir": str(p), "kind": "soc",
                         "status": (doc.get("regression") or {}).get("status"),
                         "mtime": p.stat().st_mtime})
            continue
        c_doc = _read_json(p / "c_run.json")
        if c_doc:
            case = c_doc.get("case") or {}
            runs.append({"run": p.name, "dir": str(p), "kind": "soc_c",
                         "case": case.get("id", ""),
                         "status": c_doc.get("status"),
                         "mtime": p.stat().st_mtime})
    return sorted(runs, key=lambda r: r["mtime"], reverse=True)


def run_summary(run_root: str | Path) -> Dict[str, Any]:
    root = Path(run_root).resolve()
    doc = load_run_manifest(root)
    wave = find_wave(root)
    if not doc:
        c_doc = _read_json(root / "c_run.json")
        if c_doc:
            case = c_doc.get("case") or {}
            status = str(c_doc.get("status") or "")
            passes = status.upper() == "PASS"
            # 归一化成与 SoC run 相同的最小形状：页面只认 manifest.regression。
            doc = {"schema": c_doc.get("schema", "soc_c_run_v1"),
                   "kind": "soc_c", "case": case,
                   "regression": {"status": status,
                                  "passed": 1 if passes else 0,
                                  "failed": 0 if passes else 1,
                                  "unknown": 0, "total": 1},
                   "waves": c_doc.get("waves") or []}
    return {"available": bool(doc), "kind": (doc or {}).get("kind", "soc"),
            "dir": str(root), "manifest": doc,
            "wave": str(wave) if wave else "",
            "evidence": verify_soc_evidence(root) if doc and doc.get("kind") != "soc_c" else {}}


def find_design(run_root: str | Path, wave: str | Path = None) -> Optional[Path]:
    """找 Visualizer 的 design.bin（qwave.db 只提供波形，源码浏览要 design 库）。"""
    root = Path(run_root)
    c_doc = _read_json(root / "c_run.json")
    design = c_doc.get("design") or {}
    if isinstance(design, dict) and design.get("path"):
        p = root / str(design["path"])
        if p.is_file():
            return p
    if wave:
        d = Path(wave).parent
        for cand in (d / "design.bin", d.parent / "design.bin",
                     d.parent.parent / "design.bin"):
            if cand.is_file():
                return cand
    found = sorted(root.glob("regression_run/**/design.bin"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


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
    for folder, pattern in (("vectors", "*"), ("npu", "*.sv"), ("tb", "*.sv")):
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


def find_wave(run_root: str | Path, test: str = "") -> Optional[Path]:
    """找 run 里的波形：SoC 回归 run、C 用例 run（`c_run.json`）都认。

    `test` 是路径子串过滤（例如 `gemm_8x8_c`），用于一次 run 里有多份波形时
    精确选一份。
    """
    root = Path(run_root)
    for doc in (load_run_manifest(root), _read_json(root / "c_run.json")):
        for item in doc.get("waves") or []:
            p = root / str(item.get("path") or "")
            if p.is_file() and (not test or test in p.as_posix()):
                return p
    found: List[Path] = []
    for pat in ("regression_run/**/waves/*.db", "regression_run/**/waves/*.wlf",
                "e203/waves/*.db", "e203/waves/*.wlf"):
        found.extend(p for p in root.glob(pat) if p.is_file())
    found = [p for p in found if not test or test in p.as_posix()]
    if found:
        return max(found, key=lambda p: p.stat().st_mtime)
    return None
