"""导入产物进 run：source_map 复制、事实汇总、导入后漂移。"""
from __future__ import annotations

import json
from pathlib import Path

from src.tools.humanview.aivm_ir.evidence import (
    copy_ingest_artifacts, ingest_facts,
)


def _spec_dir(tmp: Path) -> Path:
    specs = tmp / "specs" / "npu"
    specs.mkdir(parents=True)
    (specs / "casemodel.yaml").write_text("version: '1'\n", encoding="utf-8")
    (specs / "source_map.json").write_text(json.dumps({
        "schema": "aivm_import_v1", "module": "npu",
        "bins": {"r9": {"kind": "cross"}, "cfg_0": {"kind": "config_enum"}},
        "dropped": [{"reason": "unbound"}],
        "inputs": {"xlsx": "npu.xlsx", "xlsx_sha256": "abc"},
        "outputs": {"casemodel_sha256": "not-the-real-one"},
        "axes": {"sha256": "def", "applied": {"unmatched": [{}, {}]}},
    }), encoding="utf-8")
    return specs


def test_without_source_map_nothing_copied(tmp_path):
    specs = tmp_path / "specs" / "m"
    specs.mkdir(parents=True)
    model = specs / "casemodel.yaml"
    model.write_text("version: '1'\n", encoding="utf-8")
    assert copy_ingest_artifacts(model, tmp_path / "run") == []


def test_copies_source_map_and_model_into_run(tmp_path):
    specs = _spec_dir(tmp_path)
    copied = copy_ingest_artifacts(specs / "casemodel.yaml", tmp_path / "run")
    run = tmp_path / "run" / "inputs"
    assert (run / "source_map.json").is_file()
    assert (run / "casemodel.yaml").is_file()
    assert len(copied) == 2


def test_facts_report_counts_and_drift(tmp_path):
    specs = _spec_dir(tmp_path)
    run = tmp_path / "run"
    copy_ingest_artifacts(specs / "casemodel.yaml", run)
    facts = ingest_facts(run)
    assert facts["available"] is True
    assert facts["bins"] == 2 and facts["bins_by_kind"] == {
        "config_enum": 1, "cross": 1}
    assert facts["dropped"] == 1
    assert facts["unmatched_axis_values"] == 2
    # 导入时的 casemodel_sha256 与 run 里那份对不上 → 漂移
    assert facts["issues"] and facts["issues"][0]["check"] == \
        "casemodel_changed_after_import"


def test_evidence_package_collects_source_map():
    from src.layers.l2_orchestration.evidence.signoff_package import SECTION_FILES

    assert "inputs/source_map.json" in SECTION_FILES["inputs"]
