"""逐用例取证 + 波形可追溯 —— 签核口径从「合并库里有」改成「这条用例证明」。

钉住的契约（见 docs/design/case_coverage_and_wave_traceability.md）：

  · `task_meta.json` 是用例身份（task / test / seed / stage / tp_ids）的落点，
    文件缺失时按同一套规则从目录名 + sim.sh 推导；
  · `coverage/case_cov/<stage>/<task>.json` 只统计这条用例自己的 ucdb；
  · `coverage/case_tp.json` 让「用例 → 测试点」正反都能查；
  · `waves/manifest.json` 让「测试点 → 波形」可反查；
  · `SIGNED_OFF` 要求同一条用例、同一次 seed 同时满足：仓全中 + illegal 干净
    + UVM_ERROR=0 + SCB mismatched=0 + 断言不触发 + 有波形。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.tools.common.lib import case_meta


VCOVER = """\
Coverage Report by instance with details

 TYPE /p/npu_sched_env_pkg/npu_sched_env_coverage/cg_dut
                                                       72.63%        100          -    Uncovered
    Coverpoint cp_queue_level                         100.00%        100          -    Covered
        illegal_bin illegal_over                            0                     -    ZERO
        bin empty                                           8          1          -    Covered
    Coverpoint cp_instr_type                           75.00%        100          -    Uncovered
        bin mac                                            12          1          -    Covered
COVERGROUP COVERAGE:
 TYPE /p/npu_sched_env_pkg/npu_sched_env_coverage/cg_dut
                                                       72.63%        100          -    Uncovered
