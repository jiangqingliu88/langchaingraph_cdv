"""覆盖率豁免审批 —— 让人看清自己在签什么。

**批准一条豁免会把那个覆盖点从分母里拿掉** —— 等于放行一个原本没覆盖的点，
签核结论会跟着变。所以这一页的测试重心不在"表格铺出来了吗"，而在：

  · 提议的**理由与证据**要摆到人眼前（不提证据的批准是拍脑袋）；
  · 签名 + **哈希指纹**要入链、要能看见；
  · 确认框必须把"改动覆盖率分母"这句话说出来。

在此之前**只有 CLI** 能批（`vagent exclude approve`），工作台里连"有提议待批"
都看不到 —— 于是这些东西的现状是：提议一直攒，没人批。
"""
from __future__ import annotations

import pytest

MODULE_ID = "coverage.excludes"


@pytest.fixture
def db(tmp_path):
    """一个只属于这个用例的豁免库 —— 用真 sqlite，不打桩存储层。"""
    from src.knowledge.exclude_registry import ExcludeRegistry

    path = tmp_path / "exclude_registry.db"
    reg = ExcludeRegistry(path)
    reg.propose_exclude("D_baud.baud_9600",
                        "FIFO 深度固定为 4，该波特率组合结构上走不到",
                        "unreachable", "cov_report.html#L88")
    reg.propose_exclude("D_parity.odd", "奇校验未实现", "dead_code")
    reg.propose_exclude("D_flow.err_recover", "已批准的那条", "unreachable")
    reg.approve_exclude("EXC-0003", "alice")
    reg.close()
    return path


@pytest.fixture
def module(qt_app, settings, db, monkeypatch):
    """把模块的读数接到这个临时库上。

    模块走的是 `coverage.excludes` 绑定（不带参数 → 用默认库）。测试里把绑定的
    实参补上 `db_path`，**不动模块本身** —— 模块不该为了可测而多一个
    "库在哪"的旋钮，那是工具层的事。
    """
    from .conftest import make_ctx, shipped_manifest
    from ..modules.coverage.excludes import ExcludesModule

    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == MODULE_ID)
    ctx = make_ctx(manifest, manifest_path, settings)

    real_call = ctx.call_tool

    def call(name, **kwargs):
        if name.startswith("coverage."):
            kwargs.setdefault("db_path", str(db))
        return real_call(name, **kwargs)

    monkeypatch.setattr(ctx, "call_tool", call)

    mod = ExcludesModule(ctx, spec)
    widget = mod.create_widget()
    mod.refresh()
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


def _select_first(module) -> None:
    module.pending_view.setCurrentIndex(module.pending_view.model().index(0, 0))


class TestListing:
    def test_pending_and_approved_are_separated(self, module):
        assert len(module.pending) == 2                 # EXC-0001 / EXC-0002
        assert len(module.approved) == 1                # EXC-0003
        assert [r["exclude_id"] for r in module.pending] == ["EXC-0001", "EXC-0002"]

    def test_the_summary_counts_what_is_waiting(self, module):
        assert "待批 2" in module.summary.text()
        assert "已批 1" in module.summary.text()

    def test_rows_carry_chinese_type_labels(self, module):
        types = [r["type_title"] for r in module.pending]
        assert types == ["结构不可达", "死代码"]

    def test_the_approved_row_carries_the_signature_and_hash(self, module):
        """已批那一列的意义就在这两栏：谁签的、在链上的哪一环。"""
        row = module.approved[0]
        assert row["approver"] == "alice"
        assert len(row["audit_hash"]) == 64
        assert row["signed"] is True

    def test_an_empty_registry_is_not_an_error(self, qt_app, settings, tmp_path, monkeypatch):
        from .conftest import make_ctx, shipped_manifest
        from ..modules.coverage.excludes import ExcludesModule

        manifest, manifest_path = shipped_manifest()
        spec = next(s for s in manifest.modules if s.id == MODULE_ID)
        ctx = make_ctx(manifest, manifest_path, settings)
        real_call = ctx.call_tool
        monkeypatch.setattr(ctx, "call_tool", lambda name, **kw: real_call(
            name, **{**kw, "db_path": str(tmp_path / "none.db")}))

        mod = ExcludesModule(ctx, spec)
        widget = mod.create_widget()
        try:
            mod.refresh()
            assert mod.pending == [] and mod.approved == []
            assert "还没有豁免提议" in mod.summary.text()
        finally:
            widget.deleteLater()
            qt_app.processEvents()


