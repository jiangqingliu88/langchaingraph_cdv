"""覆盖地图的**口径** —— 它是收敛判定的那个数，单位错了就永远收敛不了。

原来 `coverage` 是「7 个条目里干净几个」的**计数**（代码 6 个 metric + 功能 1 个），
却被拿去跟"覆盖率目标 95%"比：实测真实覆盖率 96% 的运行时，这个数读作
**14.3%**（7 个里干净 1 个）→ `converged` 永远为 NO → 签核永远过不了。

现在 `coverage` 是**按 bin 加权**的百分比（Σcovered/Σbins），而"每个 metric 都盖满"
这个更严格的信号保留在 `metrics_clean` 上（当初用条目计数就是为了不被空数据骗，
那个用意不该丢）。
"""
from __future__ import annotations

from src.orchestration_plane.l2.coverage_map import CoverageMap


def _cov(**kw):
    base = {"line_pct": 0, "line_bins": 0, "line_misses": 0,
            "statement_pct": 0, "statement_bins": 0, "statement_misses": 0,
            "branch_pct": 0, "branch_bins": 0, "branch_misses": 0,
            "condition_pct": 0, "condition_bins": 0, "condition_misses": 0,
            "toggle_pct": 0, "toggle_bins": 0, "toggle_misses": 0,
            "fsm_pct": 0, "fsm_bins": 0, "fsm_misses": 0,
            "functional_pct": 0}
    base.update(kw)
    return base


class TestCoverageIsAWeightedPercentage:

    def test_is_bin_weighted_not_an_entry_count(self):
        """96% 的运行时就得读出接近 96%，不能是 "7 个里干净 1 个" 的 14.3%。"""
        cov = _cov(statement_pct=88.57, statement_bins=35, statement_misses=4,
                   branch_pct=87.5, branch_bins=8, branch_misses=1,
                   functional_pct=51.72)
        m = CoverageMap().build(cov, [], {"bin_total": 29, "bin_hits": 15})
        # (31 + 7 + 15) / (35 + 8 + 29) = 53/72
        assert m["total"] == 72 and m["covered"] == 53
        assert m["coverage"] == 73.6

    def test_empty_data_is_not_counted_as_covered(self):
        """空数据（0 个 bin）既不算命中、也不进分母 —— 这是原来那个假覆盖率的病根。

        实测历史：只看 `misses == 0` 的话，没收集到的 metric 会被当成"全覆盖"，
        造出 6/7 = 85.7% 的假覆盖率。
        """
        m = CoverageMap().build(_cov(), [], {})
        assert m["total"] == 0
        assert m["coverage"] == 0.0
        assert m["metrics_clean"] is False

    def test_metrics_clean_keeps_the_strict_signal(self):
        """全都盖满才是 True；只要有 bin 没中就是 False。"""
        clean = CoverageMap().build(
            _cov(statement_pct=100, statement_bins=10, statement_misses=0,
                 functional_pct=100), [], {"bin_total": 5, "bin_hits": 5})
        assert clean["metrics_clean"] is True
        assert clean["coverage"] == 100.0

        partial = CoverageMap().build(
            _cov(statement_pct=90, statement_bins=10, statement_misses=1,
                 functional_pct=100), [], {"bin_total": 5, "bin_hits": 5})
        assert partial["metrics_clean"] is False
        assert partial["coverage"] == 93.3

    def test_functional_contributes_its_bins(self):
        """功能覆盖率按 covergroup bin 加权，不再压成一个"100% 才算命中"的布尔。"""
        a = CoverageMap().build(_cov(functional_pct=50), [], {"bin_total": 20, "bin_hits": 10})
        b = CoverageMap().build(_cov(functional_pct=50), [], {"bin_total": 200, "bin_hits": 100})
        assert a["total"] == 20 and b["total"] == 200      # 分母跟着 bin 数走
        assert a["coverage"] == b["coverage"] == 50.0
