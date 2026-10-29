"""粗连续奖励 —— 把“过/不过”拆成“往好的方向走了多少”。

钉的是：编译/回归/覆盖率三层能合成 0..1；空输入不崩；最弱层可指出。
"""
from __future__ import annotations

from src.layers.l3_decision.reward import compute_sim_reward


def test_all_good_is_near_one():
    r = compute_sim_reward(
        {"compile": "PASS", "passed": 10, "failed": 0, "total": 10},
        {"functional_pct": 100.0},
        {"counts": {"HIT": 10}, "total": 10},
        {"verdict": "DIVERSE"},
    )
    assert r["schema"] == "sim_reward_v1"
    assert r["total"] > 0.95
    assert r["weakest"] in {"compile", "regression", "coverage"}


def test_compile_failure_is_not_all_or_nothing():
    """编译失败但错误少 → 仍然给出方向（>0），不是 0。"""
    r = compute_sim_reward(
        {"compile": "FAIL", "stderr": "Errors: 2, Warnings: 1",
         "passed": 0, "failed": 1, "total": 1},
        {"functional_pct": 0.0}, {}, {})
    assert 0.0 < r["components"]["compile"]["score"] < 0.5
    assert r["components"]["compile"]["errors"] == 2
    # 回归 0 通过、覆盖率 0 → 最弱层是 regression（并列时按字典顺序取第一个 0 分层）
    assert r["weakest"] == "regression"


def test_plateau_reward_tracks_tp_hits_and_seed():
    base = compute_sim_reward(
        {"compile": "PASS", "passed": 10, "failed": 0, "total": 10},
        {"functional_pct": 80.0},
        {"counts": {"HIT": 5}, "total": 10},
        {"verdict": "IDENTICAL"},
    )
    better = compute_sim_reward(
        {"compile": "PASS", "passed": 10, "failed": 0, "total": 10},
        {"functional_pct": 80.0},
        {"counts": {"HIT": 9}, "total": 10},
        {"verdict": "DIVERSE"},
    )
    assert better["total"] > base["total"]


def test_empty_inputs_are_safe():
    r = compute_sim_reward({}, {}, {}, {})
    assert r["total"] == 0.0
    assert r["weakest"]
