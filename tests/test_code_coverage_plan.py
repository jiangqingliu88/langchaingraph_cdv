"""DUT 代码覆盖率的计划口径 —— 排除 loopback、正确生成 merge spec。"""
from __future__ import annotations

from pathlib import Path

from src.runtime_plane.tools.common.lib.code_coverage_plan import dut_stores, store_specs


def _store(root: Path, rel: str, data_name: str = "t1.data"):
    store = root / rel
    store.mkdir(parents=True)
    (store / "questa.db").write_text("x", encoding="utf-8")
    (store / data_name).write_text("x", encoding="utf-8")
    return store


def test_dut_stores_excludes_loopback(tmp_path):
    _store(tmp_path, "regression_run/p0/build/test_a/cov/t1")
    _store(tmp_path, "regression_run/p3/build/test_b/cov/t2")
    _store(tmp_path, "regression_run/loopback/build/test_lb/cov/lb")
    stores = dut_stores(tmp_path)
    assert len(stores) == 2
    assert all("loopback" not in p.parts for p in stores)


def test_store_specs_uses_test_name_and_handles_null(tmp_path):
    _store(tmp_path, "regression_run/p0/build/test_a/cov/t1", "t1.data")
    _store(tmp_path, "regression_run/p0/build/test_b/cov/(null)", "(null).data")
    specs = store_specs(tmp_path, dut_stores(tmp_path))
    assert any(s.endswith(":t1") for s in specs)
    assert any(s.endswith("cov/(null)") for s in specs)


def test_no_stores_is_empty(tmp_path):
    assert dut_stores(tmp_path) == []
