"""测试点 IR —— 用例建模到后面整条流程的**那根轴**。

这里钉住四件事：

  ① 每个取值点**恰好**变成一个测试点（不多、不少、不撞号）；
  ② `realization` 三分法把"能驱动的 / 只能观测的"分开；
  ③ 覆盖仓、test 类名、回归级都能从测试点上**查回来**；
  ④ 与 `uvm_tools` 的命名契约逐字一致（两个包各写一份，靠测试对齐）。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from src.layers.l3_decision.casemodel.plan import (attribute_test_name, build_testpoints,
                                            run_testpoints, testpoints_yaml)
from src.layers.l3_decision.casemodel.tests.conftest import FC

FC_TEXT = FC.read_text(encoding="utf-8")
NPU = Path(__file__).resolve().parents[5] / "specs" / "npu_sched" / "casemodel.yaml"


def _with_stimulus(text: str, dim_id: str, field: str) -> str:
    doc = yaml.safe_load(text)
    for dim in doc.get("dimensions") or []:
        if dim.get("id") == dim_id:
            dim["stimulus"] = {"field": field}
            return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
    raise AssertionError(f"没有维度 {dim_id}")


class TestOneValuePointOneTestPoint:
    def test_count_matches_flat_value_points(self):
        """一个取值点都不能丢、也不能多 —— **resolve 之后**的模型才是准的
        （联动字段在解析时才展开成取值点）。"""
        from src.layers.l3_decision.casemodel.repository import load_models_from_text

        result = run_testpoints(FC_TEXT, env_name="fc_env")
        model = load_models_from_text(FC_TEXT, source="<test>")[0].resolve()
        expected = sum(len(f.value_points())
                       for d in model.dimensions for f in d.fields)
        assert result["count"] == expected

    def test_ids_are_unique_and_ascii(self):
        result = run_testpoints(FC_TEXT, env_name="fc_env")
        ids = [tp["tp_id"] for tp in result["testpoints"]]
        assert len(ids) == len(set(ids))
        assert all(tp.startswith("TP-") and tp.isascii() for tp in ids)

    def test_duplicate_dimension_value_gets_a_suffix(self):
        """同一维度两个字段撞出同一个 tp_id 时加序号，**不合并**。"""
        text = FC_TEXT.replace(
            "  - id: D_dur\n    name: 反压持续时间\n    fields:\n"
            "      - name: 反压持续时间\n",
            "  - id: D_dur\n    name: 反压持续时间\n    fields:\n"
            "      - name: 反压持续时间\n"
            "        type: enum\n        values: [\"1拍\"]\n"
            "      - name: 反压持续时间\n", 1)
        result = run_testpoints(text, env_name="fc_env", max_tests=None)
        dur = [tp["tp_id"] for tp in result["testpoints"]
               if tp["dimension"] == "D_dur"]
        assert len(dur) == len(set(dur))


class TestRealization:
    def test_default_is_observe(self):
        """FC 模型没写 stimulus —— 一条都不能假装能驱动。"""
        result = run_testpoints(FC_TEXT, env_name="fc_env")
        assert result["by_kind"] == {"observe": result["count"]}
        assert all(tp["observe_only"] for tp in result["testpoints"])

    def test_stimulus_carries_field_and_value(self):
        text = _with_stimulus(FC_TEXT, "D_ratio", "credit")
        result = run_testpoints(text, env_name="fc_env",
                                agents={"fc_master": ["credit"]})
        bound = [tp for tp in result["testpoints"] if tp["dimension"] == "D_ratio"]
        assert bound and all(tp["realization"]["kind"] == "stimulus" for tp in bound)
        assert {tp["realization"]["field"] for tp in bound} == {"credit"}
        assert {tp["realization"]["agent"] for tp in bound} == {"fc_master"}
        assert [tp["realization"]["value"] for tp in bound] == [0, 10, 50, 100]

    def test_unknown_field_is_reported_not_silently_dropped(self):
        text = _with_stimulus(FC_TEXT, "D_ratio", "creditt")
        result = run_testpoints(text, env_name="fc_env",
                                agents={"fc_master": ["credit"]})
        assert any("creditt" in n and "不会生效" in n for n in result["notes"])

    def test_explicit_observe_is_recorded(self):
        doc = yaml.safe_load(FC_TEXT)
        for dim in doc["dimensions"]:
            if dim["id"] == "D_ratio":
                dim["realization"] = {"kind": "observe"}
        result = run_testpoints(yaml.safe_dump(doc, allow_unicode=True),
                                env_name="fc_env")
        ratio = [tp for tp in result["testpoints"] if tp["dimension"] == "D_ratio"]
        assert ratio and all(tp["realization"]["kind"] == "observe" for tp in ratio)


class TestObservationLink:
    def test_explicit_range_bins_map_by_value(self):
        """`D_queue=1` 落在显式仓 `low` 里 —— 覆盖端对账靠这一格。"""
        result = run_testpoints(NPU.read_text(encoding="utf-8"),
                                env_name="npu_sched_env", module_name="npu_sched")
        q1 = [tp for tp in result["testpoints"]
              if tp["dimension"] == "D_queue" and tp["value"] == "1"][0]
        assert q1["coverpoint"] == "cp_queue_level"
        assert q1["bin"] == "low"

    def test_stage_follows_priority(self):
        result = run_testpoints(NPU.read_text(encoding="utf-8"),
                                env_name="npu_sched_env", module_name="npu_sched")
        mac = [tp for tp in result["testpoints"] if tp["tp_id"].endswith("D_TYPE-MAC")][0]
        assert mac["priority"] == "P0"
        assert mac["execution"]["stage"] == "p0"

    def test_requirement_and_cover_id_are_carried(self):
        result = run_testpoints(NPU.read_text(encoding="utf-8"),
                                env_name="npu_sched_env", module_name="npu_sched")
        mac = [tp for tp in result["testpoints"] if tp["tp_id"].endswith("D_TYPE-MAC")][0]
        assert mac["requirement"] == "REQ-NPU-002"
        assert mac["cover_id"] == "CP_NPU_TYPE_002"


class TestNamingContract:
    """`plan.py` 与 `gen_uvm.attr_class_slug` 各写一份 —— 必须逐字一致。"""

    def test_class_names_match_uvm_tools(self):
        from src.tools.generation.uvm_tools.generation.render.jinja_renderer import attr_class_slug

        cases = [("D_ratio", "50", 50), ("D_mode", "首拍", 1),
                 ("D_type", "MAC", 0), ("反压模式", "尾拍", 2)]
        for dim, value, iv in cases:
            our = attribute_test_name("fc_env", dim, value, iv)
            theirs = f"fc_env_{attr_class_slug({'dimension': dim, 'value': value, 'int_value': iv})}_test"
            assert our == theirs, (dim, value)

    def test_yaml_round_trips(self):
        result = run_testpoints(FC_TEXT, env_name="fc_env")
        doc = yaml.safe_load(testpoints_yaml(result))
        assert doc["count"] == result["count"]
        assert len(doc["testpoints"]) == result["count"]
        assert doc["testpoints"][0]["tp_id"].startswith("TP-")


class TestTruncation:
    def test_boundary_values_survive(self):
        result = run_testpoints(FC_TEXT, env_name="fc_env", max_tests=4)
        assert result["count"] == 4
        assert any("截断" in n for n in result["notes"])
        # 前 4 条按边界优先挑 —— 至少有一条来自 D_ratio 的边界值
        assert any(tp["dimension"] == "D_ratio" for tp in result["testpoints"])

    def test_same_cap_selects_the_same_points_as_uvm_tests(self):
        """TP IR 与 `environment.tests` **必须截到同一批取值点**。

        两条路各自推送 `max_tests`，一旦挑选顺序不同，就会出现"TP 说这条
        该跑、生成的 test 类却不存在"的幽灵测试点。
        """
        from src.layers.l3_decision.casemodel.api import run_uvm_tests

        for cap in (3, 4, 7, 11):
            tps = run_testpoints(FC_TEXT, env_name="fc_env", max_tests=cap)
            tests = run_uvm_tests(FC_TEXT, max_tests=cap)["tests"]
            assert [(t["dimension"], t["value"]) for t in tps["testpoints"]] == \
                   [(t["dimension"], t["value"]) for t in tests]


class TestBackdoorRealization:
    """观测型维度的**状态注入** —— 没有输入引脚也能确定到达目标仓。"""

    def _model(self):
        doc = yaml.safe_load(FC_TEXT)
        for dim in doc.get("dimensions") or []:
            if dim.get("id") == "D_ratio":
                dim["realization"] = {"kind": "backdoor",
                                      "path": "tb.dut.credit"}
        return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)

    def test_tp_carries_the_path_and_is_not_observe_only(self):
        result = run_testpoints(self._model(), env_name="fc_env")
        ratio = [tp for tp in result["testpoints"] if tp["dimension"] == "D_ratio"]
        assert ratio and all(tp["realization"]["kind"] == "backdoor" for tp in ratio)
        assert all(tp["realization"]["path"] == "tb.dut.credit" for tp in ratio)
        assert not any(tp["observe_only"] for tp in ratio)

    def test_uvm_tests_entry_carries_backdoor_path(self):
        from src.layers.l3_decision.casemodel.api import run_uvm_tests

        tests = run_uvm_tests(self._model(), dimensions=["D_ratio"])["tests"]
        assert tests and all(t.get("backdoor_path") == "tb.dut.credit" for t in tests)
        assert all("field" not in t for t in tests)   # 不是 stimulus

    def test_a_backdoor_without_path_falls_back_to_observe(self):
        doc = yaml.safe_load(FC_TEXT)
        for dim in doc.get("dimensions") or []:
            if dim.get("id") == "D_ratio":
                dim["realization"] = {"kind": "backdoor"}
        result = run_testpoints(yaml.safe_dump(doc, allow_unicode=True),
                                env_name="fc_env")
        ratio = [tp for tp in result["testpoints"] if tp["dimension"] == "D_ratio"]
        assert all(tp["realization"]["kind"] == "observe" for tp in ratio)
        assert any("realization.path" in n for n in result["notes"])
