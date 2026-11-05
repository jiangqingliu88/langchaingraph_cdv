from __future__ import annotations

from pathlib import Path

from src.core.runtime.run_context import (
    RunContext, active_context, bind, open_run_context, reset, set_current,
)


def test_identity_and_paths(tmp_path):
    ctx = open_run_context(tmp_path, run_id="r1", module_id="dut")
    assert ctx.run_id == "r1"
    assert ctx.output_root == tmp_path
    paths = ctx.paths.ensure()
    assert paths.docs.is_dir() and paths.artifacts.is_dir()
    assert paths.decision.is_dir() and paths.coverage.is_dir()
    assert paths.events_file() == tmp_path / "docs" / "events.jsonl"


def test_child_keeps_parent_link(tmp_path):
    parent = open_run_context(tmp_path, run_id="r1")
    child = parent.child("sub", module_id="sub")
    assert child.run_id == "r1::sub"
    assert child.parent_run_id == "r1"
    assert child.output_root == tmp_path / "sub"


def test_bind_is_nested_and_restores(tmp_path):
    a = open_run_context(tmp_path / "a", run_id="a")
    b = open_run_context(tmp_path / "b", run_id="b")
    assert active_context() is None
    with bind(a):
        assert active_context() is a
        with bind(b):
            assert active_context() is b
        assert active_context() is a
    assert active_context() is None


def test_set_current_and_reset(tmp_path):
    ctx = open_run_context(tmp_path, run_id="r1")
    token = set_current(ctx)
    try:
        assert active_context() is ctx
    finally:
        reset(token)
    assert active_context() is None


def test_to_dict_is_serializable(tmp_path):
    doc = open_run_context(tmp_path, run_id="r1").to_dict()
    assert doc["run_id"] == "r1"
    assert doc["output_root"] == str(tmp_path)
