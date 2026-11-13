"""M3 规则引擎：声明式规则 + 规则表 + 可关闭。

停点：新增一条"某字段为空/缺失"的规则，**只改 YAML**；每条 finding 带
`rule_id` 与 `evidence`（CI 能列出每条 blocker 看了哪些数据）。
"""
from __future__ import annotations

from src.ir_plane.decision.case_view.gates import (
    load_declarative, load_rules, rules_table, validate_case_view,
)

CASE_IR = {"cases": [{
    "id": "CASE-A",
    "groups": [
        {"group": "CG-A", "name": "功能A", "cell": "CELL-A", "tp_ids": ["TP-1"],
         "required_layers": ["functional"], "requirements": ["REQ-1"]},
        {"group": "CG-B", "name": "功能B", "cell": "CELL-B", "tp_ids": ["TP-2"],
         "required_layers": ["functional"], "requirements": []},
    ],
    "sva": [], "scb": [],
}]}

VIEW = {"cases": []}
CELLS = {"cells": []}
EVD = {"evd": []}

RULE = {
    "id": "CASE_GROUP_NO_REQUIREMENT",
    "level": "warning",
    "stage": "report",
    "title": "覆盖率组没有需求编号",
    "source": "case_groups",
    "where": {"requirements": {"op": "empty"}},
    "target": "{case}/{group}",
    "message": "覆盖率组 {group} 没有 requirements",
    "evidence": ["case", "group"],
}


def _run(declarative=None, rules=None):
    return validate_case_view(VIEW, CELLS, EVD, rules or load_rules(),
                              case_ir=CASE_IR, case_cov=[],
                              declarative=declarative or [])


class TestDeclarativeRules:
    def test_rule_fires_on_matching_item_only(self):
        report = _run([RULE])
        hits = [w for w in report["warnings"] if w["rule"] == "CASE_GROUP_NO_REQUIREMENT"]
        assert len(hits) == 1
        assert hits[0]["target"] == "CASE-A/CG-B"
        assert hits[0]["evidence"] == {"case": "CASE-A", "group": "CG-B"}
        assert hits[0]["rule_id"] == "CASE_GROUP_NO_REQUIREMENT"

    def test_rule_can_be_disabled_from_yaml(self):
        rules = load_rules()
        rules["CASE_GROUP_NO_REQUIREMENT"] = {"level": "warning", "enabled": False,
                                              "title": "x"}
        report = _run([RULE], rules=rules)
        assert not [w for w in report["warnings"]
                    if w["rule"] == "CASE_GROUP_NO_REQUIREMENT"]

    def test_missing_and_present_ops(self):
        rule = dict(RULE, id="CG_NO_CELL", where={"cell": {"op": "missing"}},
                    level="info")
        report = _run([rule])
        assert not [i for i in report["infos"] if i["rule"] == "CG_NO_CELL"]

    def test_unknown_source_yields_nothing(self):
        rule = dict(RULE, id="X_UNKNOWN", source="no_such_table")
        assert not [w for w in _run([rule])["warnings"] if w["rule"] == "X_UNKNOWN"]


class TestRuleTable:
    def test_table_lists_level_stage_enabled(self):
        rows = {r["id"]: r for r in rules_table(load_rules())}
        assert rows["CASE_GROUPS_EMPTY"]["level"] == "blocker"
        assert rows["CASE_GROUPS_EMPTY"]["enabled"] is True
        assert "stage" in rows["CASE_GROUPS_EMPTY"]

    def test_repo_rule_file_declares_the_requirement_rule(self):
        ids = [r.get("id") for r in load_declarative()]
        assert "CASE_GROUP_NO_REQUIREMENT" in ids