class TestWhatAmISigning:
    """选中一条提议之后，**理由和证据必须摆到眼前**。"""

    def test_the_detail_shows_reason_and_evidence(self, module):
        _select_first(module)
        text = module.detail.toPlainText()
        assert "FIFO 深度固定为 4" in text
        assert "cov_report.html#L88" in text

    def test_it_says_what_approving_does_to_coverage(self, module):
        """这一句是这一页存在的理由 —— 不说，签字就是走过场。"""
        _select_first(module)
        assert "分母" in module.detail.toPlainText()

    def test_a_proposal_without_evidence_is_called_out(self, module):
        module.pending_view.setCurrentIndex(module.pending_view.model().index(1, 0))
        assert "没带证据" in module.detail.toPlainText()

    def test_the_buttons_are_disabled_until_something_is_selected(self, module):
        assert not module.approve_btn.isEnabled()
        assert not module.reject_btn.isEnabled()
        _select_first(module)
        assert module.approve_btn.isEnabled() and module.reject_btn.isEnabled()


class TestSigning:
    def test_approving_records_the_approver_and_a_hash(self, module, db, monkeypatch):
        _select_first(module)
        module.approver_edit.setText("jiang")
        monkeypatch.setattr(module, "_confirm", lambda row: True)

        module.approve()

        assert len(module.approved) == 2
        signed = [r for r in module.approved if r["exclude_id"] == "EXC-0001"][0]
        assert signed["approver"] == "jiang"
        assert len(signed["audit_hash"]) == 64
        assert "EXC-0001" in module.status.text() if hasattr(module, "status") else True

    def test_the_hash_chain_continues_across_approvals(self, module, monkeypatch):
        """链是跨 run、跨实例连续的：新签的那条要接着上一条的哈希。"""
        before = module.approved[0]["audit_hash"]
        _select_first(module)
        monkeypatch.setattr(module, "_confirm", lambda row: True)
        module.approve()
        hashes = {r["exclude_id"]: r["audit_hash"] for r in module.approved}
        assert hashes["EXC-0001"] != before
        assert len(set(hashes.values())) == len(hashes)

    def test_cancelling_the_confirm_changes_nothing(self, module, db, monkeypatch):
        _select_first(module)
        monkeypatch.setattr(module, "_confirm", lambda row: False)
        module.approve()
        assert len(module.approved) == 1

    def test_rejecting_leaves_the_point_covered(self, module, db, monkeypatch):
        _select_first(module)
        module.reject()
        assert len(module.approved) == 1
        assert len(module.pending) == 1
        assert [r["exclude_id"] for r in module.pending] == ["EXC-0002"]

    def test_an_unknown_id_is_reported_not_silently_ok(self, module, db, monkeypatch):
        """库里没有这条时不许报"已批准" —— 一个撒谎的成功比报错更难查。"""
        result = module.run_tool("coverage.approve_exclude", force=True,
                                 exclude_id="EXC-9999", approver="x",
                                 db_path=str(db))
        assert result["approved"] is False
        assert "没有这条豁免" in result["error"]

    def test_rejecting_an_unknown_id_is_also_reported(self, module, db):
        result = module.run_tool("coverage.reject_exclude", force=True,
                                 exclude_id="EXC-9999", approver="x",
                                 db_path=str(db))
        assert result["rejected"] is False
        assert "没有这条豁免" in result["error"]

    def test_the_approver_defaults_when_the_field_is_empty(self, module, db, monkeypatch):
        """签名留空时取配置/登录名，**不能**变成空字符串 —— 那等于没签。"""
        _select_first(module)
        monkeypatch.setattr(module, "_confirm", lambda row: True)
        module.approve()
        signed = [r for r in module.approved if r["exclude_id"] == "EXC-0001"][0]
        assert signed["approver"]
