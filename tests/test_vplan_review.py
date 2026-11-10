"""VPlan 人工审阅门：LLM 抽取表没人看过就不许执行。

审阅记录绑定文件哈希 —— 人工改过任何一张表，旧审阅自动失效。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.layers.l3_decision.vplan import VPlanError
from src.layers.l3_decision.vplan.review import (
    record_review, require_review, review_status)


def _project(tmp_path):
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    (tmp_path / "data" / "contract_matrix").mkdir(parents=True)
    (tmp_path / "cases").mkdir()
    (tmp_path / "docs" / "specs" / "demo_contracts.csv").write_text(
        "contract_id,category,content\nC-1,接口,x\n", encoding="utf-8")
    (tmp_path / "data" / "contract_matrix" / "func.csv").write_text(
        "contract_id,class\nC-1,func\n", encoding="utf-8")
    (tmp_path / "cases" / "TC_1.yaml").write_text(
        "case_id: TC_1\n", encoding="utf-8")
    return SimpleNamespace(root=tmp_path, module="demo")


def test_unreviewed_project_is_blocked(tmp_path):
    project = _project(tmp_path)
    status = review_status(project)
    assert status["reviewed"] is False
    assert set(status["unreviewed"]) == {"docs_specs", "data", "cases"}
    with pytest.raises(VPlanError, match="人工审阅"):
        require_review(project)


def test_review_then_edit_invalidates_it(tmp_path):
    project = _project(tmp_path)
    manifest = record_review(project, "jiang", "接口/契约已核对")
    assert manifest["reviewed"] is True
    assert review_status(project)["reviewed"] is True
    require_review(project)                      # 通过

    # 人工改表 → 哈希变化 → 旧审阅自动失效
    (tmp_path / "data" / "contract_matrix" / "func.csv").write_text(
        "contract_id,class\nC-1,func\nC-2,func\n", encoding="utf-8")
    status = review_status(project)
    assert status["reviewed"] is False
    assert status["stale"] == ["data"]
    with pytest.raises(VPlanError, match="审阅后又改过"):
        require_review(project)

    record_review(project, "jiang")              # 重新审阅
    assert review_status(project)["reviewed"] is True


def test_generated_data_sidecar_does_not_invalidate_review(tmp_path):
    """生成 sidecar（dimensions/execution_meta）变化不该让语义审阅过期。"""
    project = _project(tmp_path)
    record_review(project, "jiang")
    assert review_status(project)["reviewed"] is True

    (tmp_path / "data" / "dimensions.csv").write_text(
        "dimension_id\nD_x\n", encoding="utf-8")
    status = review_status(project)
    assert status["reviewed"] is True
    assert "data/dimensions.csv" in status["skipped_generated"]

    # 权威契约矩阵变化仍然必须使审阅过期。
    (tmp_path / "data" / "contract_matrix" / "func.csv").write_text(
        "contract_id,class\nC-1,func\nC-2,func\n", encoding="utf-8")
    assert review_status(project)["reviewed"] is False


def test_review_requires_a_reviewer(tmp_path):
    project = _project(tmp_path)
    with pytest.raises(ValueError, match="审阅人"):
        record_review(project, "  ")


def test_unreviewed_can_be_explicitly_bypassed_for_dev(tmp_path, monkeypatch):
    project = _project(tmp_path)
    monkeypatch.setenv("SIGNOFFAI_ALLOW_UNREVIEWED", "1")
    require_review(project)                      # 显式跳过，不抛
