"""导入产物进 run：把 source_map 带进证据链，并做"导入后被手改"的漂移检查。

`case-model import-xlsx` 把 `casemodel.yaml + source_map.json` 写在工程里
（`specs/<module>/`）。verify 跑起来时把这两份复制进 run 的 `inputs/`：

  · 证据包收 `inputs/source_map.json` → 签核里能按覆盖仓反查源表第几行；
  · 若 `inputs/casemodel.yaml` 的 sha256 与导入时的 `casemodel_sha256`
    对不上 → 模型在导入之后被手改过，audit 挂 `INGEST_DRIFT`。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "aivm_evidence_v1"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def copy_ingest_artifacts(case_model_path: str | Path,
                          run_dir: str | Path) -> List[str]:
    """把 case 模型旁边那份 `source_map.json`（以及模型本身）复制进 run。

    没有 source_map = 这份模型不是从 xlsx 导入的 —— 什么都不做，不造空文件。
    """
    src_dir = Path(case_model_path).resolve().parent
    source_map = src_dir / "source_map.json"
    if not source_map.is_file():
        return []
    inputs = Path(run_dir) / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    target = inputs / "source_map.json"
    shutil.copy2(source_map, target)
    copied = [str(target)]
    model_target = inputs / "casemodel.yaml"
    if not model_target.is_file():
        shutil.copy2(Path(case_model_path), model_target)
        copied.append(str(model_target))
    return copied


def ingest_facts(run_dir: str | Path) -> Dict[str, Any]:
    """run 里的导入事实：覆盖点数 / 丢弃 / 轴未命中 / 导入后漂移。"""
    root = Path(run_dir)
    source_map = _read_json(root / "inputs" / "source_map.json")
    if not source_map:
        return {"available": False}
    bins = source_map.get("bins") or {}
    dropped = source_map.get("dropped") or []
    axes = source_map.get("axes") or {}
    applied = axes.get("applied") or {}
    issues: List[Dict[str, Any]] = []
    casemodel = root / "inputs" / "casemodel.yaml"
    expected = (source_map.get("outputs") or {}).get("casemodel_sha256", "")
    if casemodel.is_file() and expected:
        actual = _sha256(casemodel)
        if actual and actual != expected:
            issues.append({"check": "casemodel_changed_after_import",
                           "actual": actual[:12], "expected": expected[:12]})
    return {
        "available": True,
        "schema": source_map.get("schema", ""),
        "module": source_map.get("module", ""),
        "xlsx": (source_map.get("inputs") or {}).get("xlsx", ""),
        "bins": len(bins),
        "bins_by_kind": _count_kinds(bins),
        "dropped": len(dropped),
        "unmatched_axis_values": len(applied.get("unmatched") or []),
        "axes_sha256": (axes.get("sha256") or "")[:16],
        "issues": issues,
    }


def _count_kinds(bins: Dict[str, Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for record in bins.values():
        kind = str((record or {}).get("kind") or "")
        out[kind] = out.get(kind, 0) + 1
    return dict(sorted(out.items()))
