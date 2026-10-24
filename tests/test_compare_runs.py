"""运行对比 —— 「这次比上次差在哪、是谁改坏的」。

单次报告只回答"这次怎么样"。而"修好一个、改坏三个"这种事只有**两次并排**才
看得见 —— 它恰好是「可审计」这条定位最贵的那个问题，而数据每次运行都落了盘，
所以对比是纯对齐、不重跑。

与 `refactor_guard` 是同一个故事的人机两面：守卫是机器在改完 RTL 后自动比对
"原先通过的现在还过吗"，这里是**人**手动挑两次运行做同样的事。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.tools.flow.flow_tools.api import compare_runs


def _run(tmp_path, name: str, cases: dict, verdict="NEEDS_FIX",
         overall=90.0, functional=50.0, statement=88.0):
    """搭一个最小运行目录：根下的 report.json + 回归用例目录 + 覆盖率产物。"""
    root = tmp_path / name
    (root / "regression_run").mkdir(parents=True)
    (root / "sim" / "coverage").mkdir(parents=True)
    (root / "report.json").write_text(json.dumps(
        {"verdict": verdict, "signoff_status": "CONDITIONAL", "coverage": overall}),
        encoding="utf-8")
    (root / "sim" / "coverage" / "coverage_result.json").write_text(json.dumps(
        {"coverage": {"overall_pct": overall, "functional_pct": functional,
                      "statement_pct": statement}}), encoding="utf-8")
    for case, status in cases.items():
        d = root / "regression_run" / "build_build_dut" / f"test_{case}"
        d.mkdir(parents=True)
        # 框架落的是一手状态：`EMAN_BASE_STATUS=pass|fail|unknown`
        (d / "status.env").write_text(f"EMAN_BASE_STATUS={status}\n", encoding="utf-8")
    return root


class TestCaseLevelDiff:

    def test_newly_failing_is_the_headline(self, tmp_path):
        """**基线通过、现在没通过** —— 这一条是整页存在的理由，必须单独指出。"""
        a = _run(tmp_path, "run_a", {"t_pass": "pass", "t_keep": "pass"})
        b = _run(tmp_path, "run_b", {"t_pass": "fail", "t_keep": "pass"})
        out = compare_runs(str(a), str(b))
        assert out["cases"]["newly_failing"] == ["t_pass"]
        assert out["summary"]["newly_failing"] == 1
        assert any("变" in n for n in out["notes"])      # 有一句点名的说明

    def test_fixed_is_counted_separately(self, tmp_path):
        a = _run(tmp_path, "run_a", {"t_bad": "fail", "t_keep": "pass"})
        b = _run(tmp_path, "run_b", {"t_bad": "pass", "t_keep": "pass"})
        out = compare_runs(str(a), str(b))
        assert out["cases"]["fixed"] == ["t_bad"]
        assert out["cases"]["newly_failing"] == []

    def test_added_and_removed_cases(self, tmp_path):
        a = _run(tmp_path, "run_a", {"t_a": "pass", "t_gone": "pass"})
        b = _run(tmp_path, "run_b", {"t_a": "pass", "t_new": "pass"})
        out = compare_runs(str(a), str(b))
        assert out["cases"]["added"] == ["t_new"]
        assert out["cases"]["removed"] == ["t_gone"]
        assert out["cases"]["common"] == 1

    def test_an_added_case_that_fails_is_not_newly_failing(self, tmp_path):
        """新加的用例本来就不在基线里 —— 它变坏不叫"改坏了东西"。"""
        a = _run(tmp_path, "run_a", {"t_a": "pass"})
        b = _run(tmp_path, "run_b", {"t_a": "pass", "t_new": "fail"})
        out = compare_runs(str(a), str(b))
        assert out["cases"]["newly_failing"] == []
        assert out["cases"]["added"] == ["t_new"]


class TestCoverageDelta:

    def test_delta_is_current_minus_baseline(self, tmp_path):
        a = _run(tmp_path, "run_a", {"t": "pass"}, overall=94.0, functional=51.7)
        b = _run(tmp_path, "run_b", {"t": "pass"}, overall=88.0, functional=51.7)
        out = compare_runs(str(a), str(b))
        assert out["coverage"]["overall_pct"]["delta"] == -6.0
        assert out["coverage"]["functional_pct"]["delta"] == 0.0
        assert out["summary"]["coverage_delta"] == -6.0

    def test_missing_side_is_reported_not_silently_zero(self, tmp_path):
        """一侧没有回归产物 → 用例级对比不完整，**如实说**，别当"没有变化"。"""
        a = _run(tmp_path, "run_a", {"t": "pass"})
        b = tmp_path / "run_b"
        (b / "docs").mkdir(parents=True)
        (b / "report.json").write_text(json.dumps({"verdict": "READY", "coverage": 96.0}),
                                       encoding="utf-8")
        out = compare_runs(str(a), str(b))
        assert any("不完整" in n for n in out["notes"])
        assert out["cases"]["removed"] == ["t"]


class TestGuards:

    def test_same_run_twice_is_refused(self, tmp_path):
        a = _run(tmp_path, "run_a", {"t": "pass"})
        assert "同一个运行" in compare_runs(str(a), str(a))["error"]

    def test_missing_argument_is_refused(self, tmp_path):
        a = _run(tmp_path, "run_a", {"t": "pass"})
        assert "error" in compare_runs(str(a), "")

    def test_nonexistent_run_reports_which_side(self, tmp_path):
        a = _run(tmp_path, "run_a", {"t": "pass"})
        out = compare_runs(str(a), str(tmp_path / "nope"))
        assert out["side"] == "current" and "不存在" in out["error"]

    def test_verdict_change_is_surfaced(self, tmp_path):
        a = _run(tmp_path, "run_a", {"t": "pass"}, verdict="NEEDS_FIX")
        b = _run(tmp_path, "run_b", {"t": "pass"}, verdict="READY")
        out = compare_runs(str(a), str(b))
        assert out["verdict"]["changed"] is True
        assert any("判定" in n for n in out["notes"])
