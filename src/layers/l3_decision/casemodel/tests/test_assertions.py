"""断言建模与「断言 ↔ TP」绑定（方法学 P2）。

三件事必须成立：
  1. `assertions:` 是 schema 的一部分（以前模型里写了它，schema 直接判错）；
  2. 绑定到不存在的 TP 要在建模期报错，不是仿真时才发现；
  3. TP IR 里带反向索引，签核/失败报告能回答"这条断言护住了哪些 TP"。
"""
from __future__ import annotations

import pathlib

import yaml

from src.layers.l3_decision.casemodel.api import run_testpoints, run_validate
from src.layers.l3_decision.casemodel.analysis import analyze
from src.layers.l3_decision.casemodel.framework.naming import iter_value_points
from src.layers.l3_decision.casemodel.repository import load_models_from_text

NPU = (pathlib.Path(__file__).resolve().parents[5]
       / "specs" / "npu_sched" / "casemodel.yaml")


def _model(assertions=None) -> dict:
    spec = {
        "version": "1", "object": "dut", "object_code": "DUT",
        "sub_objects": [{"id": "OBJ-01", "name": "F", "code": "F1"}],
        "dimensions": [{"id": "D_type", "name": "类型",
                        "fields": [{"name": "t", "type": "enum",
                                    "values": ["A", "B"]}]}],
        "themes": [{"id": "TH-P0", "name": "f", "priority": "P0",
                    "dimensions": ["D_type"]}],
    }
    if assertions is not None:
        spec["assertions"] = assertions
    return spec


def _text(spec: dict) -> str:
    return yaml.safe_dump(spec, allow_unicode=True, sort_keys=False)


def _tp_ids(spec: dict) -> list:
    model = load_models_from_text(_text(spec))[0]
    return [tp_id for *_rest, tp_id in iter_value_points(model)]


class TestAssertionParsing:
    def test_id_defaults_to_name_and_role_defaults_to_primary(self):
        spec = _model([{"name": "p_x", "expr": "a |-> b",
                        "tp_bindings": [{"tp_id": "TP-DUT-D_type-A-0"}]}])
        model = load_models_from_text(_text(spec))[0]
        assert len(model.assertions) == 1
        assertion = model.assertions[0]
        assert assertion.id == "p_x"
        assert assertion.tp_bindings == [{"tp_id": "TP-DUT-D_type-A-0",
                                          "role": "primary"}]
        assert assertion.failure_severity == "error"

    def test_entry_without_expr_is_dropped(self):
        spec = _model([{"name": "p_x"}])
        model = load_models_from_text(_text(spec))[0]
        assert model.assertions == []


class TestAssertionSchema:
    def test_the_shipped_npu_model_validates(self):
        """这份模型一直有 `assertions:`，但 schema 以前不认 —— 现在必须绿。"""
        errors = [i for i in (run_validate(NPU.read_text(encoding="utf-8"))
                              .get("issues") or []) if i.get("severity") == "error"]
        assert errors == [], errors

    def test_assertion_without_expr_is_a_schema_error(self):
        spec = _model([{"name": "p_x"}])
        errors = [i for i in (run_validate(_text(spec)).get("issues") or [])
                  if i.get("severity") == "error"]
        assert errors
        assert any("assertions" in str(i.get("target") or i) for i in errors)


class TestAssertionRules:
    def _rules(self, spec: dict) -> set:
        result = analyze(load_models_from_text(_text(spec))[0])
        return {i.rule for i in result.issues}

    def test_unknown_tp_binding_is_an_error(self):
        spec = _model([{"name": "p_x", "expr": "a |-> b",
                        "tp_bindings": [{"tp_id": "TP-DUT-GHOST-A-0"}]}])
        assert "assertion_tp_unknown" in self._rules(spec)

    def test_partial_binding_warns(self):
        tp = _tp_ids(_model())[0]
        spec = _model([
            {"name": "p_ok", "expr": "a |-> b", "tp_bindings": [{"tp_id": tp}]},
            {"name": "p_lost", "expr": "c |-> d"},
        ])
        assert "assertion_unbound" in self._rules(spec)

    def test_v1_model_without_any_binding_is_silent(self):
        spec = _model([{"name": "p_x", "expr": "a |-> b"}])
        assert "assertion_unbound" not in self._rules(spec)

    def test_shipped_npu_model_is_silent(self):
        result = analyze(load_models_from_text(NPU.read_text(encoding="utf-8"))[0])
        rules = {i.rule for i in result.issues}
        assert "assertion_tp_unknown" not in rules
        assert "assertion_unbound" not in rules


class TestAssertionBindingsInIr:
    def test_payload_carries_the_reverse_index(self):
        tp = _tp_ids(_model())[0]
        spec = _model([{"name": "p_x", "expr": "a |-> b",
                        "tp_bindings": [{"tp_id": tp, "role": "supporting"},
                                        {"tp_id": "TP-DUT-GHOST-A-0"}]}])
        payload = run_testpoints(_text(spec))
        bindings = payload["assertion_bindings"]
        assert bindings[0]["assertion_id"] == "p_x"
        assert bindings[0]["tp_ids"] == [tp]
        assert bindings[0]["roles"] == {tp: "supporting"}
        assert bindings[0]["unknown"] == ["TP-DUT-GHOST-A-0"]

    def test_model_without_assertions_keeps_the_v1_payload_shape(self):
        payload = run_testpoints(_text(_model()))
        assert "assertion_bindings" not in payload
