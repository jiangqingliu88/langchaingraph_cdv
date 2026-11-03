"""Case 视图必须说清"**覆盖什么**"：覆盖率组 / 覆盖类型 / 作用域 / SVA / SCB。

只有一堆 `CG-D_DEP / PROVEN` 的表格证明不了任何事——读的人看不出这是一条
"数据依赖"用例、跑的是组合逻辑还是状态迁移、由哪条断言和哪个比对兜底。
验收口径：Markdown 与 HTML 都要有这四样东西。
"""
from __future__ import annotations

import json

from src.tools.humanview.case_associate_view.render import (
    render_html, render_markdown,
)


def _view() -> dict:
    return {
        "schema": "case_associate_view_v2",
        "run": "run_x",
        "features": [], "gaps": [],
        "matrix": {"groups": [], "rows": []},
        "cases": [{
            "task": "t1", "name": "t1", "case_id": "CASE-D_DEP",
            "tst_id": "TST-X@1", "case_status": "PARTIAL",
            "conclusion": "待补",
            "coverage": {"status": "green", "detail": "全部仓命中"},
            "sva": {"status": "yellow", "detail": "未声明/未执行"},
            "scoreboard": {"status": "green", "detail": "matched=40"},
            "path": {"status": "na", "detail": "未声明 PATH 组"},
            "groups_evidence": [{
                "group": "CG-D_DEP", "name": "数据依赖",
                "description": "RAW/WAW/WAR 依赖处理",
                "coverage_type": "功能覆盖", "scope": "指令依赖检查",
                "coverpoints": ["cp_dep_type"], "requirements": ["REQ-NPU-004"],
                "checks": ["CHECK-FUNC"], "cell": "CELL-D_DEP-P1",
                "required_layers": ["functional", "timing", "data"],
                "functional": {"status": "PROVEN"}, "timing": {"status": "NOT_APPLICABLE"},
                "data": {"status": "PROVEN"}, "path": {"status": "NOT_APPLICABLE"},
                "result": "PARTIAL",
            }],
            "sva_items": [{
                "id": "SVA-RAW", "name": "raw_never_issues",
                "expr": "dep_type == 2'd1 |-> issue_valid == 1'b0",
                "cell": "CELL-D_DEP-P1", "hit": None, "fail": 0,
                "cover_property_hit": None, "status": "MISSING",
            }],
            "scb_items": [{
                "id": "SB-DUT", "name": "in-order 比对",
                "description": "DUT 检查收口", "evidence_mode": "aggregate",
                "evidence_level": "aggregate", "cell": "CELL-D_DEP-P1",
                "exec": 40, "matched": 40, "mismatched": 0, "status": "PROVEN",
            }],
        }],
        "case_cell": {"rows": [{"cell_id": "CELL-D_DEP-P1", "cg": "CG-D_DEP",
                                "p": "p1", "color": "yellow", "tp_count": 4,
                                "declared_cases": ["CASE-D_DEP"],
                                "observed_cases": ["CASE-D_DEP"]}]},
        "case_runs": [],
    }


def test_markdown_has_group_overview_with_semantics():
    md = render_markdown(_view())
    assert "覆盖率组总览" in md
    for phrase in ("CG-D_DEP", "数据依赖", "功能覆盖", "指令依赖检查",
                   "cp_dep_type", "REQ-NPU-004", "functional + timing + data"):
        assert phrase in md, phrase


def test_markdown_three_sets_carry_assertion_and_scb_semantics():
    md = render_markdown(_view())
    assert "SVA（断言）" in md and "raw_never_issues" in md
    assert "dep_type == 2'd1" in md                      # 规则原文
    assert "SCB（比对）" in md and "DUT 检查收口" in md   # 比的是什么
    assert "aggregate" in md                              # 证据粒度


def test_html_has_the_same_sections():
    page = render_html(_view())
    for phrase in ("覆盖率组总览", "三集合证据", "功能覆盖", "指令依赖检查",
                   "SVA（断言）", "SCB（比对）", "Case × CELL"):
        assert phrase in page, phrase
    assert "dep_type == 2'd1" in page


def test_rendering_is_json_safe():
    """视图数据最终要进 JSON / 签核包，渲染不能依赖不可序列化的东西。"""
    json.dumps(_view(), ensure_ascii=False)
    assert render_markdown(_view()).count("CG-D_DEP") >= 2
