"""配置域（方法学 v2 P3a）：建模 / 校验 / 组合可行性进 TP IR。

P3a 只枚举组合、不把配置乘进 TP（那是 P3b）—— 因此 v1 模型与不写配置的模型
产物完全不变，写了配置的模型多一段 `config_space` 摘要。
"""
from __future__ import annotations

import yaml

from src.layers.l3_decision.casemodel.api import run_testpoints, run_validate
from src.layers.l3_decision.casemodel.analysis import analyze
from src.layers.l3_decision.casemodel.repository import load_models_from_text

CONFIG = {
    "dimensions": [
        {"name": "queue_depth", "values": [8, 16, 32]},
        {"name": "gemm_enable", "values": [True, False]},
    ],
    "cross_groups": [
        {"id": "XG-CFG-01", "dimensions": ["queue_depth", "gemm_enable"]},
    ],
    "feasibility": [
        {"id": "CFG-RULE-01", "when": {"gemm_enable": False},
         "then": {"exclude": True}},
    ],
    "max_combinations": 32,
}


def _spec(config=None) -> dict:
    spec = {
        "version": "1", "object": "dut", "object_code": "DUT",
        "sub_objects": [{"id": "OBJ-01", "name": "F", "code": "F1"}],
        "dimensions": [{"id": "D_type", "name": "类型",
                        "fields": [{"name": "t", "type": "enum",
                                    "values": ["A", "B"]}]}],
        "themes": [{"id": "TH-P0", "name": "f", "priority": "P0",
                    "dimensions": ["D_type"]}],
    }
    if config is not None:
        spec["config_space"] = config
    return spec


def _text(spec: dict) -> str:
    return yaml.safe_dump(spec, allow_unicode=True, sort_keys=False)


class TestConfigParsing:
    def test_dimensions_and_rules_are_parsed(self):
        model = load_models_from_text(_text(_spec(CONFIG)))[0]
        space = model.config_space
        assert [d.name for d in space.dimensions] == ["queue_depth", "gemm_enable"]
        assert space.max_combinations == 32
        assert space.feasibility[0]["id"] == "CFG-RULE-01"

    def test_model_without_config_has_none(self):
        assert load_models_from_text(_text(_spec()))[0].config_space is None


class TestConfigSchema:
    def test_a_well_formed_block_validates(self):
        errors = [i for i in (run_validate(_text(_spec(CONFIG))).get("issues") or [])
                  if i.get("severity") == "error"]
        assert errors == [], errors

    def test_dimension_without_values_is_a_schema_error(self):
        bad = {"dimensions": [{"name": "q"}]}
        errors = [i for i in (run_validate(_text(_spec(bad))).get("issues") or [])
                  if i.get("severity") == "error"]
        assert errors


class TestConfigRules:
    def _rules(self, config: dict) -> set:
        model = load_models_from_text(_text(_spec(config)))[0]
        return {i.rule for i in analyze(model).issues}

    def test_duplicate_dimension_is_an_error(self):
        bad = {"dimensions": [{"name": "q", "values": [1]},
                              {"name": "q", "values": [2]}]}
        assert "config_duplicate_dimension" in self._rules(bad)

    def test_unknown_reference_is_an_error(self):
        bad = {"dimensions": [{"name": "q", "values": [1]}],
               "feasibility": [{"id": "R", "when": {"ghost": 1}}]}
        assert "config_ref_unknown" in self._rules(bad)

    def test_value_outside_the_dimension_is_an_error(self):
        bad = {"dimensions": [{"name": "q", "values": [1]}],
               "feasibility": [{"id": "R", "when": {"q": 99}}]}
        assert "config_ref_unknown" in self._rules(bad)

    def test_combination_cap_warns(self):
        bad = {"dimensions": [{"name": "a", "values": list(range(8))},
                              {"name": "b", "values": list(range(8))}],
               "max_combinations": 10}
        assert "config_combination_cap" in self._rules(bad)

    def test_a_clean_space_has_no_config_rules(self):
        rules = self._rules(CONFIG)
        assert not {r for r in rules if r.startswith("config_")}


class TestConfigInIr:
    def test_summary_counts_feasible_and_excluded(self):
        payload = run_testpoints(_text(_spec(CONFIG)))
        summary = payload["config_space"]
        assert summary["total"] == 6
        assert summary["feasible"] == 3          # gemm_enable=False 的 3 组被排除
        assert {e["rule"] for e in summary["excluded"]} == {"CFG-RULE-01"}

    def test_model_without_config_keeps_the_v1_payload(self):
        payload = run_testpoints(_text(_spec()))
        assert "config_space" not in payload


class TestConfigInstances:
    """P3b：配置是**执行实例维度**，不是新的 tp_id。"""

    def test_each_tp_carries_the_feasible_combinations(self):
        payload = run_testpoints(_text(_spec(CONFIG)))
        for tp in payload["testpoints"]:
            assert len(tp["config_instances"]) == 3      # 6 组里 3 组被排除
        assert payload["config_space"]["instances_total"] == 3 * payload["count"]

    def test_disable_tps_only_removes_that_combination(self):
        config = {
            "dimensions": [{"name": "mode", "values": ["on", "off"]}],
            "feasibility": [{"id": "R", "when": {"mode": "off"},
                             "then": {"disable_tps": ["*"]}}],
        }
        payload = run_testpoints(_text(_spec(config)))
        for tp in payload["testpoints"]:
            assert tp["config_instances"] == [{"mode": "on"}]
        assert payload["config_space"]["instances_total"] == payload["count"]

    def test_no_config_means_no_instances_key(self):
        payload = run_testpoints(_text(_spec()))
        assert all("config_instances" not in tp for tp in payload["testpoints"])


def test_config_instances_stay_out_of_the_ir_yaml():
    """YAML 是人读的 IR（也是 manifest 哈希对象）—— 配置实例只进 JSON。"""
    import hashlib

    payload = run_testpoints(_text(_spec(CONFIG)))
    assert "config_instances" in payload["testpoints"][0]
    assert "config_instances" not in payload["testpoints_yaml"]
    want = ((payload.get("methodology") or {}).get("artifacts") or {}) \
        .get("testpoints_yaml", {}).get("sha256", "")
    got = hashlib.sha256(payload["testpoints_yaml"].encode("utf-8")).hexdigest()
    assert got == want
