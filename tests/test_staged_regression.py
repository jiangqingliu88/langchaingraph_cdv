"""分级门控回归 —— 前一级不过就不进下一级。

`run_regression_staged` 只依赖 `self.run_regression` 与 `self.REGRESSION_STAGES`，
所以这里用桩对象直接喂每一级的返回值，不真起回归。
"""
from __future__ import annotations

from src.layers.l1_infrastructure.infrastructure import InfrastructureManager


class _Stub:
    REGRESSION_STAGES = InfrastructureManager.REGRESSION_STAGES
    _staged_summary = staticmethod(InfrastructureManager._staged_summary)

    def __init__(self, script):
        self.script = list(script)
        self.calls: list = []

    def run_regression(self, **kw):
        self.calls.append(kw.get("tags"))
        return self.script.pop(0)


def _ok():
    return {"passed": 3, "failed": 0, "unknown": 0, "total": 3}


def test_all_stages_pass():
    stub = _Stub([_ok() for _ in range(5)])
    res = InfrastructureManager.run_regression_staged(stub)
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
    res = InfrastructureManager.run_regression_staged(stub)
    assert res["blocked_at"] == "p1"
    assert stub.calls == ["loopback", "p0", "p1"]      # p2/p3 没跑
    assert [s["status"] for s in res["stages"]] == ["PASS", "PASS", "FAIL"]


def test_empty_tier_is_not_a_failure():
    """这一级没有用例（total=0）不算失败 —— 但也不该被读成"跑过了、过了"。"""
    stub = _Stub([{"passed": 0, "failed": 0, "unknown": 0, "total": 0}])
    res = InfrastructureManager.run_regression_staged(stub, stages=(("p2", "P2", "p2"),))
    assert res["status"] == "PASS" and res["stages"][0]["total"] == 0


def test_config_error_gates_with_its_own_message():
    stub = _Stub([{"status": "FAIL", "error": "regression.yaml not found"}])
    res = InfrastructureManager.run_regression_staged(stub)
    assert res["blocked_at"] == "loopback"
    assert "not found" in res["blocked_reason"]


def test_toplevel_aggregates_are_summed():
    """顶层 passed/failed 必须是各级之和 —— 只给 `stages` 会让上层读成"一条没跑"。"""
    stub = _Stub([_ok(), {"passed": 1, "failed": 1, "unknown": 0, "total": 2}])
    res = InfrastructureManager.run_regression_staged(stub)
    assert res["passed"] == 4 and res["failed"] == 1 and res["total"] == 5
