"""一条 TP 可被**多条**业务 CASE 共享 —— 多对多绑定。

为什么需要：业务 xlsx 投影出的 CASE 各自声明 `dimensions`。两条用例可能
绑同一维度（CASE A 只绑 `D_x`，CASE B 绑 `D_x + D_y`），此时 `D_x` 下的
TP 是**共同证据**。若身份只保留主 `case_id`，后绑的 CASE 永远空，门禁会
把"没归到"错报成"没覆盖"。

这里钉三件事：
  ① `CaseDoc.resolve_all` 返回全部匹配身份，`resolve` 仍给首项（兼容）；
  ② 生成期把全量写进 TP（`case_ids`），契约按每个身份归并；
  ③ 回归 shell 的 `test → CASE` 映射不漏掉非主身份。
"""
from __future__ import annotations

import yaml

from src.ir_plane.vplan.runtime import plan
from src.ir_plane.vplan.runtime.repository import load_models_from_text

MODEL = """
object: T
dimensions:
  - id: D_x
    name: X
    fields:
      - name: f
        values: [0, 1]
cases:
  categories:
    - id: CCAT-ROOT
      name: root
  cases:
    - id: CASE-A
      name: A
      dimensions: [D_x]
    - id: CASE-B
      name: B
      dimensions: [D_x]
"""


def _bundle():
    model = load_models_from_text(MODEL)[0]
    return plan.build_bundle(model, env_name="t_env", module_name="T")


class TestResolveAll:
    def test_all_cases_sharing_a_dimension_are_returned(self):
        from src.ir_plane.decision.case_ir import parse_declared

        doc = parse_declared(yaml.safe_load(MODEL)["cases"], module="T")
        assert doc.resolve_all(dimension="D_x") == ["CASE-A", "CASE-B"]
        # 旧读端：首项即主身份
        assert doc.resolve(dimension="D_x") == "CASE-A"

    def test_no_match_is_empty_not_a_default_case(self):
        from src.ir_plane.decision.case_ir import parse_declared

        doc = parse_declared(yaml.safe_load(MODEL)["cases"], module="T")
        assert doc.resolve_all(dimension="D_missing") == []
        assert doc.resolve(dimension="D_missing") == ""


class TestGenerationWritesAllCaseIds:
    def test_tp_carries_every_shared_case(self):
        bundle = _bundle()
        assert bundle.testpoints
        for tp in bundle.testpoints:
            assert tp.case_id == "CASE-A"
            assert tp.case_ids == ["CASE-A", "CASE-B"]

    def test_every_case_gets_the_shared_tp_contract(self):
        bundle = _bundle()
        by_case = {c["id"]: c for c in bundle.case_doc["cases"]}
        for cid in ("CASE-A", "CASE-B"):
            groups = by_case[cid]["groups"]
            assert groups, f"{cid} 没有拿到共享 TP 的组契约"
            assert {t for g in groups for t in g["tp_ids"]} == {
                tp.tp_id for tp in bundle.testpoints}

    def test_single_identity_is_not_duplicated_in_ir(self):
        """只有一个身份时不额外写 `case_ids` —— 与 `case_id` 重复没有信息。"""
        tp = _bundle().testpoints[0]
        tp.case_ids = ["CASE-A"]
        tp.case_id = "CASE-A"
        assert "case_ids" not in tp.to_dict()
        assert tp.to_dict()["case_id"] == "CASE-A"


class TestRegressionMapKeepsAllCases:
    def test_test_to_case_map_unions_case_ids(self, tmp_path):
        from src.orchestration_plane.l2.regression_tools.regression_framework.generators.shell import (
            _testpoint_case_map_detail)

        (tmp_path / "coverage").mkdir()
        (tmp_path / "coverage" / "testpoints.yaml").write_text(
            yaml.safe_dump({"testpoints": [{
                "tp_id": "TP-1",
                "execution": {"test": "t_x_test"},
                "case_id": "CASE-A",
                "case_ids": ["CASE-A", "CASE-B"],
            }]}), encoding="utf-8")
        assert _testpoint_case_map_detail(tmp_path) == {
            "t_x_test": ["CASE-A", "CASE-B"]}
