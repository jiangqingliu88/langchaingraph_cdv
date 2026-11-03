"""证据流水线 —— 把 run 目录里的**派生物**按固定顺序算出来。

以前这段编排长在 `collect_real_coverage.run()` 里（那个文件 1600+ 行，`run()`
一口气串了 8 个写入器）：想改一处要读完一整条链，想重跑一步得把仿真也重跑。

现在分成两段：

    collect_real_coverage.run()   编译 → 仿真 → 解析 → 合并     （度量：事实）
            │
            ▼  本模块
    case_cov → tp_matrix → tp_evidence → evd → cell_matrix → case_view → gates
                                                            （派生：结论）

每一步都可以单独重跑（`only=...`）：模型改了、证据重算，但仿真不必重跑。
每步产物的 sha256 与耗时记进 `coverage/evidence_manifest.json`——于是
"这份视图是哪个模型版本出的"能回答，而不是靠 mtime 猜。

**幂等**：同一份输入重复跑，产物内容逐字节一致（除 `generated_at`）。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

SCHEMA = "evidence_manifest_v1"

STEPS: tuple = ("case_cov", "tp_matrix", "tp_evidence", "evd",
                "cell_matrix", "case_view", "gates", "os_shadow",
                "os_tp_shadow")

#: 每步**应当**产出的文件（相对 run 目录）。缺了记进 manifest，不静默。
STEP_ARTIFACTS: Dict[str, tuple] = {
    "case_cov": ("coverage/case_tp.json",),
    "tp_matrix": ("coverage/tp_matrix.json",),
    "tp_evidence": ("coverage/tp_cov_evidence.json",),
    "evd": ("coverage/evd.json",),
    "cell_matrix": ("coverage/cell_matrix.json",),
    "case_view": ("coverage/case_view.json",),
    "gates": ("coverage/gates.json",),
    # Verification OS v3 · M0：契约/义务/事实账本/影子对账（不改变旧判定）
    "os_shadow": ("status/shadow_report.json", "evidence/ledger.jsonl"),
    # M2 第一步：TP 级状态也推导一遍，与 tp_matrix 对账（仍不改判定）
    "os_tp_shadow": ("status/tp_shadow.json",),
}


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


# ── 每一步 ────────────────────────────────────────────────────

def _step_case_cov(od: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from .case_cov import case_cov_matrix
    index = case_cov_matrix(od, max_cases=ctx.get("max_cases") or 0)
    ctx["case_index"] = index
    return index


def _step_tp_matrix(od: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    # 私有函数在 collect_real_coverage 里（它才是度量侧的唯一实现），
    # 这里只**调用**不复制 —— 延迟 import 避免循环依赖。
    from src.tools.common.lib.collect_real_coverage import (
        _tp_matrix, _write_tp_matrix,
    )
    coverage = ctx.get("coverage") or _read_json(
        od / "sim" / "coverage" / "coverage_result.json").get("coverage") or {}
    matrix = _tp_matrix(od, coverage, case_index=ctx.get("case_index"))
    if matrix:
        _write_tp_matrix(od, matrix)
    return matrix


def _step_tp_evidence(od: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from .tp_evidence import write_tp_evidence
    return write_tp_evidence(od)


def _step_evd(od: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from .evd import write_evd
    return write_evd(od)


def _step_cell_matrix(od: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from .cell_matrix import write_cell_matrix
    return write_cell_matrix(od)


def _step_case_view(od: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from src.tools.humanview.case_associate_view import write_case_view
    return write_case_view(od)


def _step_gates(od: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from src.tools.humanview.case_associate_view.gates import write_gates
    return write_gates(od)


def _step_os_shadow(od: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """M0 影子：契约→义务→账本→推导，与旧结论逐条对账（不改任何判定）。"""
    from src.tools.checking.verification_os import run_shadow
    return run_shadow(od)


def _step_os_tp_shadow(od: Path, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """M2a：TP 级状态由事实推导，与 `tp_matrix` 对账（仍不改判定）。

    顺带把 run 级 `bin_hit`（合并覆盖率）与 `tp_attr` 写进账本 —— 批次级 test
    没有 case 身份，但它们的命中必须进事实账本，否则 TP 度量缺一块。
    """
    from src.tools.checking.verification_os import append_bundle
    from src.tools.checking.verification_os.tp_shadow import (
        attr_bundle, run_facts, run_tp_shadow)

    for bundle in (run_facts(od), attr_bundle(od)):
        if bundle is not None:
            append_bundle(od, bundle)
    return run_tp_shadow(od)


_STEP_FUNCS: Dict[str, Callable[[Path, Dict[str, Any]], Any]] = {
    "case_cov": _step_case_cov,
    "tp_matrix": _step_tp_matrix,
    "tp_evidence": _step_tp_evidence,
    "evd": _step_evd,
    "cell_matrix": _step_cell_matrix,
    "case_view": _step_case_view,
    "gates": _step_gates,
    "os_shadow": _step_os_shadow,
    "os_tp_shadow": _step_os_tp_shadow,
}


# ── 编排 ──────────────────────────────────────────────────────

def _write_manifest(od: Path, run: List[Dict[str, Any]],
                    skipped: List[str]) -> Dict[str, Any]:
    manifest = {
        "schema": SCHEMA,
        "run": od.name,
        "steps": run,
        "skipped": skipped,
        "artifacts": {
            name: {"sha256": _sha(od / rel), "path": rel}
            for name, rels in STEP_ARTIFACTS.items()
            for rel in rels
        },
        "notes": ([] if run else ["没有任何步骤被执行"]),
    }
    path = od / "coverage" / "evidence_manifest.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError:
        pass
    return manifest


def run_evidence_pipeline(od: str | Path, *, coverage: Dict[str, Any] = None,
                          max_cases: int = 0,
                          only: Optional[List[str]] = None,
                          case_index: Dict[str, Any] = None) -> Dict[str, Any]:
    """按 `STEPS` 顺序跑派生物；`only` 指定时只跑那几步（按依赖顺序）。

    返回 `{step: result, manifest, case_index}`。某一步抛异常**不中断**后续
    能跑的步骤（例如 `gates` 只依赖 `case_view`），错误记进 `steps[].error`。
    """
    root = Path(od)
    wanted = [s for s in STEPS if not only or s in only]
    ctx: Dict[str, Any] = {"coverage": coverage or {}, "max_cases": max_cases,
                           "case_index": case_index or {}}
    out: Dict[str, Any] = {}
    records: List[Dict[str, Any]] = []
    for step in wanted:
        started = time.perf_counter()
        record: Dict[str, Any] = {"step": step, "ok": True, "error": ""}
        try:
            out[step] = _STEP_FUNCS[step](root, ctx)
        except Exception as exc:                 # noqa: BLE001 单步失败不拖垮整条
            record.update(ok=False, error=f"{type(exc).__name__}: {exc}")
            out[step] = None
        record["ms"] = round((time.perf_counter() - started) * 1000, 1)
        record["artifacts"] = {
            rel: _sha(root / rel) for rel in STEP_ARTIFACTS.get(step, ())
        }
        records.append(record)

    skipped = [s for s in STEPS if s not in wanted]
    manifest = _write_manifest(root, records, skipped)
    return {"steps": out, "manifest": manifest,
            "case_index": ctx.get("case_index") or {}}


# ── 给度量侧的适配层 ────────────────────────────────────────────

def attach_to_result(od: str | Path, result: Dict[str, Any],
                     max_cases: int = 0) -> Dict[str, Any]:
    """跑流水线并把摘要并进 `coverage_result`（`collect_real_coverage.run` 调）。

    度量侧只关心"结果字典里有哪些段"，编排细节不该再长在那个 1600 行的文件里。
    """
    ev = run_evidence_pipeline(Path(od), coverage=result.get("coverage") or {},
                               max_cases=max_cases)
    from .case_cov import case_coverage_patch

    result.update(case_coverage_patch(ev.get("case_index") or {}))
    steps = ev.get("steps") or {}
    if steps.get("tp_matrix"):
        result["tp_matrix"] = steps["tp_matrix"]
    attach_sections(result, steps)
    if ev.get("manifest"):
        result["evidence_pipeline"] = {
            "path": "coverage/evidence_manifest.json",
            "steps": [{k: r.get(k) for k in ("step", "ok", "ms", "error")}
                      for r in (ev["manifest"].get("steps") or [])],
        }
    return ev


def attach_sections(result: Dict[str, Any], steps: Dict[str, Any]) -> None:
    """各步产物的摘要（缺失的步不写键 —— 不造空壳）。"""
    tep = steps.get("tp_evidence") or {}
    if tep:
        result["tp_cov_evidence"] = {
            "path": "coverage/tp_cov_evidence.json",
            "counts": tep.get("counts") or {},
            "evidence_layers": tep.get("evidence_layers") or {},
            "path_backend": ((tep.get("review") or {}).get("path_backend") or ""),
        }
    cv = steps.get("case_view") or {}
    if cv:
        result["case_view"] = {
            "path": "coverage/case_view.json",
            "counts": cv.get("counts") or {},
            "reports": cv.get("_reports") or {},
        }
    for key, rel in (("cell_matrix", "cell_matrix.json"), ("evd", "evd.json")):
        doc = steps.get(key) or {}
        if doc:
            result[key] = {"counts": doc.get("counts") or {},
                           "path": f"coverage/{rel}"}
    _attach_verdict_sections(result, steps)


def _attach_verdict_sections(result: Dict[str, Any], steps: Dict[str, Any]) -> None:
    """门禁 / 影子对账两段摘要（判定相关的派生结果，单独一处）。"""
    gates = steps.get("gates") or {}
    if gates:
        result["case_gates"] = {"verdict": gates.get("verdict", ""),
                                "counts": gates.get("counts") or {},
                                "path": "coverage/gates.json"}
    shadow = steps.get("os_shadow") or {}
    if shadow.get("available"):
        result["os_shadow"] = {
            "ok": bool(shadow.get("ok")),
            "obligations": shadow.get("obligations", 0),
            "mismatched": (shadow.get("compare") or {}).get("mismatched", 0),
            "path": "status/shadow_report.json",
        }


__all__ = ["SCHEMA", "STEPS", "STEP_ARTIFACTS", "attach_sections",
           "attach_to_result", "run_evidence_pipeline"]
