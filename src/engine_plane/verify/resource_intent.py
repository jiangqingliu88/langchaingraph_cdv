"""Resource / Interaction intent 的确定性验证入口（M1/M3）。

自然语言/计划最终必须落成 ResourceModel 才能被 Engine 检查：
intent → resources/operations/interactions → overlap 事实 → 场景 → 结论。

**不调用 LLM**；判定只看地址区间与策略。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_INCOMPLETE = "INCOMPLETE"


def _canonical_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_document(doc: Dict[str, Any], *, address_width: int = 64,
                    module: str = "") -> Dict[str, Any]:
    """ResourceModel dict → 三态结论 + 可落盘证据。"""
    from src.ir_plane.decision.resource_model import (
        compile_scenarios, coverage_summary, from_dict,
    )

    model = from_dict(doc if isinstance(doc, dict) else {})
    model.module = model.module or module
    validation = model.validate()
    facts = model.interaction_facts(address_width=address_width)
    scenarios = compile_scenarios(model, address_width=address_width)
    conflicts = [f for f in facts if f.get("conflict")]
    overflows = [f for f in facts if f.get("overflow")]

    if validation:
        status, reason = STATUS_INCOMPLETE, "资源/操作引用不完整"
    elif not model.operations or not model.interactions:
        status, reason = STATUS_INCOMPLETE, "intent 缺少 operations/interactions"
    elif conflicts:
        status, reason = STATUS_FAIL, f"{len(conflicts)} 条禁止重叠冲突"
    elif overflows:
        status, reason = STATUS_FAIL, f"{len(overflows)} 条地址溢出"
    else:
        status, reason = STATUS_PASS, "所有交互满足声明策略"

    return {
        "schema": "resource_intent_result_v1",
        "module": model.module,
        "status": status,
        "reason": reason,
        "intent_hash": _canonical_hash(doc),
        "counts": {
            "resources": len(model.resources),
            "operations": len(model.operations),
            "interactions": len(model.interactions),
            "facts": len(facts),
            "scenarios": len(scenarios),
        },
        "validation": validation,
        "conflicts": conflicts,
        "overflows": overflows,
        "facts": facts,
        "scenarios": scenarios,
        "coverage": coverage_summary(scenarios),
        "model": model.to_dict(),
    }


def verify_file(path: str | Path, *, address_width: int = 64) -> Dict[str, Any]:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() in (".yaml", ".yml"):
        import yaml
        doc = yaml.safe_load(text) or {}
    else:
        doc = json.loads(text)
    return verify_document(doc if isinstance(doc, dict) else {},
                           address_width=address_width, module=p.stem)


def write_result(result: Dict[str, Any], out_dir: str | Path) -> Path:
    from src.runtime_plane.core.runtime.atomic import atomic_write_json

    target = Path(out_dir) / "resource_intent_result.json"
    atomic_write_json(target, result)
    return target


__all__ = [
    "STATUS_FAIL", "STATUS_INCOMPLETE", "STATUS_PASS",
    "verify_document", "verify_file", "write_result",
]
