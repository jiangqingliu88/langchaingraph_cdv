"""粗连续奖励 —— 把“过/不过”拆成“往好的方向走了多少”。

钉的是：编译/回归/覆盖率三层能合成 0..1；空输入不崩；最弱层可指出。
"""
from __future__ import annotations

from src.ir_plane.decision.reward import compute_sim_reward


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


def test_custom_weights_are_normalised_and_used():
    from src.ir_plane.decision.reward import normalize_weights

    weights, issues = normalize_weights(
        {"compile": 1.0, "regression": 1.0, "coverage": 2.0})
    assert issues == []
    assert sum(weights.values()) == 1.0
    assert weights["coverage"] == 0.5

    r = compute_sim_reward(
        {"compile": "PASS", "passed": 1, "failed": 0, "total": 1},
        {"functional_pct": 0.0}, {}, {}, weights=weights)
    # compile=0.25、regression=0.25 都满分，coverage=0.5 为 0 → 0.5
    assert r["total"] == 0.5


def test_invalid_weights_fall_back_and_say_why():
    from src.ir_plane.decision.reward import WEIGHTS

    r = compute_sim_reward({}, {}, {}, {},
                           weights={"compile": -1, "regression": 1, "coverage": 1})
    assert r["weights"] == WEIGHTS
    assert any("非负" in i for i in r["weight_issues"])


def test_missing_weight_key_uses_default_and_reports():
    from src.ir_plane.decision.reward import WEIGHTS

    r = compute_sim_reward({}, {}, {}, {}, weights={"compile": 0.5})
    assert "缺少 regression" in " ".join(r["weight_issues"])
    # 缺项补默认后**整体归一**（0.5 + 0.35 + 0.40 = 1.25）
    assert r["weights"]["regression"] == round(WEIGHTS["regression"] / 1.25, 6)
    assert sum(r["weights"].values()) == 1.0


def test_weights_from_policy_accepts_raw_or_loaded_policy():
    from src.ir_plane.decision.reward import weights_from_policy

    raw = {"reward_weights": {"compile": 1, "regression": 1, "coverage": 2}}
    assert weights_from_policy(raw) == raw["reward_weights"]
    assert weights_from_policy({"raw": raw}) == raw["reward_weights"]
    assert weights_from_policy({}) is None


def test_policy_file_reward_weights_are_discovered(tmp_path):
    """`reward_weights` 落在模块策略文件里就能被读出来（不用改代码）。"""
    from src.orchestration_plane.l2.evidence.signoff_package import load_policy

    run = tmp_path / "run_w"
    run.mkdir()
    (run / "signoff_policy.yaml").write_text(
        "require_baseline: true\n"
        "reward_weights:\n"
        "  compile: 0.2\n"
        "  regression: 0.3\n"
        "  coverage: 0.5\n",
        encoding="utf-8")
    policy, source = load_policy(run, "whatever")
    assert source.endswith("signoff_policy.yaml")
    from src.ir_plane.decision.reward import weights_from_policy
    assert weights_from_policy(policy) == {
        "compile": 0.2, "regression": 0.3, "coverage": 0.5}