"""

VCOVER_ILLEGAL = VCOVER.replace(
    "illegal_bin illegal_over                            0",
    "illegal_bin illegal_over                            3")


def _task_dir(run: Path, *, task="tp_a_seed_6001", test="env_attr_test",
              stage="p1", tp_ids=("TP-1",), wave=True, log=True,
              meta=True) -> Path:
    d = run / "regression_run" / stage / "build_b_dut" / f"test_{task}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "cov" / test).mkdir(parents=True, exist_ok=True)
    (d / "cov" / test / "questa.db").write_bytes(b"fake-index")
    if meta:
        import json
        (d / "task_meta.json").write_text(json.dumps({
            "task": task, "test": test, "seed": 6001, "stage": stage,
            "build": "b_dut", "tp_ids": list(tp_ids),
        }), encoding="utf-8")
    # sim.sh 是 `+UVM_TESTNAME` 的权威来源（目录名只给任务名）
    (d / "sim.sh").write_text(
        f"vsim -c top +UVM_TESTNAME={test} +ntb_random_seed=6001\n",
        encoding="utf-8")
    if log:
        (d / "sim_vsim.log").write_text(
            "UVM_ERROR :    0\nUVM_FATAL :    0\n"
            "[SCB_DUT] total=40 matched=40 mismatched=0\n",
            encoding="utf-8")
    if wave:
        (d / "waves").mkdir(exist_ok=True)
        (d / "waves" / f"{task.split('_seed_')[0]}.db").write_bytes(b"wavedb")
    return d


def _run_with_tp(tmp_path: Path, **tp):
    run = tmp_path / "run"
    rows = [{
        "tp_id": "TP-1", "coverpoint": "cp_queue_level", "bin": "empty",
        "dimension": "queue", "value": "empty",
        "realization": {"kind": "stimulus"},
        "execution": {"test": "env_attr_test", "stage": "p1", "seeds": [6001]},
        "observe_only": False,
    }]
    rows[0].update(tp)
    (run / "coverage").mkdir(parents=True, exist_ok=True)
    (run / "coverage" / "testpoints.yaml").write_text(
        yaml.safe_dump({"testpoints": rows}, allow_unicode=True), encoding="utf-8")
    return run


@pytest.fixture
def fake_vcover(monkeypatch):
    from src.layers.l3_decision.evidence import case_cov as cc
    from src.layers.l3_decision.evidence import cov_api
    from src.tools.common.lib import collect_real_coverage as crc

    def fake_materialize(db, force=False):
        return str(db), ""

    monkeypatch.setattr(cov_api, "materialize_ucdb", fake_materialize)
    monkeypatch.setattr(cc, "_vcover_cvg_report", lambda ucdb: (VCOVER, ""))
    # 测试仍通过 `collect_real_coverage` 的门面调用（公开入口不变）。
    return crc


# ────────────────────────────────────────────────────────────────
# 身份推导
# ────────────────────────────────────────────────────────────────

class TestTaskMeta:
    def test_reads_written_meta(self, tmp_path):
        d = _task_dir(tmp_path, task="tp_x_seed_6001", test="env_attr_test",
                      stage="p1", tp_ids=["TP-X"])
        meta = case_meta.read_task_meta(d)
        assert meta["task"] == "tp_x_seed_6001"
        assert meta["test"] == "env_attr_test"
        assert meta["seed"] == 6001
        assert meta["stage"] == "p1"
        assert meta["tp_ids"] == ["TP-X"]
        assert meta["source"] == "meta"

    def test_derives_from_dir_and_sim_sh_when_meta_missing(self, tmp_path):
        """老目录没有 task_meta —— 目录名给 task/seed、sim.sh 给 UVM 类名。"""
        d = _task_dir(tmp_path, task="tp_a_seed_2222", test="env_base_test",
                      stage="p2", meta=False)
        meta = case_meta.read_task_meta(d)
        assert meta["task"] == "tp_a_seed_2222"
        assert meta["test_name"] == "tp_a"
        assert meta["seed"] == 2222
        assert meta["test"] == "env_base_test"
        assert meta["stage"] == "p2"
        assert meta["source"] == "derived"

    def test_tp_ids_from_tags(self):
        assert case_meta.tp_ids_from_tags(["p1", "tp", "TP-A", "TP-B", "tp_NP"]) == \
            ["TP-A", "TP-B"]


class TestTaskMetaGeneration:
    def test_shell_generator_writes_identity_with_tp_ids(self, tmp_path):
        """回归目录生成时就把「用例 → 测试点」写下来，而不是事后猜。

        归属两路合流：tag 里的 `TP-*` + `execution.test` 反查（后者让批次
        用例也能挂上它实际覆盖的测试点）。
        """
        import yaml
        from src.layers.l2_orchestration.regression_tools.regression_framework.generators.shell import (
            ShellGenerator)

        run = tmp_path / "run"
        (run / "coverage").mkdir(parents=True)
        (run / "coverage" / "testpoints.yaml").write_text(yaml.safe_dump({
            "testpoints": [
                {"tp_id": "TP-B",
                 "execution": {"test": "env_batch_test", "stage": "p1"}},
            ]}), encoding="utf-8")
        cfg = {
            "variables": {"SEED": 1},
            "builds": [{"name": "b1", "top": "tb", "run_cmd": "echo build"}],
            "tests": [
                {"name": "tp_a", "build": "b1", "tags": ["p1", "TP-A"],
                 "run_cmd": "vsim tb +UVM_TESTNAME=env_attr_test"},
                {"name": "batch_x", "build": "b1", "tags": ["p1", "batch"],
                 "run_cmd": "vsim tb +UVM_TESTNAME=env_batch_test"},
            ],
            "settings": {},
        }
        ShellGenerator().generate(cfg, str(run / "regression_run" / "p1"),
                                  "mock", run_root=run)

        base = run / "regression_run" / "p1" / "build_b1"
        a = case_meta.read_task_meta(base / "test_tp_a")
        b = case_meta.read_task_meta(base / "test_batch_x")
        assert a["test"] == "env_attr_test"
        assert a["tp_ids"] == ["TP-A"]
        assert a["stage"] == "p1"
        assert b["test"] == "env_batch_test"
        assert b["tp_ids"] == ["TP-B"]          # 按 execution.test 反查得来


# ────────────────────────────────────────────────────────────────
# 逐用例取证
# ────────────────────────────────────────────────────────────────

class TestCaseCov:
    def test_clean_case_signs_the_tp_off(self, tmp_path, fake_vcover):
        run = _run_with_tp(tmp_path)
        _task_dir(run, task="tp_a_seed_6001", tp_ids=["TP-1"])

        idx = fake_vcover._case_cov_matrix(run)

        assert idx["counts"]["signed_off"] == 1
        assert idx["by_tp"]["TP-1"]["signed_off"] is True
        assert idx["by_tp"]["TP-1"]["signed_off_by"] == "tp_a_seed_6001@6001"
        assert (run / "coverage" / "case_tp.json").is_file()
        case_file = (run / "coverage" / "case_cov" / "p1" /
                     "tp_a_seed_6001.json")
        assert case_file.is_file()
        rec = yaml.safe_load(case_file.read_text(encoding="utf-8"))
        assert rec["tp"][0]["status"] == "SIGNED_OFF"
        assert rec["tp"][0]["hits"] == {"empty": 8}

    def test_illegal_bin_vetoes_an_otherwise_green_case(
            self, tmp_path, fake_vcover, monkeypatch):
        from src.layers.l3_decision.evidence import case_cov as cc
        run = _run_with_tp(tmp_path)
        _task_dir(run, task="tp_a_seed_6001", tp_ids=["TP-1"])
        monkeypatch.setattr(cc, "_vcover_cvg_report",
                            lambda ucdb: (VCOVER_ILLEGAL, ""))

        idx = fake_vcover._case_cov_matrix(run)

        s = idx["by_tp"]["TP-1"]
        assert s["signed_off"] is False
        assert "illegal_bin" in s["reasons"]
        assert s["cases"][0]["status"] == "UNSIGNED"

    def test_missing_wave_blocks_signoff(self, tmp_path, fake_vcover):
        """波形是签核材料的一部分 —— 没有它就反查不到"这条用例证明了哪个点"。"""
        run = _run_with_tp(tmp_path)
        _task_dir(run, task="tp_a_seed_6001", tp_ids=["TP-1"], wave=False)

        idx = fake_vcover._case_cov_matrix(run, require_wave=True)

        assert idx["by_tp"]["TP-1"]["signed_off"] is False
        assert "wave_missing" in idx["by_tp"]["TP-1"]["reasons"]

    def test_wave_can_be_optional(self, tmp_path, fake_vcover):
        run = _run_with_tp(tmp_path)
        _task_dir(run, task="tp_a_seed_6001", tp_ids=["TP-1"], wave=False)

        idx = fake_vcover._case_cov_matrix(run, require_wave=False)

        assert idx["by_tp"]["TP-1"]["signed_off"] is True

    def test_scb_evidence_is_required(self, tmp_path, fake_vcover):
        """没有 `mismatched=0` = 没有比对结论 —— "没报错"不等于"验过了"。"""
        run = _run_with_tp(tmp_path)
        d = _task_dir(run, task="tp_a_seed_6001", tp_ids=["TP-1"])
        (d / "sim_vsim.log").write_text("UVM_ERROR :    0\n", encoding="utf-8")

        idx = fake_vcover._case_cov_matrix(run)

        assert idx["by_tp"]["TP-1"]["signed_off"] is False
        assert "no_scb_evidence" in idx["by_tp"]["TP-1"]["reasons"]

    def test_tp_without_owner_case_is_reported_not_faked(self, tmp_path, fake_vcover):
        run = _run_with_tp(tmp_path)
        _task_dir(run, task="other_seed_1", test="other_test", tp_ids=["TP-OTHER"])

        idx = fake_vcover._case_cov_matrix(run)

        s = idx["by_tp"]["TP-1"]
        assert s["signed_off"] is False
        assert s["reasons"] == ["no_owner_case"]

    def test_tp_matrix_carries_signoff_fields(self, tmp_path, fake_vcover):
        run = _run_with_tp(tmp_path)
        _task_dir(run, task="tp_a_seed_6001", tp_ids=["TP-1"])
        rep = run / "sim" / "coverage" / "reports"
        rep.mkdir(parents=True)
        (rep / "coverage_cvg.txt").write_text(VCOVER, encoding="utf-8")

        m = fake_vcover._tp_matrix(run, {"report_dir": str(rep)})

        row = m["rows"][0]
        assert row["status"] == "HIT"
        assert row["signed_off"] is True
        assert row["signed_off_by"] == "tp_a_seed_6001@6001"
        assert m["counts"]["SIGNED_OFF"] == 1
        assert m["counts"]["UNSIGNED"] == 0
        assert m["signed_off_total"] == 1


# ────────────────────────────────────────────────────────────────
# 波形索引
# ────────────────────────────────────────────────────────────────

class TestWaveManifest:
    def test_manifest_maps_task_to_tp_and_wave(self, tmp_path):
        run = tmp_path / "run"
        d = _task_dir(run, task="tp_a_seed_6001", tp_ids=["TP-1"])

        m = case_meta.write_wave_manifest(run, [d])

        assert m["schema"] == "wave_manifest_v1"
        assert m["count"] == 1 and m["with_wave"] == 1
        entry = m["entries"][0]
        assert entry["task"] == "tp_a_seed_6001"
        assert entry["tp_ids"] == ["TP-1"]
        assert entry["wave_exists"] is True
        assert m["by_tp"]["TP-1"][0]["task"] == "tp_a_seed_6001"
        assert (run / "waves" / "manifest.json").is_file()
        assert case_meta.read_wave_manifest(run)["count"] == 1

    def test_missing_wave_is_an_honest_empty_entry(self, tmp_path):
        run = tmp_path / "run"
        d = _task_dir(run, task="tp_a_seed_6001", tp_ids=["TP-1"], wave=False)

        m = case_meta.write_wave_manifest(run, [d])

        assert m["entries"][0]["wave"] == ""
        assert m["entries"][0]["wave_exists"] is False
        assert m["with_wave"] == 0


# ────────────────────────────────────────────────────────────────
# audit 门（三态：判不了 / 全签 / 有缺口）
# ────────────────────────────────────────────────────────────────

class TestAuditSignoffGate:
    def _gate(self, tmp_path, rows):
        from src.executors.audit.main import _apply_case_coverage_gate
        gates: dict = {}
        caveats: list = []
        cc = _apply_case_coverage_gate(
            tmp_path, {"rows": rows}, gates,
            lambda code, msg: caveats.append(code))
        return gates, caveats, cc

    def test_no_case_evidence_is_unknown_not_failed(self, tmp_path):
        """老 run / 没 TP IR：`None` = 判不了，不挂 caveat（三态纪律）。"""
        gates, caveats, _ = self._gate(
            tmp_path, [{"tp_id": "TP-1", "kind": "stimulus"}])
        assert gates["tp_signed_off"] is None
        assert caveats == []

    def test_unsigned_drivable_tp_is_a_caveat(self, tmp_path):
        gates, caveats, cc = self._gate(tmp_path, [{
            "tp_id": "TP-1", "kind": "stimulus", "stage": "p1",
            "signed_off": False, "signed_off_by": ""}])
        assert gates["tp_signed_off"] is False
        assert "TP_NOT_SIGNED_OFF" in caveats
        assert cc["unsigned_required"] == 1

    def test_all_signed_is_green(self, tmp_path):
        gates, caveats, _ = self._gate(tmp_path, [{
            "tp_id": "TP-1", "kind": "stimulus", "stage": "p1",
            "signed_off": True, "signed_off_by": "tp_a_seed_1@1"}])
        assert gates["tp_signed_off"] is True
        assert "TP_NOT_SIGNED_OFF" not in caveats

    def test_signed_but_wave_not_indexed_is_flagged(self, tmp_path):
        """manifest 找不到签核用例 → 签核材料不可反查，必须说出来。"""
        (tmp_path / "waves").mkdir(parents=True)
        (tmp_path / "waves" / "manifest.json").write_text(
            '{"schema": "wave_manifest_v1", "entries": '
            '[{"task": "another_case", "wave": "x.db"}]}', encoding="utf-8")
        gates, caveats, _ = self._gate(tmp_path, [{
            "tp_id": "TP-1", "kind": "stimulus", "stage": "p1",
            "signed_off": True, "signed_off_by": "tp_a_seed_1@1"}])
        assert gates["tp_signed_off"] is True
        assert "TP_WAVE_MISSING" in caveats


class TestPerSbEvidence:
    """逐条 SB 收口（`[SCB <id>]`）—— 接口先通，等 UVM 侧按 `scoreboards:` 生成。

    现在 env 只打聚合行 `[SCB_DUT]`；一旦日志里出现 `[SCB SB-X]`，证据必须
    优先用它（`evidence_level=per_scb`），**不能**继续拿聚合冒充逐条。
    """

    def test_parse_per_sb_lines(self):
        from src.tools.common.lib.case_meta import parse_case_log

        facts = parse_case_log(
            "[SCB_DUT] total=40 matched=40 mismatched=0\n"
            "[SCB SB-X] total=5 matched=4 mismatched=1\n")
        assert facts["scb"]["matched"] == 40
        assert facts["scb_by_id"]["SB-X"] == {"total": 5, "matched": 4,
                                             "mismatched": 1}

    def test_per_sb_evidence_wins_over_aggregate(self):
        from src.layers.l3_decision.evidence.case_cov import _scb_evidence

        facts = {"scb_summary": {"total": 40, "matched": 40, "mismatched": 0},
                 "log_facts": {"scb_by_id": {"SB-X": {"total": 5, "matched": 4,
                                                     "mismatched": 1}}}}
        out = _scb_evidence([{"id": "SB-X", "cell": "CELL-X",
                              "evidence": "auto"}], facts)
        assert out[0]["evidence_level"] == "per_scb"
        assert out[0]["status"] == "MISSING"       # 逐条的 mismatch 不能被聚合盖住

    def test_log_mode_without_own_line_is_not_executed(self):
        from src.layers.l3_decision.evidence.case_cov import _scb_evidence

        facts = {"scb_summary": {"total": 40, "matched": 40, "mismatched": 0},
                 "log_facts": {}}
        out = _scb_evidence([{"id": "SB-X", "cell": "CELL-X",
                              "evidence": "log"}], facts)
        assert out[0]["evidence_level"] == "none"
        assert out[0]["status"] == "NOT_EXECUTED"
