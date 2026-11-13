"""Long-Horizon runtime：TaskStore / Planner / Subagent contract & isolation。"""
from __future__ import annotations

import json

from src.agent.runtime.harness import Harness, HarnessConfig
from src.agent.memory import TaskStore
from src.agent.planner import (
    acceptance_met, mark, new_plan, next_step, replan, should_replan,
)
from src.agent.collaboration import (
    ScopedTools, SubagentManager, build_contract,
)
from src.runtime.sandbox import SandboxTools
from src.runtime.workspace_manager import WorkspaceZones


def _zones(tmp_path):
    return WorkspaceZones.direct_mode(tmp_path)


def _finisher(payload):
    return json.dumps({"tool": "finish", "args": {"summary": payload["task"]}})


def test_task_store_persists_goal_plan_decisions(tmp_path):
    store = TaskStore(_zones(tmp_path), "T1").ensure()
    store.set_goal("跑通 npu_sched", ["回归 PASS", "覆盖率 >= 80"])
    store.set_plan(new_plan("跑通 npu_sched", [
        {"id": "S1", "title": "分析 spec"},
        {"id": "S2", "title": "跑回归", "depends_on": ["S1"]},
    ])["steps"])
    store.add_decision("使用 SVA + bind", reason="需要真 elaborate")
    store.add_blocker("EDA_MISSING")
    memory = store.render_memory()

    assert store.goal()["goal"] == "跑通 npu_sched"
    assert [s["id"] for s in store.plan()] == ["S1", "S2"]
    assert store.decisions()[0]["decision"].startswith("使用 SVA")
    assert "EDA_MISSING" in memory
    assert "S1" in memory and "S2" in memory


def test_planner_ready_replan_and_acceptance():
    plan = new_plan("goal", [
        {"id": "S1", "title": "a"},
        {"id": "S2", "title": "b", "depends_on": ["S1"]},
    ])
    first = next_step(plan)
    assert first["id"] == "S1"
    mark(plan, "S1", "done", "ok")
    assert next_step(plan)["id"] == "S2"
    triggered, reason = should_replan("regression_failed")
    assert triggered and "回归" in reason
    replan(plan, "regression_failed", [{"id": "S2a", "title": "归因"}])
    assert any(s["id"] == "S2a" for s in plan["steps"])
    assert acceptance_met({"target": 80}, {
        "regression": {"status": "PASS"},
        "coverage": {"functional_pct": 81},
    })["met"] is True
    assert acceptance_met({"target": 80}, {
        "regression": {"status": "FAIL"},
        "coverage": {"functional_pct": 60},
    })["met"] is False


def test_scoped_tools_deny_writes_outside_contract(tmp_path):
    zones = _zones(tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    tools = ScopedTools(
        SandboxTools(zones), zones,
        allowed_tools={"read_file", "write_file"},
        write_roots=[tmp_path / "allowed"])
    assert tools.call("write_file", {"path": "allowed/x.txt", "content": "ok"})["ok"]
    denied = tools.call("write_file", {"path": "other.txt", "content": "no"})
    assert denied["ok"] is False
    assert tools.call("read_file", {"path": "a.txt"})["ok"]


def test_subagent_manager_returns_structured_result(tmp_path):
    zones = _zones(tmp_path)
    steps = [
        {"tool": "write_file", "args": {
            "path": ".signoffai/subagents/t1/workspace/changed_files.json",
            "content": "{}"}},
        {"tool": "write_file", "args": {
            "path": ".signoffai/subagents/t1/workspace/compile.log",
            "content": "vlog ok"}},
        {"tool": "finish", "args": {"summary": "uvm generated"}},
    ]
    child_planner = lambda payload: json.dumps(steps.pop(0))  # noqa: E731
    parent = Harness(zones, config=HarnessConfig(emit_proposal=False,
                                                 project_root=str(tmp_path)),
                     planner=child_planner)
    manager = SubagentManager(parent)
    result = manager.spawn("uvm_engineer", "生成 UVM", task_id="t1")

    assert result["status"] == "COMPLETED"
    assert result["summary"] == "uvm generated"
    assert "changed_files.json" in result["artifacts"]
    assert result["validation"] == []
    assert (zones.harness_dir / "subagents/t1/result.json").is_file()
    assert parent.task_store.subagent_results()[0]["task_id"] == "t1"


def test_harness_task_store_recovers_across_instances(tmp_path):
    zones = _zones(tmp_path)
    config = HarnessConfig(emit_proposal=False, project_root=str(tmp_path))
    first = Harness(zones, config=config, planner=_finisher)
    result = first.run("分析 npu_sched")
    session_id = result["session"]["session_id"]

    second = Harness(zones, config=config, planner=_finisher,
                     session_id=session_id)
    assert second.task_store.goal()["goal"] == "分析 npu_sched"
    assert second.task_store.plan()
    assert second.task_store.render_memory().startswith("# TASK MEMORY")


def test_subagent_contract_validation():
    contract = build_contract("rtl_analyst", "分析接口驱动", task_id="r1")
    assert contract.validate() == []
    contract.objective = ""
    assert contract.validate()
