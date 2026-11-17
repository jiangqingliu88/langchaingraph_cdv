"""Resource / Interaction intent 的确定性验证入口（M1-A）。

自然语言/计划最终必须落成 ResourceModel 才能被 Engine 检查：
intent → 声明校验 → 地址事实 → 场景 → 三态静态结论。

**不调用 LLM**。非法或缺失输入只能得到 INCOMPLETE，确定的越界或禁止
重叠得到 FAIL。PASS 只代表静态声明检查通过，不是 RTL 仿真或签核通过。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_INCOMPLETE = "INCOMPLETE"


def _canonical_hash(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _input_error(rule: str, target: str, message: str) -> dict[str, str]:
    return {"rule": rule, "target": target, "message": message, "status": STATUS_INCOMPLETE}


def _invalid_input_result(module: str, raw: Any, validation: list[dict[str, str]]) -> dict[str, Any]:
    """输入读不出来时也保持相同结果形状，调用方不必靠异常猜三态。"""
    return {
        "schema": "resource_intent_result_v1",
        "module": module,
        "status": STATUS_INCOMPLETE,
        "reason": "输入无法读取或解析，不能完成静态检查",
        "intent_hash": _canonical_hash({"raw_input": raw}),
        "counts": {"resources": 0, "operations": 0, "interactions": 0, "facts": 0, "scenarios": 0},
        "validation": validation,
        "conflicts": [],
        "overflows": [],
        "facts": [],
        "scenarios": [],
        "coverage": {},
        "model": {
            "schema": "resource_model_v1",
            "module": module,
            "check_window": 0,
            "resources": [],
            "operations": [],
            "interactions": [],
        },
    }


def _verify_address_width(address_width: Any) -> list[dict[str, str]]:
    if isinstance(address_width, bool) or not isinstance(address_width, int) or address_width <= 0:
        return [_input_error("invalid_address_width", "address_width", "必须是正整数")]
    return []


def verify_document(
    doc: dict[str, Any], *, address_width: int = 64, module: str = "", input_errors: list[dict[str, str]] = None
) -> dict[str, Any]:
    """ResourceModel dict → 三态结论 + 可落盘证据。

    解析失败留下的 ``input_errors`` 与模型声明错误统一进入 validation。
    当原始形状无法安全计算时，不生成伪造的 NONE overlap 或场景。
    """
    from src.mental_ir_plane.decision.resource_model import (
        compile_scenarios,
        coverage_summary,
        from_dict,
    )
    from src.mental_ir_plane.decision.resource_model.model import _issue

    width_errors = _verify_address_width(address_width)
    if not isinstance(doc, dict):
        doc = {}
        width_errors.append(_issue("invalid_document_type", "document", "根节点必须是对象"))
    model = from_dict(doc)
    model.module = model.module or module
    model.declaration_errors.extend(width_errors)
    model.declaration_errors.extend(input_errors or [])
    validation = model.validate(
        address_width=address_width
        if isinstance(address_width, int) and not isinstance(address_width, bool) and address_width > 0
        else 64
    )
    structural_error = bool(width_errors or input_errors or model.declaration_errors)
    facts = [] if structural_error else model.interaction_facts(address_width=address_width)
    scenarios = [] if structural_error else compile_scenarios(model, address_width=address_width)
    conflicts = [fact for fact in facts if fact.get("conflict")]
    overflows = [fact for fact in facts if fact.get("overflow")]
    status, reason = _decide(model, validation, conflicts, overflows)
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


def _decide(
    model: Any, validation: list[dict[str, str]], conflicts: list[dict[str, Any]], overflows: list[dict[str, Any]]
) -> tuple[str, str]:
    """声明不完整优先于事实裁决，禁止用非法声明制造一个 FAIL/PASS。"""
    if any(row.get("status", STATUS_INCOMPLETE) == STATUS_INCOMPLETE for row in validation):
        return STATUS_INCOMPLETE, "输入声明未通过完整性校验"
    if any(row.get("status") == STATUS_FAIL for row in validation):
        count = sum(row.get("status") == STATUS_FAIL for row in validation)
        return STATUS_FAIL, f"{count} 条确定的资源访问或地址范围违规"
    for key, label in (("resources", "resources"), ("operations", "operations"), ("interactions", "interactions")):
        if not getattr(model, key):
            return STATUS_INCOMPLETE, f"intent 缺少 {label}"
    if conflicts:
        return STATUS_FAIL, f"{len(conflicts)} 条禁止重叠冲突"
    if overflows:
        return STATUS_FAIL, f"{len(overflows)} 条地址溢出"
    return STATUS_PASS, "所有交互满足声明策略（静态检查）"


def read_document(path: str | Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """读 YAML/JSON，返回 **可安全建模** 的文档与解析错误，不抛解析异常。"""
    source = Path(path)
    kind = "yaml" if source.suffix.lower() in (".yaml", ".yml") else "json"
    try:
        text = source.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        return {}, [_input_error("input_unreadable", str(source), str(exc))]
    if kind == "yaml":
        import yaml

        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return {}, [_input_error("malformed_yaml", str(source), str(exc))]
    else:
        try:
            doc = json.loads(text)
        except (TypeError, ValueError) as exc:
            return {}, [_input_error("malformed_json", str(source), str(exc))]
    if doc is None:
        return {}, []
    if not isinstance(doc, dict):
        return {}, [_input_error("invalid_document_type", str(source), "根节点必须是对象")]
    return doc, []


def verify_file(path: str | Path, *, address_width: int = 64, module: str = "") -> dict[str, Any]:
    source = Path(path)
    doc, errors = read_document(source)
    module = module or str(doc.get("module") or "") or source.stem
    if errors and not doc:
        try:
            raw: Any = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            raw = str(source)
        return _invalid_input_result(module, raw, errors)
    return verify_document(doc, address_width=address_width, module=module, input_errors=errors)


def write_result(result: dict[str, Any], out_dir: str | Path) -> Path:
    from src.runtime_plane.core.runtime.atomic import atomic_write_json

    target = Path(out_dir) / "resource_intent_result.json"
    atomic_write_json(target, result)
    return target


__all__ = [
    "STATUS_FAIL",
    "STATUS_INCOMPLETE",
    "STATUS_PASS",
    "read_document",
    "verify_document",
    "verify_file",
    "write_result",
]
