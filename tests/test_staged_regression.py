"""分级门控回归 —— 前一级不过就不进下一级。

`run_regression_staged` 只依赖 `self.run_regression` 与 `self.REGRESSION_STAGES`，
所以这里用桩对象直接喂每一级的返回值，不真起回归。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.layers.l1_infrastructure.infrastructure import InfrastructureManager


class _Stub:
    REGRESSION_STAGES = InfrastructureManager.REGRESSION_STAGES
    _staged_summary = staticmethod(InfrastructureManager._staged_summary)
    _stage_parts = staticmethod(InfrastructureManager._stage_parts)

    def __init__(self, script, approvals=None):
        self.script = list(script)
        self.calls: list = []
        # 谁批过了：{"loopback": {"approver": "...", ...}}；缺省 = 一个都没批
        self.approvals = dict(approvals or {})

    def run_regression(self, **kw):
        self.calls.append(kw.get("tags"))
        return self.script.pop(0)

    def read_stage_approval(self, after, stage=None):
        return self.approvals.get(after)

    def _write_staged_summary(self, summary):
        self.written = summary          # 桩：只记下来，不落盘


def _ok():
    return {"passed": 3, "failed": 0, "unknown": 0, "total": 3}


def test_all_stages_pass():
    """`auto_approve=True` 跳过人工节点 —— 纯门控逻辑的回归。"""
    stub = _Stub([_ok() for _ in range(5)])
    res = InfrastructureManager.run_regression_staged(stub, auto_approve=True)
    assert res["status"] == "PASS" and res["blocked_at"] == ""
    assert [s["name"] for s in res["stages"]] == ["loopback", "p0", "p1", "p2", "p3"]
    assert stub.calls == ["loopback", "p0", "p1", "p2", "p3"]


def test_failure_gates_the_next_stage():
    """loopback 挂 → 连 p0 都不进（这是用户要的那道硬门）。"""
    stub = _Stub([{"passed": 0, "failed": 2, "unknown": 0, "total": 2}])
    res = InfrastructureManager.run_regression_staged(stub)
    assert res["status"] == "FAIL" and res["blocked_at"] == "loopback"
    assert stub.calls == ["loopback"]                  # p0 起没跑


def test_unknown_also_gates():
    """`unknown`（编不过 / 挂死）同样拦 —— 没出结论的不放行。"""
    stub = _Stub([{"passed": 1, "failed": 0, "unknown": 1, "total": 2}])
    res = InfrastructureManager.run_regression_staged(stub)
    assert res["blocked_at"] == "loopback"
    assert "unknown=1" in res["blocked_reason"]


def test_stops_at_the_right_tier_midway():
    stub = _Stub([_ok(), _ok(), {"passed": 1, "failed": 1, "unknown": 0, "total": 2}])
    res = InfrastructureManager.run_regression_staged(stub, auto_approve=True)
    assert res["blocked_at"] == "p1"
    assert stub.calls == ["loopback", "p0", "p1"]      # p2/p3 没跑
    assert [s["status"] for s in res["stages"]] == ["PASS", "PASS", "FAIL"]


def test_empty_tier_blocks_instead_of_reporting_green():
    """一条用例都没匹配到（total=0）**绝不能判 PASS**：那是假绿 ——
    门看着在、其实什么都没拦。实测踩过：五级全 total=0 却整轮报"每级都过"。"""
    stub = _Stub([{"passed": 0, "failed": 0, "unknown": 0, "total": 0}])
    res = InfrastructureManager.run_regression_staged(stub, stages=(("p2", "P2", "p2"),))
    assert res["status"] == "FAIL"
    assert res["blocked_at"] == "p2"
    assert res["stages"][0]["status"] == "EMPTY"
    assert "一条都没跑" in res["blocked_reason"]


def test_config_error_gates_with_its_own_message():
    stub = _Stub([{"status": "FAIL", "error": "regression.yaml not found"}])
    res = InfrastructureManager.run_regression_staged(stub)
    assert res["blocked_at"] == "loopback"
    assert "not found" in res["blocked_reason"]


def test_toplevel_aggregates_are_summed():
    """顶层 passed/failed 必须是各级之和 —— 只给 `stages` 会让上层读成"一条没跑"。"""
    stub = _Stub([_ok(), {"passed": 1, "failed": 1, "unknown": 0, "total": 2}])
    res = InfrastructureManager.run_regression_staged(stub, auto_approve=True)
    assert res["passed"] == 4 and res["failed"] == 1 and res["total"] == 5


def test_summary_is_persisted():
    """分级结果必须落盘 —— 每级会 rmtree 上一次的 regression_run，
    不落盘就只剩最后一级的状态，loopback 那级事后无从复查。"""
    stub = _Stub([{"passed": 0, "failed": 1, "unknown": 0, "total": 1}])
    InfrastructureManager.run_regression_staged(stub)
    assert stub.written["blocked_at"] == "loopback"
    assert stub.written["stages"][0]["failed"] == 1


# ── 人工节点（loopback 全过之后必须有人放行才进 p0）──────────────

def test_manual_gate_stops_before_p0():
    """loopback 全过也**不能**自己往下走 —— 停在人工节点等放行。"""
    stub = _Stub([_ok() for _ in range(5)])
    res = InfrastructureManager.run_regression_staged(stub)
    assert res["status"] == "WAITING_APPROVAL" and res["blocked_at"] == "loopback"
    assert stub.calls == ["loopback"]                  # p0 起没跑
    assert res["awaiting"] == {"after": "loopback", "next": "p0",
                               "next_label": "P0 功能", "hint": res["awaiting"]["hint"]}
    assert "人工放行" in res["blocked_reason"]
    assert stub.written["status"] == "WAITING_APPROVAL"    # 也要落盘


def test_manual_gate_proceeds_once_approved():
    """有放行记录 → 直接从 p0 继续。"""
    stub = _Stub([_ok() for _ in range(5)],
                 approvals={"loopback": {"approver": "jiang", "at": "2026-10-07"}})
    res = InfrastructureManager.run_regression_staged(stub)
    assert res["status"] == "PASS"
    assert stub.calls == ["loopback", "p0", "p1", "p2", "p3"]


def test_manual_gate_only_applies_to_the_configured_stage():
    """p0 过了**不该**再拦一次 —— 人工节点只配在 loopback 之后。"""
    stub = _Stub([_ok(), _ok(), {"passed": 1, "failed": 1, "unknown": 0, "total": 2}],
                 approvals={"loopback": {"approver": "jiang"}})
    res = InfrastructureManager.run_regression_staged(stub)
    assert res["status"] == "FAIL" and res["blocked_at"] == "p1"
    assert stub.calls == ["loopback", "p0", "p1"]


def test_approval_is_bound_to_evidence(tmp_path):
    """放行绑的是**那一份结果**：记录里的 total/passed/failed 变了就不认。

    没有这条，改完 TB 重跑（loopback 从 3 条变 20 条）还会拿旧批条自动放行 ——
    批的就不再是"这次看到的这份证据"了。
    """
    infra = InfrastructureManager(tmp_path)
    (tmp_path / "regression_stages.json").write_text(
        json.dumps({"stages": [{"name": "loopback", "status": "PASS",
                                "total": 3, "passed": 3, "failed": 0, "unknown": 0}]}),
        encoding="utf-8")

    entry = infra.approve_stage("loopback", approver="jiang", note="环境自洽")
    assert entry["approver"] == "jiang" and entry["next"] == "p0"
    assert entry["evidence"]["passed"] == 3
    # 证据一致 → 认
    assert infra.read_stage_approval(
        "loopback", {"name": "loopback", "status": "PASS",
                     "total": 3, "passed": 3, "failed": 0, "unknown": 0}) is not None
    # 证据变了（重跑后条数不同）→ 不认，得重新放行
    assert infra.read_stage_approval(
        "loopback", {"name": "loopback", "status": "PASS",
                     "total": 20, "passed": 20, "failed": 0, "unknown": 0}) is None
    # 没批过的级 → 不认
    assert infra.read_stage_approval("p0", None) is None


def test_approval_requires_an_approver(tmp_path):
    """没有审批人的"已审批"不算审计证据。"""
    infra = InfrastructureManager(tmp_path)
    with pytest.raises(ValueError):
        infra.approve_stage("loopback", approver="  ")


# ── 工作台「人工节点」开关 ::: 工具栏 → .signoffai/manual_gate.json → 运行 ──

def test_manual_gate_store_defaults_to_on(tmp_path, monkeypatch):
    """默认**开** —— 门是默认该在的；默认关等于这个机制默认不存在。

    读不到 / 写坏了也回落 `True`：治理不能因为一份记忆文件不在就静默失效。
    """
    from src.workbench import manual_gate as ui

    monkeypatch.setattr(ui, "STORE", tmp_path / "manual_gate.json")
    assert ui.load() is True                       # 没存过
    ui.save(False)
    assert ui.load() is False                      # 存过就认
    (tmp_path / "manual_gate.json").write_text("{ 坏 json", encoding="utf-8")
    assert ui.load() is True                       # 写坏了 → 回到默认开


def test_manual_gate_store_is_user_level_not_project_level():
    """**全局开关**：记在用户级 `~/.signoffai/`，不跟着工作目录走。

    和「仿真业务」刻意不同 —— 那个是项目的事（低功耗开 `upf`、教学开 `wave`），
    落在工作目录下的 `.signoffai/`；这个开关是**操作者**的事（「我现在要不要被
    拦一下」），换项目目录人还是同一个人、答案还是同一个。
    """
    from src.workbench import manual_gate as ui

    assert ui.STORE == Path.home() / ".signoffai" / "manual_gate.json"
    assert not ui.STORE.is_relative_to(Path.cwd())     # 不是项目级


def test_the_ops_agent_turns_the_switch_into_auto_approve(monkeypatch):
    """开关关掉 = `run_regression_staged(auto_approve=True)`；开 = 不传（缺省拦截）。

    这条是"界面开关真有作用"的落点 —— 前面那条链（RunRequest → PipelineState →
    n_ops 的 params）只是搬运，**最终得有人把它翻译成 auto_approve**。
    """
    import asyncio

    from src.executors.ops import main as ops_main

    seen = {}

    def fake_staged(self, **kw):
        seen.update(kw)
        return {"status": "PASS", "passed": 1, "total": 1}

    monkeypatch.setattr(InfrastructureManager, "run_regression_staged", fake_staged)
    monkeypatch.setattr("shutil.which", lambda _t: "/usr/bin/mock")

    def run(manual_gate):
        seen.clear()
        agent = ops_main.OpsExecutor() if hasattr(ops_main, "OpsExecutor") else None
        assert agent is not None, "ops agent 类名变了，改这条测试"
        asyncio.run(agent.execute_task(
            {"output_dir": "out_x", "params": {"manual_gate": manual_gate}}))
        return seen.get("auto_approve")

    assert run(False) is True            # 关（放行）→ auto_approve
    assert run(True) is False            # 开（拦截）→ 不自动放行


def test_the_gate_is_declared_on_the_stage_not_in_a_side_table():
    """门是**这一级的属性**，不是另写一张 `{name: next}` 的表。

    另写一张表的问题不是啰嗦，是**会静默失配**：把 `p0` 改个名，表里那个键
    对不上，门看着还在、其实谁都没拦，而且不报错。所以这里断言两件事：
    门的取值跟着级走；由它推出的映射与声明一致。
    """
    parts = InfrastructureManager._stage_parts
    assert [(p[0], p[3]) for p in
            (parts(s) for s in InfrastructureManager.REGRESSION_STAGES)] == [
        ("loopback", True), ("p0", False), ("p1", False),
        ("p2", False), ("p3", False)]
    assert InfrastructureManager.regression_manual_gates() == {"loopback": "p0"}
    # 换一套级，映射跟着变 —— 派生而非另写
    assert InfrastructureManager.regression_manual_gates(
        (("a", "A", "a", True), ("b", "B", "b", False), ("c", "C", "c", True),
         ("d", "D", "d", False))) == {"a": "b", "c": "d"}


def test_stage_tuples_without_the_gate_flag_are_still_valid():
    """三元组（老调用方/老测试的写法）仍然合法，缺省 = 不设人工节点。

    `run_regression_staged(stages=...)` 是公开参数，收窄了就是静默改契约。
    """
    stub = _Stub([_ok() for _ in range(3)])
    res = InfrastructureManager.run_regression_staged(
        stub, stages=(("a", "A", "a"), ("b", "B", "b"), ("c", "C", "c")))
    assert res["status"] == "PASS"          # 没人拦
    assert stub.calls == ["a", "b", "c"]


def test_closed_loop_stops_at_the_manual_node():
    """闭环撞上人工节点要**停下来交棒**，不能当成普通失败再转下一轮。

    实测踩过：不拦的话每轮都停在同一个放行点、每轮都被判成 ops 失败，
    空烧 `max_rounds` 轮（5 轮 loopback 跑完，P0 一次都没跑过）。
    """
    from src.layers.l2_orchestration.graph import r_coverage
    from src.layers.l2_orchestration.state import PipelineState

    assert r_coverage(PipelineState(run_id="r", output_root="x",
                                    awaiting_approval=True)) == "awaiting_approval"
    # 没有这个标志时完全不受影响
    assert r_coverage(PipelineState(run_id="r", output_root="x")) == "run_coverage"
    # EDA 缺失优先级更高（真环境问题先报）
    assert r_coverage(PipelineState(run_id="r", output_root="x",
                                    awaiting_approval=True,
                                    eda_blocked=True)) == "eda_missing"


def test_incremental_filter_does_not_skip_loopback_self_check():
    """增量过滤只作用于 DUT 级；loopback 是环境自检，永远不被筛掉。"""
    calls = []

    class _S(_Stub):
        def run_regression(self, **kw):
            calls.append(kw.get("tests"))
            return _ok()

    stub = _S([_ok() for _ in range(5)])
    res = InfrastructureManager.run_regression_staged(
        stub, auto_approve=True, tests="^(alu_test)$")
    assert res["status"] == "PASS"
    assert calls[0] is None                 # loopback
    assert all(c == "^(alu_test)$" for c in calls[1:])
