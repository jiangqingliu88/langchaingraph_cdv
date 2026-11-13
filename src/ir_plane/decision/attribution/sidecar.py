"""Per-test coverage sidecar v2 —— 每条 Test 结束后落一份独立事实记录。"""
from __future__ import annotations

from typing import Any, Dict, List

SCHEMA = "per_test_coverage_v2"
_IDENTITY_FIELDS = ("run_id", "test_id", "seed", "rtl_hash",
                    "coverage_model_hash", "stimulus_plan_hash")


def build_sidecar(*, run_id: str, test_id: str, seed: Any,
                  config_id: str = "", stimulus_plan_hash: str = "",
                  rtl_hash: str = "", coverage_model_hash: str = "",
                  coverage_artifact_hash: str = "",
                  observed_bins: List[Dict[str, Any]] = None
                  ) -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "run_id": str(run_id or ""),
        "test_id": str(test_id or ""),
        "seed": seed,
        "config_id": str(config_id or ""),
        "stimulus_plan_hash": str(stimulus_plan_hash or ""),
        "rtl_hash": str(rtl_hash or ""),
        "coverage_model_hash": str(coverage_model_hash or ""),
        "coverage_artifact_hash": str(coverage_artifact_hash or ""),
        "observed_bins": [
            {"bin_id": str(b.get("bin_id") or ""),
             "status": str(b.get("status") or "HIT").upper()}
            for b in (observed_bins or []) if isinstance(b, dict)
        ],
    }


def validate_sidecar(doc: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[Dict[str, str]] = []
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        errors.append({"rule": "unknown_schema", "target": str(doc.get("schema")),
                       "message": f"期望 {SCHEMA}"})
        return {"ok": False, "errors": errors, "identity_complete": False}
    missing = [k for k in _IDENTITY_FIELDS
               if doc.get(k) in (None, "")]
    for key in missing:
        errors.append({"rule": "missing_identity", "target": key,
                       "message": f"sidecar 缺少身份字段 {key}"})
    for index, item in enumerate(doc.get("observed_bins") or []):
        if not isinstance(item, dict) or not item.get("bin_id"):
            errors.append({"rule": "invalid_bin", "target": str(index),
                           "message": "observed_bins 条目缺 bin_id"})
    return {
        "ok": not errors,
        "errors": errors,
        "identity_complete": not missing,
        "metrics": {"bins": len(doc.get("observed_bins") or []),
                    "missing_identity": missing},
    }


__all__ = ["SCHEMA", "build_sidecar", "validate_sidecar"]
