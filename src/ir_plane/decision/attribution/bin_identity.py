"""Bin 身份 —— 同名 Bin 在不同 Coverage Model / RTL 版本之间不能合并。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def _hash(doc: Any) -> str:
    text = json.dumps(doc, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bin_identity(coverage_model_hash: str, scope: str, coverpoint: str,
                 bin_name: str) -> str:
    """`bin_id = H(coverage_model_hash, scope, coverpoint, bin)`。"""
    digest = _hash({
        "coverage_model_hash": str(coverage_model_hash or ""),
        "scope": str(scope or ""),
        "coverpoint": str(coverpoint or ""),
        "bin": str(bin_name or ""),
    })
    return f"BIN-{digest[:20]}"


def hit_fact(*, bin_id: str, run_id: str, test_id: str, seed: Any,
             tp_ids: Any = None, case_ids: Any = None,
             stimulus_plan_hash: str = "", rtl_hash: str = "",
             coverage_model_hash: str = "",
             config_id: str = "", backend: str = "",
             attribution_level: str = "EXACT") -> Dict[str, Any]:
    return {
        "bin_id": bin_id,
        "run_id": str(run_id or ""),
        "test_id": str(test_id or ""),
        "seed": seed,
        "tp_ids": [str(t) for t in (tp_ids or []) if str(t)],
        "case_ids": [str(c) for c in (case_ids or []) if str(c)],
        "stimulus_plan_hash": str(stimulus_plan_hash or ""),
        "rtl_hash": str(rtl_hash or ""),
        # **身份链的一部分**：缺它 identity_completeness 永远是 0。
        "coverage_model_hash": str(coverage_model_hash or ""),
        "config_id": str(config_id or ""),
        "backend": str(backend or ""),
        "attribution_level": str(attribution_level or "UNKNOWN").upper(),
    }


__all__ = ["bin_identity", "hit_fact"]
