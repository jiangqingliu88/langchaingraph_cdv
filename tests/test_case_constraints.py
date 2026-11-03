"""Case 的**第四集合**：约束 id（`p_*` 策略）—— 归属按维度交集，不猜。

一条用例要能回答"它的激励受哪些约束塑造"。约束本体由 case 模型生成
（`coverage_plan.constraint_backing.policies[]`，带 `backed/dimensions`），
这里钉住三件事：

    归属   维度交集（大小写/`CG-` 前缀归一），没有交集就是空
    契约   约束 id 进 `CaseSpec`，因此进契约哈希（约束换版 → 旧证据失效）
    落盘   Case IR / TP IR / task_meta 三处一致
"""
from __future__ import annotations

from src.tools.humanview.case_ir.constraints import (
    attach_constraints, constraints_for, policy_index,
)

PLAN = {
    "constraint_backing": {
        "policies": [
            {"name": "p_th_b04_combo", "backed": False,
             "dimensions": ["D_dep", "D_decision"], "reason": "空骨架"},
            {"name": "p_th_b02_random", "backed": True,
             "dimensions": ["D_type"], "reason": "1 个字段赋值"},
        ]
    }
}

CASE_IR = {
    "module": "demo",
    "cases": [
        {"id": "CASE-D_DEP", "dimensions": ["D_dep"],
         "groups": [{"group": "CG-D_dep", "cell": "CELL-D_DEP-P1"}],
         "sva": [], "scb": []},
        {"id": "CASE-D_TYPE", "dimensions": ["D_TYPE"],
         "groups": [{"group": "CG-D_TYPE", "cell": "CELL-D_TYPE-P0"}],
         "sva": [], "scb": []},
        {"id": "CASE-BEH", "dimensions": ["BEH_QUEUE"],
         "groups": [{"group": "CG-BEH_QUEUE", "cell": "CELL-BEH-P"}],
         "sva": [], "scb": []},
    ],
}


def test_policy_index_keeps_backing_state():
    index = policy_index(PLAN)
    assert index["p_th_b04_combo"]["backed"] is False
    assert index["p_th_b02_random"]["dimensions"] == ["D_type"]


def test_constraints_follow_dimension_intersection_case_insensitively():
    by_dim = {}
    for pid, meta in policy_index(PLAN).items():
        for dim in meta["dimensions"]:
            by_dim.setdefault(dim.lower(), []).append(pid)
    assert constraints_for(CASE_IR["cases"][0], by_dim) == ["p_th_b04_combo"]
    # 大小写不同也要对上（case 用 D_TYPE / 策略写 D_type）
    assert constraints_for(CASE_IR["cases"][1], by_dim) == ["p_th_b02_random"]
    assert constraints_for(CASE_IR["cases"][2], by_dim) == []


def test_attach_constraints_writes_ids_and_registry():
    doc = attach_constraints(
        {"module": "demo", "cases": [dict(c) for c in CASE_IR["cases"]]}, PLAN)
    by_id = {c["id"]: c for c in doc["cases"]}
    assert by_id["CASE-D_DEP"]["constraints"] == ["p_th_b04_combo"]
    assert by_id["CASE-BEH"]["constraints"] == []          # 不猜
    assert doc["constraint_backing"]["p_th_b04_combo"]["backed"] is False


def test_without_plan_nothing_is_invented():
    doc = attach_constraints({"cases": [dict(CASE_IR["cases"][0])]}, {})
    assert "constraints" not in doc["cases"][0]
    assert "constraint_backing" not in doc


def test_contract_carries_constraints_into_the_hash():
    from src.tools.checking.verification_os.contract_model import contract_from_case_ir

    plain = {"module": "demo", "cases": [dict(CASE_IR["cases"][0])]}
    enriched = {"module": "demo", "cases": [dict(CASE_IR["cases"][0])]}
    attach_constraints(enriched, PLAN)
    a = contract_from_case_ir(plain)
    b = contract_from_case_ir(enriched)
    assert b.cases[0].constraints == ["p_th_b04_combo"]
    assert a.hash != b.hash          # 约束换版 → 契约哈希变


def test_enrich_reads_the_coverage_plan(tmp_path):
    import yaml

    from src.executors.verify.ir_artifacts import enrich_case_ir

    (tmp_path / "coverage").mkdir(parents=True)
    (tmp_path / "coverage" / "coverage_plan.yaml").write_text(
        yaml.safe_dump(PLAN, allow_unicode=True), encoding="utf-8")
    doc = enrich_case_ir(tmp_path, {"cases": [dict(CASE_IR["cases"][0])]})
    assert doc["cases"][0]["constraints"] == ["p_th_b04_combo"]


def test_case_view_joins_the_backing_registry():
    from src.tools.humanview.case_associate_view.builder import (
        _case_constraint_items,
    )

    items = _case_constraint_items({
        "constraint_backing": {
            "p_th_b04_combo": {"backed": False, "dimensions": ["D_dep"],
                               "reason": "空骨架"}},
        "cases": [{"id": "CASE-D_DEP", "constraints": ["p_th_b04_combo"]}],
    })
    assert items["CASE-D_DEP"][0]["backed"] is False
    assert items["CASE-D_DEP"][0]["dimensions"] == ["D_dep"]


def test_task_meta_keeps_constraint_ids(tmp_path):
    from src.tools.common.lib.case_meta import write_task_meta, read_task_meta

    write_task_meta(tmp_path, {"task": "t1", "test": "x_test", "seed": 1,
                               "case_ir_sha": "abc",
                               "constraint_ids": ["p_th_b04_combo"]})
    assert read_task_meta(tmp_path)["constraint_ids"] == ["p_th_b04_combo"]
