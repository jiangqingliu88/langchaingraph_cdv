"""M1-A：Resource / Interaction IR 的输入完整性与三态裁决。

静态检查 PASS 只是声明级结论，不是 RTL 仿真或 Verification Signoff PASS。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.engine_plane.verify.resource_intent import verify_document, verify_file
from src.ir_plane.decision.resource_model import AddressRange, overlap
from src.ir_plane.decision.resource_model.policy import evaluate


def _doc(relation: str = "FORBIDDEN_OVERLAP"):
    return {
        "module": "dma_gemm_test",
        "resources": [{"id": "sram", "type": "sram", "address_space": "soc", "base": 0x1000, "size": 0x100}],
        "operations": [
            {"id": "dma", "owner": "dma", "resource": "sram", "accesses": [{"address": 0x1000, "length": 0x20}]},
            {"id": "gemm", "owner": "gemm", "resource": "sram", "accesses": [{"address": 0x1010, "length": 0x20}]},
        ],
        "interactions": [{"id": "IF-DMA-GEMM", "operation_a": "dma", "operation_b": "gemm", "relation": relation}],
    }


def _rules(result, rule):
    return [item for item in result["validation"] if item["rule"] == rule]


# ── 原有三个 fail-open 反例 ─────────────────────────────────────────


def test_unknown_policy_is_incomplete_not_unrestricted_pass():
    result = verify_document(_doc("FORBIDEN_OVERLAP"))
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "unknown_policy")


def test_negative_and_zero_length_are_invalid_declaration():
    for index, length in ((0, -1), (1, 0)):
        doc = _doc()
        doc["operations"][index]["accesses"][0]["length"] = length
        result = verify_document(doc)
        assert result["status"] == "INCOMPLETE"
        assert _rules(result, "invalid_access_length")


def test_accesses_outside_resource_bounds_fail_even_without_overlap():
    doc = _doc()
    doc["operations"][0]["accesses"][0]["address"] = 0x9000
    doc["operations"][1]["accesses"][0]["address"] = 0x9100
    result = verify_document(doc)
    assert result["status"] == "FAIL"
    assert not result["conflicts"]
    assert len(_rules(result, "access_out_of_bounds")) == 2


# ── 数值、资源与引用的输入完整性 ────────────────────────────────────


@pytest.mark.parametrize("value", [-1, -(2**64)])
def test_negative_address_is_incomplete(value):
    doc = _doc()
    doc["operations"][0]["accesses"][0]["address"] = value
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "invalid_access_address")


@pytest.mark.parametrize(
    "field,value",
    [
        ("address", "0x-not-an-address"),
        ("address", 1.5),
        ("address", True),
        ("length", "many-bytes"),
        ("length", 1.5),
        ("length", False),
    ],
)
def test_invalid_integer_is_never_coerced_to_a_pass(field, value):
    doc = _doc()
    doc["operations"][0]["accesses"][0][field] = value
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "invalid_integer")
    assert not result["facts"]


@pytest.mark.parametrize("value", [0, -4, "invalid", 1.5, True, None])
def test_invalid_granularity_is_incomplete(value):
    doc = _doc()
    doc["resources"][0]["granularity"] = value
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert any(row["rule"] in ("invalid_integer", "invalid_granularity") for row in result["validation"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("base", -1),
        ("base", "bad"),
        ("base", 1.5),
        ("size", 0),
        ("size", -4),
        ("size", "bad"),
    ],
)
def test_invalid_resource_bounds_are_incomplete(field, value):
    doc = _doc()
    doc["resources"][0][field] = value
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert result["validation"]


def test_incomplete_resource_bounds_declaration_is_incomplete():
    doc = _doc()
    del doc["resources"][0]["size"]
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "incomplete_resource_bounds")


def test_access_without_declared_resource_bounds_is_incomplete():
    doc = _doc("UNRESTRICTED")
    del doc["resources"][0]["base"]
    del doc["resources"][0]["size"]
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "incomplete_resource_bounds")


@pytest.mark.parametrize("index", [0, 1])
def test_access_without_resource_binding_is_incomplete(index):
    doc = _doc("UNRESTRICTED")
    del doc["operations"][index]["resource"]
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "missing_resource")


def test_address_width_overflow_is_a_definite_failure():
    doc = _doc()
    doc["resources"][0]["base"] = 0
    doc["resources"][0]["size"] = 1 << 64
    doc["operations"][0]["accesses"][0]["address"] = (1 << 64) - 16
    doc["operations"][0]["accesses"][0]["length"] = 64
    result = verify_document(doc, address_width=64)
    assert result["status"] == "FAIL"
    assert result["overflows"]
    assert _rules(result, "address_overflow")


@pytest.mark.parametrize("width", [0, -1, "64", True, None])
def test_invalid_address_width_cannot_be_used_to_pass(width):
    doc = _doc("UNRESTRICTED")
    result = verify_document(doc, address_width=width)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "invalid_address_width")
    assert not result["facts"]


def test_resource_declaration_outside_address_width_fails():
    doc = _doc("UNRESTRICTED")
    doc["resources"][0]["base"] = 0xF0
    doc["resources"][0]["size"] = 0x20
    for op in doc["operations"]:
        op["accesses"][0]["address"] = 0xF0
        op["accesses"][0]["length"] = 0x10
    result = verify_document(doc, address_width=8)
    assert result["status"] == "FAIL"
    assert _rules(result, "resource_bounds_overflow")


@pytest.mark.parametrize("kind", ["resources", "operations", "interactions"])
def test_duplicate_ids_are_incomplete(kind):
    doc = _doc()
    if kind in ("resources", "interactions"):
        doc[kind].append(copy.deepcopy(doc[kind][0]))
    else:
        doc[kind][1]["id"] = doc[kind][0]["id"]
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "duplicate_id")


@pytest.mark.parametrize("kind", ["resources", "operations", "interactions"])
def test_missing_ids_are_incomplete(kind):
    doc = _doc()
    doc[kind][0]["id"] = ""
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "missing_id")


@pytest.mark.parametrize("address_space", [None, "", "  ", 123, []])
def test_missing_address_space_is_incomplete(address_space):
    doc = _doc()
    doc["resources"][0]["address_space"] = address_space
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "invalid_address_space")


def test_cross_address_space_interaction_is_incomplete_not_none_pass():
    doc = _doc()
    doc["resources"].append({"id": "dram", "address_space": "host"})
    doc["operations"][1]["resource"] = "dram"
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "cross_address_space")
    assert overlap(AddressRange(0, 1, "soc"), AddressRange(0, 1, "host")) == "NONE"


@pytest.mark.parametrize("kind", ["resources", "operations", "interactions"])
def test_required_collections_cannot_be_empty(kind):
    doc = _doc()
    doc[kind] = []
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert result["validation"]


def test_empty_accesses_are_incomplete_not_no_conflict():
    doc = _doc()
    doc["operations"][0]["accesses"] = []
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "empty_accesses")


def test_malformed_containers_and_rows_are_incomplete():
    doc = _doc()
    doc["resources"] = {"id": "not-a-list"}
    result = verify_document(doc)
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "invalid_container")
    assert not result["facts"]


def test_non_dictionary_document_is_incomplete():
    result = verify_document(["not", "a", "mapping"])
    assert result["status"] == "INCOMPLETE"
    assert _rules(result, "invalid_document_type")
    assert not result["facts"]


def test_direct_unknown_policy_result_is_explicitly_invalid():
    decision = evaluate("typo-policy", "FULL")
    assert decision["valid"] is False
    assert decision["incomplete"] is True
    assert "UNRESTRICTED" not in decision["reason"]


# ── 合法模型与四类边界不能回归 ─────────────────────────────────────


@pytest.mark.parametrize(
    "name,a,b,overlap_kind,status",
    [
        ("partial", (0x1000, 0x20), (0x1010, 0x20), "PARTIAL", "FAIL"),
        ("full", (0x1000, 0x20), (0x1000, 0x20), "FULL", "FAIL"),
        ("contained", (0x1000, 0x80), (0x1010, 0x10), "CONTAINED", "FAIL"),
        ("adjacent", (0x1000, 0x20), (0x1020, 0x20), "ADJACENT", "PASS"),
        ("disjoint", (0x1000, 0x20), (0x1040, 0x20), "NONE", "PASS"),
    ],
)
def test_legal_overlap_cases_keep_expected_status(name, a, b, overlap_kind, status):
    doc = _doc()
    for operation, (address, length) in zip(doc["operations"], (a, b)):
        operation["accesses"] = [{"address": address, "length": length}]
    result = verify_document(doc)
    assert result["status"] == status
    assert not result["validation"]
    assert result["facts"][0]["overlap"] == overlap_kind


def test_shorthand_operation_address_and_length_remains_supported():
    doc = _doc("UNRESTRICTED")
    for operation in doc["operations"]:
        access = operation.pop("accesses")[0]
        operation.update(access)
    result = verify_document(doc)
    assert result["status"] == "PASS"
    assert result["counts"]["facts"] == 1


def test_verification_does_not_mutate_input_and_hash_is_stable():
    doc = _doc("UNRESTRICTED")
    before = copy.deepcopy(doc)
    first = verify_document(doc)
    second = verify_document(doc)
    assert doc == before
    assert first["status"] == "PASS"
    assert first["intent_hash"] == second["intent_hash"]


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("resource_intent.yaml", "PASS"),
        ("dma_gemm_conflict.yaml", "FAIL"),
        ("dma_gemm_interaction.yaml", "PASS"),
    ],
)
def test_shipped_dma_gemm_examples_keep_expected_static_status(filename, expected):
    path = Path(__file__).resolve().parents[1] / "examples/open_npu_soc/spec" / filename
    result = verify_file(path)
    assert result["status"] == expected
    assert not result["validation"]
    assert result["counts"]["scenarios"] > 0


# ── 文件解析 → Engine → Audit / CLI 的不合法输入语义 ────────────────


@pytest.mark.parametrize(
    "suffix,content",
    [
        (".yaml", "resources: [\n"),
        (".yml", "operations: {"),
        (".json", "{not-json"),
    ],
)
def test_malformed_file_returns_incomplete_result(tmp_path, suffix, content):
    path = tmp_path / f"intent{suffix}"
    path.write_text(content, encoding="utf-8")
    result = verify_file(path)
    assert result["status"] == "INCOMPLETE"
    assert result["counts"]["facts"] == 0
    assert any(row["rule"].startswith("malformed_") for row in result["validation"])
    assert result["intent_hash"]


def test_cli_maps_pass_fail_and_incomplete_to_distinct_exit_codes(tmp_path):
    from click.testing import CliRunner

    from src.workbench.cli.commands import cli

    files = {}
    for name, doc in (("pass", _doc("UNRESTRICTED")), ("fail", _doc()), ("incomplete", _doc("TYPO"))):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        files[name] = str(path)
    runner = CliRunner()
    for name, code in (("pass", 0), ("fail", 1), ("incomplete", 2)):
        result = runner.invoke(cli, ["resource", "verify", files[name]])
        assert result.exit_code == code, result.output


def test_malformed_verify_input_writes_incomplete_for_audit(tmp_path):
    from src.engine_plane.audit.helpers import add_resource_intent_caveat, read_resource_intent_status
    from src.engine_plane.verify.ir_artifacts import write_resource_artifacts

    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs/resources.yaml").write_text("resources: [\n", encoding="utf-8")
    result = write_resource_artifacts(tmp_path, "malformed_demo")
    assert result["available"] is False
    status = read_resource_intent_status(tmp_path)
    assert status == "INCOMPLETE"
    caveats = []
    add_resource_intent_caveat(status, lambda code, message: caveats.append(code))
    assert caveats == ["RESOURCE_INTENT_INCOMPLETE"]


def test_audit_hard_gate_rejects_fail_incomplete_and_unknown_status():
    from src.engine_plane.audit.helpers import resource_intent_hard_ok

    decisions = [(status, resource_intent_hard_ok(status)) for status in ("PASS", "", "FAIL", "INCOMPLETE", "BROKEN")]
    assert decisions == [("PASS", True), ("", True), ("FAIL", False), ("INCOMPLETE", False), ("BROKEN", False)]


def test_corrupt_result_is_incomplete_missing_file_stays_not_applicable(tmp_path):
    from src.engine_plane.audit.helpers import read_resource_intent_status

    assert read_resource_intent_status(tmp_path) == ""
    (tmp_path / "coverage").mkdir()
    (tmp_path / "coverage/resource_intent_result.json").write_text("{bad", encoding="utf-8")
    assert read_resource_intent_status(tmp_path) == "INCOMPLETE"
