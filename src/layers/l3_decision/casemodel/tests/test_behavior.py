"""行为域（方法学 v2 P1）：建模 / 校验 / 进 TP IR。

v1 模型不写 `behavior:` 时，产物必须与之前逐字节一致 —— 这是每个阶段的门槛。
"""
from __future__ import annotations

import yaml

from src.layers.l3_decision.casemodel.api import run_testpoints, run_validate
from src.layers.l3_decision.casemodel.analysis import analyze
from src.layers.l3_decision.casemodel.repository import load_models_from_text

BEHAVIOR = {
    "id": "QUEUE",
    "name": "队列水位",
    "states": ["EMPTY", "LOW", "FULL"],
    "events": ["enqueue", "dequeue"],
    "checks": ["CHECK-FUNC"],
    "transitions": [
        {"id": "TR-1", "from": "EMPTY", "event": "enqueue", "to": "LOW"},
        {"id": "TR-2", "from": "LOW", "event": "enqueue", "to": "FULL"},
    ],
    "sequences": [
        {"id": "SEQ-1",
         "steps": [{"event": "enqueue", "repeat": 2},
                   {"event": "dequeue"}],
         "expects": ["CHECK-FUNC"]},
    ],
    "temporal": [
        {"id": "TMP-1", "trigger": "enqueue",
         "condition": {"queue_full": True},
         "response": {"backpressure": True},
         "within": {"cycles": 1},
         "checks": ["CHECK-FUNC"]},
    ],
}


def _spec(behavior=None) -> dict:
    spec = {
        "version": "1", "object": "dut", "object_code": "DUT",
        "sub_objects": [{"id": "OBJ-01", "name": "F", "code": "F1"}],
        "dimensions": [{"id": "D_type", "name": "类型",
                        "fields": [{"name": "t", "type": "enum",
                                    "values": ["A", "B"]}]}],
        "themes": [{"id": "TH-P0", "name": "f", "priority": "P0",
                    "dimensions": ["D_type"]}],
    }
    if behavior is not None:
        spec["behavior"] = behavior
    return spec


def _text(spec: dict) -> str:
    return yaml.safe_dump(spec, allow_unicode=True, sort_keys=False)


class TestBehaviorParsing:
    def test_states_events_and_nodes_are_parsed(self):
        model = load_models_from_text(_text(_spec(BEHAVIOR)))[0]
        behavior = model.behavior
        assert behavior.id == "QUEUE"
        assert behavior.states == ["EMPTY", "LOW", "FULL"]
        assert [t.id for t in behavior.transitions] == ["TR-1", "TR-2"]
        assert behavior.sequences[0].steps[0]["repeat"] == 2
        assert behavior.temporal[0].within == {"cycles": 1}

    def test_model_without_behavior_has_none(self):
        assert load_models_from_text(_text(_spec()))[0].behavior is None


class TestBehaviorSchema:
    def test_a_well_formed_block_validates(self):
        errors = [i for i in (run_validate(_text(_spec(BEHAVIOR))).get("issues") or [])
                  if i.get("severity") == "error"]
        assert errors == [], errors

    def test_transition_missing_to_is_a_schema_error(self):
        bad = dict(BEHAVIOR)
        bad["transitions"] = [{"id": "TR-1", "from": "EMPTY", "event": "enqueue"}]
        errors = [i for i in (run_validate(_text(_spec(bad))).get("issues") or [])
                  if i.get("severity") == "error"]
        assert errors


class TestBehaviorRules:
    def _rules(self, behavior: dict) -> set:
        model = load_models_from_text(_text(_spec(behavior)))[0]
        return {i.rule for i in analyze(model).issues}

    def test_unknown_state_or_event_is_an_error(self):
        bad = dict(BEHAVIOR)
        bad["transitions"] = [
            {"id": "TR-X", "from": "GHOST", "event": "teleport", "to": "LOW"}]
        assert "behavior_ref_unknown" in self._rules(bad)

    def test_missing_check_is_an_error(self):
        bad = dict(BEHAVIOR)
        bad.pop("checks")
        bad["transitions"] = [
            {"id": "TR-1", "from": "EMPTY", "event": "enqueue", "to": "LOW"}]
        assert "behavior_no_check" in self._rules(bad)

    def test_duplicate_node_ids_are_an_error(self):
        bad = dict(BEHAVIOR)
        bad["sequences"] = [{"id": "TR-1", "steps": [{"event": "enqueue"}],
                             "expects": ["CHECK-FUNC"]}]
        assert "behavior_duplicate_node" in self._rules(bad)

    def test_a_clean_behavior_has_no_behavior_rules(self):
        rules = self._rules(BEHAVIOR)
        assert not {r for r in rules if r.startswith("behavior_")}


class TestBehaviorInIr:
    def test_behavior_nodes_become_testpoints(self):
        payload = run_testpoints(_text(_spec(BEHAVIOR)))
        by_prefix = [tp for tp in payload["testpoints"]
                     if "-BEH-" in tp["tp_id"]]
        assert len(by_prefix) == 4          # 2 迁移 + 1 序列 + 1 时序
        kinds = {tp["realization"]["kind"] for tp in by_prefix}
        assert kinds == {"observe", "sequence"}
        assert all(tp["execution"]["stage"] == "behavior" for tp in by_prefix)
        assert payload["by_stage"]["behavior"] == 4

    def test_v1_model_payload_is_unchanged(self):
        payload = run_testpoints(_text(_spec()))
        assert payload["count"] == 2
        assert "behavior" not in payload["by_stage"]
        assert all("行为域" not in note for note in payload["notes"])
