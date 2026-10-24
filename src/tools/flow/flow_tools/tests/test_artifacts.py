"""中间产物目录 —— 一次运行里"人该看、也该能改"的那些文件。

要钉住三件事：
  · **没生成的文件也照列**（`exists: false`）—— "这一份还没生成"本身就是信息，
    说明那次运行没跑到产出它的阶段，静默不列等于让人以为它不存在过；
  · **schema 状态是真的算出来的**（跑真校验器，不猜），有错的文件要能指名道姓；
  · **有 schema 的和没 schema 的分得清** —— `spec.json` / `regression.yaml` 没有
    schema，如实标 `null`，不假装校验过。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.tools.flow.flow_tools import run_artifacts

GOOD_BENCH = """bench:
  name: dut_bench
  include_assertions: false
  clk_rst_if:
    clocks:
      - { name: clk, period: 10ns, init: 0 }
    resets:
      - { name: rst_n, init: 0, release_delay: 10 }
  dut_instance: u_dut
  harness:
    name: dut_harness
    bind_to: dut
    interfaces: []
"""

#: 旧格式：`env_name` / `dut:` / 空 `agents:` —— 正是让整次运行挂在 verify 的那几处
BAD_BENCH = """bench:
  name: dut_bench
  env_name: dut_env
  timeout: 10ms
  agents:
  dut:
    module: dut
    instance: u_dut
"""


def _run(tmp_path: Path, *, bench: str = GOOD_BENCH, spec: bool = True) -> Path:
    root = tmp_path / "output_demo_20260101_000000"
    (root / "inputs" / "yaml" / "uvm").mkdir(parents=True)
    if spec:
        (root / "spec.json").write_text('{"design_name": "dut"}', encoding="utf-8")
    (root / "inputs" / "yaml" / "uvm" / "bench.yaml").write_text(bench, encoding="utf-8")
    return root


def _by_path(report) -> dict:
    return {a["path"]: a for a in report["artifacts"]}


class TestCatalog:
    def test_lists_the_intermediate_artifacts(self, tmp_path):
        report = run_artifacts(str(_run(tmp_path)))
        paths = [a["path"] for a in report["artifacts"]]
        assert paths == ["spec.json", "inputs/yaml/uvm/bench.yaml",
                         "inputs/yaml/regression.yaml"]

    def test_a_missing_artifact_is_still_listed(self, tmp_path):
        """`regression.yaml` 没写 → 照列，标 `exists: false`。"""
        report = run_artifacts(str(_run(tmp_path)))
        entry = _by_path(report)["inputs/yaml/regression.yaml"]
        assert entry["exists"] is False
        assert entry["sha256"] == "" and entry["errors"] == 0

    def test_the_summary_counts_present_and_broken(self, tmp_path):
        report = run_artifacts(str(_run(tmp_path)))
        assert report["present"] == 2          # spec.json + bench.yaml
        assert report["with_errors"] == 0
        assert "schema 都过" in report["summary"]

    def test_only_the_uvm_yamls_carry_a_schema(self, tmp_path):
        """没有 schema 的如实标 null —— 不假装校验过。"""
        entries = _by_path(run_artifacts(str(_run(tmp_path))))
        assert entries["spec.json"]["schema"] is None
        assert entries["inputs/yaml/regression.yaml"]["schema"] is None
        assert entries["inputs/yaml/uvm/bench.yaml"]["schema"] == "uvm_config"

    def test_every_present_artifact_carries_a_hash(self, tmp_path):
        """哈希用的是与证据链同一份实现 —— 审查台上看到的哈希要能和链对上。"""
        entries = _by_path(run_artifacts(str(_run(tmp_path))))
        assert len(entries["inputs/yaml/uvm/bench.yaml"]["sha256"]) == 64

    def test_the_run_id_comes_from_the_directory_name(self, tmp_path):
        report = run_artifacts(str(_run(tmp_path)))
        assert report["run_id"] == "output_demo_20260101_000000"


class TestSchemaStatus:
    def test_a_clean_file_passes(self, tmp_path):
        entry = _by_path(run_artifacts(str(_run(tmp_path))))["inputs/yaml/uvm/bench.yaml"]
        assert entry["errors"] == 0 and entry["warnings"] == 0

    def test_the_old_bench_shape_is_flagged(self, tmp_path):
        """**这就是那一刀要解的问题**：旧格式的 bench 会让运行挂在 verify。

        在此之前这件事只写在运行日志里（一行 `Schema validation failed`），得从
        日志挖到生成器；现在它在产物清单上直接是 `errors: 4`。
        """
        report = run_artifacts(str(_run(tmp_path, bench=BAD_BENCH)))
        entry = _by_path(report)["inputs/yaml/uvm/bench.yaml"]
        assert entry["errors"] > 0
        assert report["with_errors"] == 1
        assert "schema 不符" in report["summary"]

    def test_the_messages_name_the_field_and_the_line(self, tmp_path):
        """诊断要能落到具体字段和行 —— 不然人还得自己去文件里找。"""
        entry = _by_path(run_artifacts(str(_run(tmp_path, bench=BAD_BENCH))))[
            "inputs/yaml/uvm/bench.yaml"]
        assert entry["messages"], "一条诊断都没带出来"
        joined = " ".join(m["text"] for m in entry["messages"])
        assert "env_name" in joined or "dut" in joined or "agents" in joined
        assert any(m["line"] for m in entry["messages"]), "行号一个都没算出来"


class TestFailureIsLoud:
    def test_a_missing_directory_reports_an_error(self, tmp_path):
        report = run_artifacts(str(tmp_path / "nope"))
        assert "error" in report and "not found" in report["error"]

    def test_an_empty_run_id_is_an_error_not_a_crash(self):
        assert "error" in run_artifacts("")

    def test_a_broken_yaml_does_not_take_down_the_whole_catalog(self, tmp_path):
        """一份文件烂了，其余几份照样要能列出来。"""
        report = run_artifacts(str(_run(tmp_path, bench="bench: [未闭合\n")))
        assert len(report["artifacts"]) == 3
        entry = _by_path(report)["inputs/yaml/uvm/bench.yaml"]
        assert entry["errors"] > 0
