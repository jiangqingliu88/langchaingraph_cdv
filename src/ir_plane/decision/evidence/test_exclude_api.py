"""覆盖率豁免的审批面 —— 读 / 批 / 拒。

这一层本身没有判定逻辑（全在 `ExcludeRegistry`），所以测的是**口径**：

  · 批准要留下**签名 + 哈希指纹**（"接证据链"不是句装饰）；
  · 库里没有那条时**不许报成功** —— 一个撒谎的成功比报错更难查；
  · 签名留空要回落到配置/登录名，**不能变成空字符串**（那等于没签）。
"""
from __future__ import annotations

import pytest

from src.knowledge_plane.exclude_registry import ExcludeRegistry
from src.ir_plane.decision.evidence.exclude_api import (approve_exclude, read_excludes,
                                                  reject_exclude)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "exclude_registry.db"
    reg = ExcludeRegistry(path)
    reg.propose_exclude("D_baud.baud_9600", "FIFO 深度固定，走不到", "unreachable",
                        "cov_report.html#L88")
    reg.propose_exclude("D_parity.odd", "奇校验未实现", "dead_code")
    reg.close()
    return path


class TestRead:
    def test_splits_pending_from_approved(self, db):
        report = read_excludes(str(db))
        assert [r["exclude_id"] for r in report["pending"]] == ["EXC-0001", "EXC-0002"]
        assert report["approved"] == []

    def test_the_summary_says_what_is_waiting(self, db):
        assert "待批 2" in read_excludes(str(db))["summary"]

    def test_type_labels_are_translated(self, db):
        types = [r["type_title"] for r in read_excludes(str(db))["pending"]]
        assert types == ["结构不可达", "死代码"]

    def test_an_unknown_type_is_shown_as_is_not_blanked(self, db):
        """界面里出现一个生词，好过出现空白。"""
        reg = ExcludeRegistry(db)
        reg.propose_exclude("X", "y", "某种没人见过的新类型")
        reg.close()
        labels = [r["type_title"] for r in read_excludes(str(db))["pending"]]
        assert "某种没人见过的新类型" in labels

    def test_a_missing_db_is_an_empty_registry_not_an_error(self, tmp_path):
        report = read_excludes(str(tmp_path / "nope.db"))
        assert report["pending"] == [] and report["approved"] == []
        assert "还没有豁免提议" in report["summary"]


class TestApprove:
    def test_it_signs_with_an_audit_hash(self, db):
        result = approve_exclude("EXC-0001", "jiang", db_path=str(db))
        assert result["approved"] is True
        assert result["approver"] == "jiang"
        assert len(result["audit_hash"]) == 64
        assert result["coverage_point"] == "D_baud.baud_9600"

    def test_the_signature_shows_up_in_the_register(self, db):
        approve_exclude("EXC-0001", "jiang", db_path=str(db))
        approved = read_excludes(str(db))["approved"]
        assert approved[0]["approver"] == "jiang"
        assert approved[0]["signed"] is True

    def test_it_leaves_the_pending_list(self, db):
        approve_exclude("EXC-0001", "jiang", db_path=str(db))
        assert [r["exclude_id"] for r in read_excludes(str(db))["pending"]] == ["EXC-0002"]

    def test_an_unknown_id_is_refused_loudly(self, db):
        """**不许报成功。** 库里没有这条却说"已批准"，是界面上一个撒谎的绿灯。"""
        result = approve_exclude("EXC-9999", "jiang", db_path=str(db))
        assert result["approved"] is False
        assert "没有这条豁免" in result["error"]

    def test_an_empty_signature_falls_back_to_a_real_name(self, db):
        """留空要回落 —— 空字符串等于没签，而"谁批的"正是审计的答案。"""
        result = approve_exclude("EXC-0001", "", db_path=str(db))
        assert result["approver"]

    def test_the_chain_continues_across_approvals(self, db):
        first = approve_exclude("EXC-0001", "jiang", db_path=str(db))["audit_hash"]
        second = approve_exclude("EXC-0002", "wang", db_path=str(db))["audit_hash"]
        assert first != second
        assert len(second) == 64


class TestReject:
    def test_it_leaves_the_point_covered(self, db):
        assert reject_exclude("EXC-0001", "jiang", db_path=str(db))["rejected"] is True
        assert [r["exclude_id"] for r in read_excludes(str(db))["pending"]] == ["EXC-0002"]

    def test_an_unknown_id_is_refused_loudly(self, db):
        """`ExcludeRegistry.reject_exclude` 原来无条件返回 True —— UPDATE 命中 0 行
        也报成功。改成看 rowcount，与 `approve_exclude` 口径一致。"""
        result = reject_exclude("EXC-9999", "jiang", db_path=str(db))
        assert result["rejected"] is False
        assert "没有这条豁免" in result["error"]
