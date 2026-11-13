"""接口契约的 SVA 判据：回归 PASS + 资产声明 + 进编译清单。"""
from __future__ import annotations

from src.ir_plane.vplan.evidence import _sva_reasons
from src.ir_plane.vplan.runtime.coverage_render import checker_rules


def test_cross_cycle_rule_is_not_emitted_to_env_checker():
    got = checker_rules(
        [{"name": "pulse", "expr": "a |=> b",
          "signals": [{"name": "a"}, {"name": "b"}]}],
        ["a", "b"])
    assert got["rules"] == []
    assert any("|=>" in reason for reason in got["skipped"])


def _entry(tmp_path, *, filelist: bool = True, regression: str = "PASS"):
    run = tmp_path / "run"
    (run / "sv" / "svas").mkdir(parents=True)
    (run / "inputs" / "filelists").mkdir(parents=True)
    (run / "sv" / "svas" / "npu_sched_assertions.sv").write_text(
        "module npu_sched_sva; endmodule\n", encoding="utf-8")
    work = run / "regression_run" / "p0" / "build_x" / "work"
    work.mkdir(parents=True)
    (work / "_info").write_text("vnpu_sched_sva\n", encoding="utf-8")
    if filelist:
        (run / "inputs" / "filelists" / "filelist.f").write_text(
            "D:/x/run/sv/svas/npu_sched_assertions.sv\n", encoding="utf-8")
    return {
        "run_dir": str(run),
        "regression_status": regression,
        "sva_assets": [{
            "artifact": "npu_sched_assertions",
            "path": "sv/svas/npu_sched_assertions.sv",
            "contract_ids": ["C-IF-GRP-GLSU"],
        }],
    }


def test_sva_contract_eligible_when_compiled_and_regression_passes(tmp_path):
    assert _sva_reasons(_entry(tmp_path), "C-IF-GRP-GLSU") == []


def test_sva_contract_blocks_when_asset_not_in_filelist(tmp_path):
    reasons = _sva_reasons(_entry(tmp_path, filelist=False), "C-IF-GRP-GLSU")
    assert any("compile filelist" in r for r in reasons)


def test_sva_contract_blocks_when_module_not_elaborated(tmp_path):
    entry = _entry(tmp_path)
    (tmp_path / "run" / "regression_run" / "p0" / "build_x" / "work" / "_info").write_text(
        "something_else\n", encoding="utf-8")
    reasons = _sva_reasons(entry, "C-IF-GRP-GLSU")
    assert any("not elaborated" in r for r in reasons)


def test_sva_contract_blocks_when_regression_fails(tmp_path):
    reasons = _sva_reasons(_entry(tmp_path, regression="FAIL"), "C-IF-GRP-GLSU")
    assert any("regression=FAIL" in r for r in reasons)


def test_sva_contract_blocks_when_no_asset_declares_it(tmp_path):
    entry = _entry(tmp_path)
    entry["sva_assets"] = []
    reasons = _sva_reasons(entry, "C-IF-GRP-GLSU")
    assert any("no SVA asset" in r for r in reasons)
