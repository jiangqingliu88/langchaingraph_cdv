"""M4 默认开关：worklist **默认开**，但只在"账本里已有历史证据"时生效。

为什么不能无条件默认开：全新 run 的账本是空的，"全部未清偿"只是因为还没跑过；
此时 worklist 只含 TP test，会漏掉批次用例 —— 等于把覆盖率砍一半。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.tools.checking.verification_os import write_contract
from src.tools.checking.verification_os.contract_model import Fact, FactBundle
from src.tools.checking.verification_os.ledger import append_bundle

CASE_IR = {"module": "demo", "cases": [{
    "id": "CASE-A",
    "groups": [{"group": "CG-A", "cell": "CELL-A-P0",
                "required_layers": ["functional"], "tp_ids": ["TP-1"]}],
    "sva": [], "scb": [], "not_applicable": {},
}]}

TESTPOINTS = {"testpoints": [{
    "tp_id": "TP-1", "case_id": "CASE-A", "coverpoint": "cp_a", "bin": "b0",
    "execution": {"test": "demo_env_d_a_p0_test", "stage": "p0", "seeds": [1]}}]}
REGRESSION = {"tests": [{"name": "tp_1"}]}


def _run(tmp_path: Path, *, with_facts=True) -> Path:
    root = tmp_path / "run_switch_20260101_000000"
    (root / "coverage").mkdir(parents=True)
    (root / "inputs" / "yaml").mkdir(parents=True)
    (root / "coverage" / "case_ir.json").write_text(
        json.dumps(CASE_IR), encoding="utf-8")
    (root / "coverage" / "testpoints.yaml").write_text(
        yaml.safe_dump(TESTPOINTS, allow_unicode=True), encoding="utf-8")
    (root / "inputs" / "yaml" / "regression.yaml").write_text(
        yaml.safe_dump(REGRESSION, allow_unicode=True), encoding="utf-8")
    write_contract(root, CASE_IR)
    if with_facts:
        append_bundle(root, FactBundle(bundle_id="B-1", facts=[
            Fact(type="timing", contract_hash="", subject={"case": "CASE-A"},
                 value={"ok": True})]))
    return root


def _filter(root, params=None, env=None, monkeypatch=None):
    from src.executors.ops.main import _worklist_filter

    if env is not None:
        monkeypatch.setenv("SIGNOFFAI_WORKLIST", env)
    return _worklist_filter(root, params or {})


def test_default_on_when_prior_evidence_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("SIGNOFFAI_WORKLIST", raising=False)
    assert _filter(_run(tmp_path), monkeypatch=monkeypatch)


def test_fresh_run_falls_back_to_full(tmp_path, monkeypatch):
    monkeypatch.delenv("SIGNOFFAI_WORKLIST", raising=False)
    assert _filter(_run(tmp_path, with_facts=False), monkeypatch=monkeypatch) == ""


def test_explicit_off(tmp_path, monkeypatch):
    monkeypatch.delenv("SIGNOFFAI_WORKLIST", raising=False)
    root = _run(tmp_path)
    assert _filter(root, {"worklist": False}, monkeypatch=monkeypatch) == ""
    assert _filter(root, env="off", monkeypatch=monkeypatch) == ""


def test_explicit_on_still_needs_prior_evidence(tmp_path, monkeypatch):
    monkeypatch.delenv("SIGNOFFAI_WORKLIST", raising=False)
    assert _filter(_run(tmp_path, with_facts=False), {"worklist": True},
                   monkeypatch=monkeypatch) == ""
