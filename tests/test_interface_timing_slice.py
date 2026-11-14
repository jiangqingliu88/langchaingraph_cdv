"""单接口时序闭环的定向验证。test_double 不代表真实 RTL 仿真证据。"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.agent_plane.specification.temporal_extractor import TemporalCandidateExtractor
from src.engine_plane.interface_timing import check_anchor, check_temporal_ir
from src.engine_plane.interface_timing.checker import _rule_issues
from src.engine_plane.specification_compiler import SpecificationCompiler
from src.generation_plane.interface_timing import render_monitor, write_monitor
from src.ir_plane.interface_timing import TimingContractError, temporal_from_dict, to_specification_document
from src.orchestration_plane.interface_timing_workflow import TemporalSlicePipeline
from src.runtime_plane.tools.execution.interface_timing import SimulationResult, simulate
from src.runtime_plane.tools.execution.interface_timing.simulator import _evaluate_monitor_text, _render_testbench
from src.runtime_plane.tools.specification_extraction import extract_rtl_facts

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/interface_timing/axi_stream"


def _fixture(tmp_path):
    root = tmp_path / "fixture"
    shutil.copytree(FIXTURE, root)
    doc = yaml.safe_load((root / "intents/structured.yaml").read_text(encoding="utf-8"))
    return root, doc


def _save(root, doc):
    (root / "intents/structured.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _ports(root, name="pass_master.sv"):
    return extract_rtl_facts(root / "rtl" / name)["ports"]


def _spy_backend(kind="test_double"):
    def backend(ir, monitor, rtl_file, out_dir, *, seed):
        return SimulationResult(
            "FAIL" if Path(rtl_file).name == "fail_master.sv" else "PASS", {"simulation_kind": kind, "seed": seed}
        )

    return backend


def test_structured_source_and_rtl_binding_are_validated(tmp_path):
    root, doc = _fixture(tmp_path)
    ir = temporal_from_dict(doc)
    assert ir.clock.name == "aclk"
    assert ir.clock.reset_active_high is False
    assert ir.clock.period_ps == 10000
    report = check_temporal_ir(ir, _ports(root), root)
    assert report.status == "VALIDATED", report.issues
    assert report.binding_count == 3
    assert report.scope["protocol"] == "axi4_stream"


def test_clock_serialization_round_trip_preserves_hash(tmp_path):
    _, doc = _fixture(tmp_path)
    first = temporal_from_dict(doc)
    serialized = first.to_dict()
    assert serialized["rules"][0]["clock"] == "aclk"
    # 早期完整对象写法也兼容，但输出统一为规则引用时钟名。
    serialized["rules"][0]["clock"] = first.clock.to_dict()
    second = temporal_from_dict(serialized)
    assert second.content_hash() == first.content_hash()


def _spec_fragment(tmp_path):
    root, doc = _fixture(tmp_path)
    ir = temporal_from_dict(doc)
    report = check_temporal_ir(ir, _ports(root), root)
    return ir, report, to_specification_document(ir, report)


def test_specification_compiler_requires_matching_interface_binding(tmp_path):
    _, _, document = _spec_fragment(tmp_path)
    document["metadata"]["interface_binding_reports"] = {}
    result = SpecificationCompiler().compile(document)
    assert result.status == "INCOMPLETE"
    assert not result.execution_allowed
    assert any(issue.code == "missing_interface_binding" for issue in result.issues)


def test_legacy_interface_list_is_not_silently_discarded(tmp_path):
    _, _, document = _spec_fragment(tmp_path)
    del document["metadata"]["temporal_interfaces"]
    document["interfaces"] = [{"name": "signal-only-port-list"}]
    result = SpecificationCompiler().compile(document)
    assert result.status == "INCOMPLETE"
    assert any(issue.code == "unsupported_interface_declaration" for issue in result.issues)


def test_old_binding_cannot_cover_a_changed_temporal_ir(tmp_path):
    _, _, document = _spec_fragment(tmp_path)
    document["metadata"]["temporal_interfaces"][0]["clock"]["period_ps"] = 20000
    result = SpecificationCompiler().compile(document)
    assert result.status == "INCOMPLETE"
    assert any(issue.code == "missing_interface_binding" for issue in result.issues)


def test_fixture_records_original_specification_lifecycle(tmp_path):
    root, _ = _fixture(tmp_path)
    result = TemporalSlicePipeline(root, tmp_path / "out", simulate_backend=_spy_backend()).run()
    readiness = result["specification_readiness"]
    assert readiness["status"] == "VALIDATED"
    assert [event["stage"] for event in readiness["contract"]["lifecycle"]] == [
        "ingestion",
        "extraction",
        "reconciliation",
        "gap_analysis",
        "clarification",
        "synthesis",
        "ir_compilation",
        "validation",
        "evolution",
    ]
    interface = readiness["contract"]["metadata"]["temporal_interfaces"][0]
    assert interface["rules"][0]["clock"] == "aclk"
    assert result["simulation_kind"] == "test_double"


def test_wrong_quote_cannot_pass_as_source_evidence(tmp_path):
    root, doc = _fixture(tmp_path)
    doc["rules"][0]["anchor"]["quote"] = "invented by a language model"
    report = check_temporal_ir(temporal_from_dict(doc), _ports(root), root)
    assert report.status == "INCOMPLETE"
    assert any(row["code"] == "anchor_mismatch" for row in report.issues)


def test_changed_document_hash_invalidates_anchor(tmp_path):
    root, doc = _fixture(tmp_path)
    anchor = temporal_from_dict(doc).rules[0].anchor
    (root / "source/spec.md").write_text(
        (root / "source/spec.md").read_text(encoding="utf-8") + "\nchanged later\n", encoding="utf-8"
    )
    issues = check_anchor(anchor, root)
    assert [row["code"] for row in issues] == ["stale_source_anchor"]


def test_anchor_cannot_escape_source_root(tmp_path):
    root, doc = _fixture(tmp_path)
    doc["rules"][0]["anchor"]["locator"] = "../outside.md"
    issues = check_anchor(temporal_from_dict(doc).rules[0].anchor, root)
    assert issues[0]["code"] == "anchor_outside_project"


def test_anchor_must_cover_all_bound_endpoints(tmp_path):
    root, doc = _fixture(tmp_path)
    doc["rules"][0]["anchor"]["quote"] = "Consuming a stream is nice."
    issues = _rule_issues(temporal_from_dict(doc), {row["name"]: row for row in _ports(root)}, root)
    assert any(row["code"] == "anchor_does_not_bind_endpoints" for row in issues)


def test_candidate_llm_output_is_forced_to_derived(tmp_path):
    _, doc = _fixture(tmp_path)
    candidate = TemporalCandidateExtractor(lambda _text: copy.deepcopy(doc)).extract("spec excerpt")
    assert candidate["status"] == "DERIVED"
    assert {row["binding_status"] for row in candidate["signals"]} == {"DERIVED"}
    assert {row["status"] for row in candidate["rules"]} == {"DERIVED"}


def test_candidate_without_source_anchor_is_rejected(tmp_path):
    _, doc = _fixture(tmp_path)
    del doc["rules"][0]["anchor"]
    with pytest.raises(TimingContractError):
        TemporalCandidateExtractor(lambda _text: doc).extract("raw text")


def test_derived_semantics_blocks_generation(tmp_path):
    root, doc = _fixture(tmp_path)
    doc["status"] = "DERIVED"
    for signal in doc["signals"]:
        signal["binding_status"] = "DERIVED"
    report = check_temporal_ir(temporal_from_dict(doc), _ports(root), root)
    assert report.status == "INCOMPLETE"
    assert any(row["code"] == "unconfirmed_interface" for row in report.issues)


def test_unmatched_rtl_signal_is_not_guessed(tmp_path):
    root, doc = _fixture(tmp_path)
    doc["signals"][0]["name"] = "m_axis_tvalid_unbound"
    report = check_temporal_ir(temporal_from_dict(doc), _ports(root), root)
    assert report.status == "INCOMPLETE"
    assert any(row["code"] == "missing_rtl_binding" for row in report.issues)


def test_direction_conflict_is_definite_conflict(tmp_path):
    root, doc = _fixture(tmp_path)
    ports = _ports(root)
    next(row for row in ports if row["name"] == "m_axis_tvalid")["direction"] = "input"
    report = check_temporal_ir(temporal_from_dict(doc), ports, root)
    assert report.status == "CONFLICT"
    assert any(row["code"] == "signal_direction_conflict" for row in report.issues)


def test_multiplier_or_unknown_signal_roles_are_not_silently_supported(tmp_path):
    root, doc = _fixture(tmp_path)
    doc["signals"][1]["role"] = "VALID"
    doc["signals"][1]["name"] = doc["signals"][0]["name"]
    report = check_temporal_ir(temporal_from_dict(doc), _ports(root), root)
    assert report.status == "INCOMPLETE"
    assert any(row["code"] == "unsupported_signal_roles" for row in report.issues)


def test_monitor_is_generated_from_typed_fields_not_prose(tmp_path):
    _, doc = _fixture(tmp_path)
    artifact = write_monitor(temporal_from_dict(doc), tmp_path)
    text = artifact.path.read_text(encoding="utf-8")
    assert artifact.module == "monitor_r_valid_data_stable"
    assert "prev_valid && !prev_ready" in text
    assert "m_axis_tdata !== prev_0" in text
    assert "prev_0 <= m_axis_tdata;" in text
    assert "prev_0 <= '0;" in text
    assert "unknown_samples" in text
    assert "natural language ignored" not in text


def test_hdl_text_cannot_inject_arbitrary_statement(tmp_path):
    _, doc = _fixture(tmp_path)
    doc["rules"][0]["valid"] = "valid; $finish;"
    with pytest.raises(ValueError):
        render_monitor(temporal_from_dict(doc))


def test_testbench_has_explicit_connections_seed_and_half_period(tmp_path):
    _, doc = _fixture(tmp_path)
    ir = temporal_from_dict(doc)
    monitor = write_monitor(ir, tmp_path)
    text = _render_testbench(ir, monitor, 4242, "stream_master_model")
    assert "always #(5000.0) aclk = ~aclk" in text
    expected_payload = 0x101 ^ 4242
    assert f"32'h{expected_payload:x}" in text
    assert ".m_axis_tvalid(m_axis_tvalid)" in text
    assert ".m_axis_tdata(m_axis_tdata)" in text
    assert "TIMING_RESULT rule=R-VALID-DATA-STABLE" in text


def test_log_from_another_rule_cannot_satisfy_this_interface():
    log = "TIMING_RESULT rule=OTHER violations=0 handshakes=1 blocked=1 unknown=0\n"
    result = _evaluate_monitor_text(log, "R-VALID-DATA-STABLE", {"simulation_kind": "test_double"})
    assert result.status == "INCOMPLETE"
    assert "规则不匹配" in result.report["reason"]
    assert "counts" not in result.report


def test_missing_simulator_returns_incomplete_never_rtl_pass(tmp_path, monkeypatch):
    _, doc = _fixture(tmp_path)
    artifact = write_monitor(temporal_from_dict(doc), tmp_path)
    monkeypatch.setattr("src.runtime_plane.tools.execution.interface_timing.simulator._verilog_exe", lambda _name: "")
    result = simulate(temporal_from_dict(doc), artifact, FIXTURE / "rtl/pass_master.sv", tmp_path / "run", seed=7)
    assert result.status == "INCOMPLETE"
    assert result.report["simulation_kind"] == "unavailable"


def test_unavailable_backend_cannot_meet_slice_expectations(tmp_path):
    root, _ = _fixture(tmp_path)

    def unavailable(*_args, **_kwargs):
        return SimulationResult("INCOMPLETE", {"simulation_kind": "unavailable"})

    result = TemporalSlicePipeline(root, tmp_path / "out", simulate_backend=unavailable).run(seed=4242)
    assert result["overall_status"] == "INCOMPLETE"
    assert [row["actual_status"] for row in result["scenarios"]] == ["INCOMPLETE", "INCOMPLETE"]
    assert not result["expectation_met"]


def test_outcome_evaluation_has_negative_control_and_marks_test_double(tmp_path):
    root, _ = _fixture(tmp_path)
    result = TemporalSlicePipeline(root, tmp_path / "out", simulate_backend=_spy_backend()).run()
    assert result["overall_status"] == "PASS"
    assert [row["actual_status"] for row in result["scenarios"]] == ["PASS", "FAIL"]
    assert result["simulation_kind"] == "test_double"
    manifest = json.loads(Path(result["evidence_manifest"]).read_text(encoding="utf-8"))
    assert manifest["rtl_simulation_completed"] is False
    assert manifest["not_covered"]


def test_missing_negative_alarm_is_an_overall_failure(tmp_path):
    root, _ = _fixture(tmp_path)

    def no_alarm(*_args, **_kwargs):
        return SimulationResult("PASS", {"simulation_kind": "test_without_alarm"})

    result = TemporalSlicePipeline(root, tmp_path / "out", simulate_backend=no_alarm).run()
    assert result["overall_status"] == "FAIL"
    assert result["scenarios"][1]["expectation_met"] is False


def test_bad_anchor_blocks_monitor_and_runtime(tmp_path):
    root, doc = _fixture(tmp_path)
    doc["rules"][0]["anchor"]["quote"] = "not in the original"
    _save(root, doc)
    calls = []

    def forbidden(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("不得生成或执行")

    result = TemporalSlicePipeline(root, tmp_path / "out", simulate_backend=forbidden).run()
    assert result["overall_status"] == "INCOMPLETE"
    assert result["scenarios"] == []
    assert not list((tmp_path / "out").rglob("monitor_*.sv"))
    assert not calls


def test_bad_clock_period_never_reaches_backend(tmp_path):
    root, doc = _fixture(tmp_path)
    doc["clock"]["period_ps"] = 0
    _save(root, doc)
    result = TemporalSlicePipeline(
        root, tmp_path / "out", simulate_backend=lambda *_a, **_k: pytest.fail("不应仿真")
    ).run()
    assert result["overall_status"] == "INCOMPLETE"
    assert result["stage"] == "binding_validation"


def test_malformed_yaml_is_incomplete_not_traceback(tmp_path):
    root, _ = _fixture(tmp_path)
    (root / "intents/structured.yaml").write_text("interfaces: [\n", encoding="utf-8")
    result = TemporalSlicePipeline(root, tmp_path / "out").run()
    assert result["overall_status"] == "INCOMPLETE"
    assert "YAML" in result["reason"]
