"""有效覆盖率必须按**配置的口径**算，不能把两个分母混在一起。

历史坑：`coverage_metric=functional` 时执行侧盯功能覆盖率（95.2%），而收敛
判据用的 `effective_coverage` 是覆盖地图**全部 bin** 的加权（代码 86% / toggle
更低混进来）—— 于是闭环盯着一个它的动作推不动的数，跑满轮次也收敛不了。

这里锁住：同一份覆盖地图，按 functional 口径算出来的有效覆盖率看的是
covergroup 那几个 bin，代码/toggle 的缺口不参与。
"""
from __future__ import annotations

import pytest

from src.knowledge.exclude_registry import (
    ExcludeRegistry, _bins_for_metric,
)

MAP = {
    "total": 89, "covered": 71, "coverage": 79.8,
    "bins": [
        {"type": "functional", "metric": "covergroup", "location": "functional.covergroup",
         "hit": False, "bins": 59, "covered": 56, "purpose": "functional"},
        {"type": "code", "metric": "branch", "location": "code.branch",
         "hit": False, "bins": 20, "covered": 10, "purpose": "protocol"},
        {"type": "toggle", "location": "sig[0]",
         "hit": False, "bins": 10, "covered": 5, "purpose": "corner"},
    ],
}


@pytest.fixture()
def registry(tmp_path):
    reg = ExcludeRegistry(tmp_path / "exclude.db")
    yield reg
    reg.close()


def test_functional_metric_ignores_code_and_toggle(registry):
    """功能口径 = 56/59 = 94.9%，不能被代码/toggle 的缺口拖到 79.8%。"""
    eff = registry.effective_coverage_from_map(MAP, metric="functional")
    assert eff["metric_filtered"] is True
    assert (eff["covered"], eff["total"]) == (56, 59)
    assert eff["effective_coverage"] == 94.9


def test_code_metric_uses_code_and_toggle_bins(registry):
    eff = registry.effective_coverage_from_map(MAP, metric="code")
    assert eff["metric_filtered"] is True
    assert (eff["covered"], eff["total"]) == (15, 30)
    assert eff["effective_coverage"] == 50.0


def test_no_metric_keeps_the_whole_map(registry):
    """不配置口径时行为不变 —— 整体加权，不能因为这次改动改了老语义。"""
    eff = registry.effective_coverage_from_map(MAP)
    assert eff["metric_filtered"] is False
    assert (eff["covered"], eff["total"]) == (71, 89)


def test_unknown_metric_falls_back_to_whole_map(registry):
    eff = registry.effective_coverage_from_map(MAP, metric="area")
    assert eff["metric_filtered"] is False
    assert eff["total"] == 89


def test_empty_metric_bins_fall_back_rather_than_read_zero(registry):
    """地图里一个功能 bin 都没有时，不能拿空集合算出 0%。"""
    code_only = {"bins": MAP["bins"][1:], "total": 30, "covered": 15,
                 "coverage": 50.0}
    eff = registry.effective_coverage_from_map(code_only, metric="functional")
    assert eff["metric_filtered"] is False
    assert eff["effective_coverage"] == 50.0


def test_bins_for_metric_helper():
    picked, filtered = _bins_for_metric(MAP["bins"], "functional")
    assert filtered and len(picked) == 1
    picked, filtered = _bins_for_metric(MAP["bins"], "")
    assert not filtered and len(picked) == 3
