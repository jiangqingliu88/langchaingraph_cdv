from __future__ import annotations

import json

import pytest

from src.core.contracts import (
    EVENT_TYPES, PRODUCERS, build_envelope, event_producer, read_jsonl,
    register_producer, sha256_json, validate_envelope, validate_event_type,
    versions, write_jsonl,
)
from src.core.contracts.quality import overall_status


def test_versions_are_centralized_and_known():
    assert versions.EVENTS == "events_v1"
    assert versions.known(versions.PROVENANCE)
    assert not versions.known("nope_v1")
    assert versions.schema_registry()["events_v1"] == "run_facts"


def test_jsonl_round_trip_is_deterministic(tmp_path):
    path = tmp_path / "rows.jsonl"
    rows = [{"b": 2, "a": 1}, {"a": 3}]
    d1 = write_jsonl(path, rows, sort_key=lambda r: r.get("a", 0))
    d2 = write_jsonl(path, list(reversed(rows)), sort_key=lambda r: r.get("a", 0))
    assert d1 == d2
    assert read_jsonl(path) == [{"a": 1, "b": 2}, {"a": 3}]
    assert sha256_json({"b": 2, "a": 1}) == sha256_json({"a": 1, "b": 2})


def test_jsonl_skips_corrupt_lines(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"a": 1}\n{bad\n{"a": 2}\n', encoding="utf-8")
    assert [r["a"] for r in read_jsonl(path)] == [1, 2]


def test_event_registry_forbids_silent_reassignment():
    assert validate_event_type("stage.started")
    assert event_producer("stage.started") == "journal"
    with pytest.raises(ValueError):
        register_producer("stage.started", "someone-else")
    register_producer("custom.event", "unit-test")
    assert event_producer("custom.event") == "unit-test"
    assert validate_event_type("custom.event")


def test_envelope_build_and_validate():
    env = build_envelope(run_id="r1", module="m", profile=versions.EVIDENCE_SOC_PROFILE,
                         inputs={"x": 1}, execution={"y": 2}, verdict={"z": 3},
                         replay={"tier_a": "hash"}, hashes={"package_hash": "abc"})
    assert env["schema"] == versions.EVIDENCE_ENVELOPE
    assert validate_envelope(env) == []
    assert validate_envelope({"schema": versions.EVIDENCE_ENVELOPE})
    with pytest.raises(ValueError):
        build_envelope(run_id="r1", profile="nope")


def test_quality_overall_priority():
    assert overall_status(["pass", "pass"]) == "pass"
    assert overall_status(["pass", "warn"]) == "warn"
    assert overall_status(["warn", "unknown"]) == "unknown"
    assert overall_status(["unknown", "fail"]) == "fail"
