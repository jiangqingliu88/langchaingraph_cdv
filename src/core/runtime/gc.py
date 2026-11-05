"""Run 存储回收 —— **默认 dry-run**，只清"可重生成 / 可重跑"的大件。

与 `prune`（整目录删除）不同：这里保留证据链，只回收以下两类：

  · 逐用例覆盖率库 / 波形（`regression_run/**/cov|waves/*.db`）
  · 仿真中间库（`sim/**/*.ucdb|*.vdb`，但**不碰** `sim/coverage/` 的合并度量）

**永不删除**：`coverage/`、`status/`、`docs/`、`contract/`、`evidence/`、
`signoff_evidence*/`、`inputs/`、`rtl/`、`report.json`、`caveats.json`。
这些是签核材料或身份来源，删了就不可重建。

调用方必须先看 dry-run 计划再 `apply`；`apply_gc` 没有默认值。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "run_gc_plan_v1"

#: 只在这些子树里找可回收文件（前缀匹配）。
CANDIDATE_GLOBS = (
    "regression_run/**/waves/*.db",
    "regression_run/**/waves/*.wlf",
    "regression_run/**/cov/**/*.db",
    "regression_run/**/cov/**/*.vdb",
    "sim/**/*.ucdb",
    "sim/**/*.vdb",
    "sim/**/*.wlf",
    "**/*.fsdb",
    "**/*.vcd",
)

#: 路径里出现这些片段就**永不删除**（签核材料 / 身份 / 度量）。
PROTECTED_PARTS = (
    "coverage", "status", "docs", "contract", "evidence",
    "signoff_evidence", "inputs", "rtl", "model", "golden",
    "signoff_evidence.json", "report.json", "caveats.json",
)

#: 这些文件即使在候选目录里也保留（反查表 / 清单）。
KEEP_NAMES = ("manifest.json", "report.json", "task_meta.json",
              "status.env", "sim_vsim.log")


def _is_protected(path: Path, run_root: Path) -> bool:
    try:
        rel = path.relative_to(run_root).as_posix().lower()
    except ValueError:
        rel = path.as_posix().lower()
    if path.name in KEEP_NAMES:
        return True
    return any(part in rel for part in
               (p.lower() for p in PROTECTED_PARTS))


def _run_dirs(root: Path) -> List[Path]:
    """一个目录算 run：有 report.json / coverage/ / regression_run/ 任一。"""
    out: List[Path] = []
    try:
        children = sorted(root.iterdir())
    except OSError:
        return out
    for path in children:
        if not path.is_dir():
            continue
        if ((path / "report.json").is_file()
                or (path / "coverage").is_dir()
                or (path / "regression_run").is_dir()):
            out.append(path)
    return out


def plan_gc(runs_root: str | Path, *, keep_last: int = 5,
            keep_days: float = 30.0,
            now: Optional[float] = None) -> Dict[str, Any]:
    """生成回收计划（不删任何东西）。"""
    root = Path(runs_root)
    now = time.time() if now is None else float(now)
    runs = _run_dirs(root)
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    keep: List[Path] = []
    prune: List[Path] = []
    for index, run in enumerate(runs):
        age_days = (now - run.stat().st_mtime) / 86400.0
        if index < max(0, keep_last) or age_days <= keep_days:
            keep.append(run)
        else:
            prune.append(run)

    candidates: List[Dict[str, Any]] = []
    total = 0
    for run in prune:
        for pattern in CANDIDATE_GLOBS:
            for path in run.glob(pattern):
                if not path.is_file() or _is_protected(path, run):
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                candidates.append({
                    "run": run.name,
                    "path": path.relative_to(root).as_posix(),
                    "bytes": size,
                })
                total += size
    return {
        "schema": SCHEMA,
        "root": str(root),
        "runs": len(runs),
        "keep_last": int(keep_last),
        "keep_days": float(keep_days),
        "kept_runs": [p.name for p in keep],
        "prune_runs": [p.name for p in prune],
        "candidates": candidates,
        "candidate_files": len(candidates),
        "candidate_bytes": total,
        "applied": False,
    }


def apply_gc(plan: Dict[str, Any], *, confirm: bool = False) -> Dict[str, Any]:
    """执行回收计划。`confirm=False` 时拒绝执行（没有默认删除）。"""
    if not confirm:
        return {**plan, "applied": False, "reason": "confirm_required"}
    root = Path(plan.get("root") or ".")
    deleted, errors, freed = [], [], 0
    for item in plan.get("candidates") or []:
        path = root / str(item.get("path") or "")
        try:
            size = path.stat().st_size
            path.unlink()
            deleted.append(item)
            freed += size
        except OSError as exc:
            errors.append({"path": str(item.get("path")), "error": str(exc)})
    return {**plan, "applied": True, "deleted": deleted,
            "deleted_files": len(deleted), "freed_bytes": freed,
            "errors": errors}


__all__ = ["SCHEMA", "apply_gc", "plan_gc"]
