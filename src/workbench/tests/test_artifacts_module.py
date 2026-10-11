"""产物审查台 —— 看清楚、改对、记上账。

这一页存在的唯一理由：卡住运行的是这些中间 YAML，而在此之前它们只以**原始文件
树**的形式存在（看得见文件名，看不出哪份有问题、谁写的、改了会怎样）。实测一次
`bench.yaml` 的 schema 不符让整次运行挂在 verify，从日志挖到生成器才定位到。

三件事要钉住：
  · 清单与诊断**同源**（都走 `flow.artifacts` 背后那个 `SchemaChecker`），
    所以树上那个 ✗ 和面板里列出来的必然一致；
  · 保存**带 run_id 记账** —— 这次编辑属于这次运行，日志里有锚点；
  · 保存**不会自动重跑**，而且界面必须把这句话说出来。
"""
from __future__ import annotations

import json

import pytest

MODULE_ID = "flow.artifacts"

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

#: 旧格式 —— 让整次运行挂在 verify 的那几处（`env_name` / `dut:` / 空 `agents:`）
BAD_BENCH = """bench:
  name: dut_bench
  env_name: dut_env
  agents:
  dut:
    module: dut
    instance: u_dut
"""


def _shipped_spec():
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == MODULE_ID)
    return spec, manifest, manifest_path


@pytest.fixture
def run_dir(tmp_path):
    """一次运行的目录骨架。

    `conftest` 的 `_isolate_cwd` 已经把 cwd 隔离到 tmp_path，而
    `RunRepository("output")` 扫的是 `<cwd>/output/*` 与 `<cwd>/output_*` ——
    所以造的是"前缀式"那一支，模块的反解能认出来。
    """
    root = tmp_path / "output_test_20260101_000000"
    (root / "inputs" / "yaml" / "uvm").mkdir(parents=True)
    (root / "spec.json").write_text('{"design_name": "dut"}', encoding="utf-8")
    (root / "inputs" / "yaml" / "uvm" / "bench.yaml").write_text(
        GOOD_BENCH, encoding="utf-8")
    return root


def _module(qt_app, settings, run_id: str = ""):
    from .conftest import make_ctx
    from ..modules.flow.artifacts import ArtifactsModule

    spec, manifest, manifest_path = _shipped_spec()
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = ArtifactsModule(ctx, spec)
    widget = mod.create_widget()
    mod.run_id = run_id
    return mod, widget


@pytest.fixture
def module(qt_app, settings, run_dir):
    mod, widget = _module(qt_app, settings, run_id=run_dir.name)
    mod.refresh()
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


def _select(module, rel_path: str):
    """按路径选中树上的那一份 —— 走的是界面真的会走的那条路。"""
    module.tree.setCurrentItem(module._nodes[rel_path])


def _retype(module, text: str) -> None:
    """模拟人打字：全选 + 输入。

    **不能用 `editor.set_text()`** —— 那是"载入文件"的语义（会把内容标成与磁盘
    一致），用它测不出「用户改了东西」，`dirty` 永远是 False。
    """
    cursor = module.editor.textCursor()
    cursor.select(cursor.SelectionType.Document)
    cursor.insertText(text)


class TestCatalog:
    def test_lists_what_the_run_produced(self, module):
        assert [i["path"] for i in module.items] == [
            "spec.json", "inputs/yaml/uvm/bench.yaml", "inputs/yaml/regression.yaml",
            # 功能覆盖那一组：模型 / 声明 / env_cov 注入（都是"输入侧"的产物）
            "inputs/casemodel.yaml", "coverage/coverage_points.json",
            "inputs/yaml/uvm/env_cov_bins.yaml"]

    def test_the_tree_is_grouped_by_stage(self, module):
        roots = [module.tree.topLevelItem(i).text(0)
                 for i in range(module.tree.topLevelItemCount())]
        assert roots == ["设计", "验证·UVM", "回归", "功能覆盖"]

    def test_the_header_reports_the_run_and_the_summary(self, module):
        assert "output_test_20260101_000000" in module.summary.text()
        assert "schema 都过" in module.summary.text()

    def test_without_a_run_it_says_where_to_pick_one(self, qt_app, settings):
        mod, widget = _module(qt_app, settings)
        try:
            mod.refresh()
            assert "运行历史" in mod.summary.text()
            assert mod.items == []
        finally:
            widget.deleteLater()
            qt_app.processEvents()


class TestSelection:
    def test_selecting_loads_the_text(self, module):
        _select(module, "inputs/yaml/uvm/bench.yaml")
        assert module.path is not None and module.path.name == "bench.yaml"
        assert "dut_instance: u_dut" in module.editor.text()
        assert module.editor.isReadOnly() is False

    def test_the_head_says_what_this_is(self, module):
        _select(module, "inputs/yaml/uvm/bench.yaml")
        head = module.head.text()
        assert "bench.yaml" in head and "验证·UVM" in head
        assert "sha256" in head

    def test_an_ungenerated_artifact_cannot_be_opened(self, module):
        """`regression.yaml` 这次没有 → 说清楚"还没生成"，而不是打开一个空编辑器。"""
        _select(module, "inputs/yaml/regression.yaml")
        assert module.path is None
        assert "还没生成" in module.head.text()

    def test_a_missing_artifact_shows_as_such_on_the_tree(self, module):
        node = module._nodes["inputs/yaml/regression.yaml"]
        assert node.text(1) == "还没生成"

    def test_refreshing_keeps_you_on_the_same_file(self, module):
        """刷新一下就把人正在看的文件弹掉的界面是没法用的。"""
        _select(module, "inputs/yaml/uvm/bench.yaml")
        module.refresh()
        assert module.path is not None and module.path.name == "bench.yaml"


class TestDiagnostics:
    def test_a_clean_file_has_no_issues(self, module):
        _select(module, "inputs/yaml/uvm/bench.yaml")
        assert module.panel.model.rowCount() == 0
        assert "schema 校验通过" in module.status.text()

    def test_a_broken_file_lists_its_issues(self, qt_app, settings, run_dir):
        (run_dir / "inputs" / "yaml" / "uvm" / "bench.yaml").write_text(
            BAD_BENCH, encoding="utf-8")
        mod, widget = _module(qt_app, settings, run_id=run_dir.name)
        try:
            mod.refresh()
            _select(mod, "inputs/yaml/uvm/bench.yaml")
            assert mod.panel.model.rowCount() > 0
            assert "错误" in mod.status.text()
        finally:
            widget.deleteLater()
            qt_app.processEvents()

    def test_the_tree_marks_the_broken_one(self, qt_app, settings, run_dir):
        (run_dir / "inputs" / "yaml" / "uvm" / "bench.yaml").write_text(
            BAD_BENCH, encoding="utf-8")
        mod, widget = _module(qt_app, settings, run_id=run_dir.name)
        try:
            mod.refresh()
            node = mod._nodes["inputs/yaml/uvm/bench.yaml"]
            assert node.text(1).startswith("✗")
        finally:
            widget.deleteLater()
            qt_app.processEvents()

    def test_the_panel_speaks_chinese_severity(self, qt_app, settings, run_dir):
        """面板的"严重度"一栏靠 `severity_cn` —— 不适配的话那一栏是空白，
        而它正是用来一眼扫出"有没有 error"的。"""
        (run_dir / "inputs" / "yaml" / "uvm" / "bench.yaml").write_text(
            BAD_BENCH, encoding="utf-8")
        mod, widget = _module(qt_app, settings, run_id=run_dir.name)
        try:
            mod.refresh()
            _select(mod, "inputs/yaml/uvm/bench.yaml")
            assert mod.panel.model.counts().get("error", 0) > 0
            issue = mod.panel.model.issue_at(0)
            assert issue.severity_cn == "错误"
        finally:
            widget.deleteLater()
            qt_app.processEvents()


class TestEditing:
    def test_editing_marks_the_tab_and_the_tree(self, module):
        _select(module, "inputs/yaml/uvm/bench.yaml")
        _retype(module, "bench:\n  name: x\n")
        assert module.editor.dirty is True
        assert "●" in module.save_btn.text()

    def test_can_close_is_false_while_dirty(self, module):
        _select(module, "inputs/yaml/uvm/bench.yaml")
        assert module.can_close() is True
        _retype(module, "bench:\n")
        assert module.can_close() is False

    def test_mark_clean_clears_it(self, module):
        _select(module, "inputs/yaml/uvm/bench.yaml")
        _retype(module, "bench:\n")
        module.mark_clean()
        assert module.editor.dirty is False and module.can_close() is True


class TestSave:
    """保存 = 写回 + 记账。**记账带 run_id** —— 这次编辑属于这次运行。"""

    @staticmethod
    def _prepare(module, monkeypatch, text=None):
        _select(module, "inputs/yaml/uvm/bench.yaml")
        module._scope_ack = True          # 跳过"改的是运行产物"那一次确认
        if text is not None:
            _retype(module, text)
        monkeypatch.setattr(module, "run_tool", lambda *a, **kw: {
            "recorded": True, "seq": 3, "author": "jiang",
            "file": "inputs/yaml/uvm/bench.yaml"})

    def test_the_file_is_written_back(self, module, monkeypatch):
        self._prepare(module, monkeypatch, "bench:\n  name: 改过了\n")
        assert module.save_artifact() is True
        assert "改过了" in module.path.read_text(encoding="utf-8")

    def test_it_records_with_the_run_id(self, module, monkeypatch):
        """**带 run_id** —— 这一条是这一页独有的：人工节点页改的是静态配置，
        没有运行可挂；这里改的是某次运行的产物，锚点是天然的。"""
        self._prepare(module, monkeypatch, "bench:\n  name: x\n")
        calls = []

        def spy(name=None, *, quiet=False, force=False, **kw):
            calls.append((name, kw))
            return {"recorded": True, "seq": 3, "author": "jiang"}

        monkeypatch.setattr(module, "run_tool", spy)
        module.reason_edit.setText("修 harness")
        module.save_artifact()

        # 保存之后会 refresh（重列产物），所以找**那一次**记账调用，不是最后一次
        recorded = [kw for name, kw in calls if name == "evidence.record_human_edit"]
        assert recorded, [name for name, _ in calls]
        assert recorded[0]["run_id"] == module.run_id
        assert recorded[0]["reason"] == "修 harness"

    def test_the_reason_does_not_leak_to_the_next_save(self, module, monkeypatch):
        self._prepare(module, monkeypatch, "bench:\n  name: x\n")
        module.reason_edit.setText("第一次")
        module.save_artifact()
        assert module.reason_edit.text() == ""

    def test_saving_clears_the_dirty_flag(self, module, monkeypatch):
        self._prepare(module, monkeypatch, "bench:\n  name: x\n")
        module.save_artifact()
        assert module.editor.dirty is False

    def test_it_says_the_change_needs_a_rerun(self, module, monkeypatch):
        """**不许让人以为改完就生效。** 改的是那次运行目录里的文件。"""
        self._prepare(module, monkeypatch, "bench:\n  name: x\n")
        seen = []
        monkeypatch.setattr(module, "set_status", seen.append)
        module.save_artifact()
        assert any("重跑" in s for s in seen), seen

    def test_a_chain_record_is_actually_written(self, module, qt_app, monkeypatch):
        """走**真的**记账（不替换工具）：链落在 cwd 的 `.signoffai/` 下，
        仓库里那条不会被动到 —— `_isolate_cwd` 保证这一点。"""
        from pathlib import Path

        _select(module, "inputs/yaml/uvm/bench.yaml")
        module._scope_ack = True
        module.editor.set_text("bench:\n  name: 人工改过\n")
        module.reason_edit.setText("测试记账")
        assert module.save_artifact() is True

        chain = Path(".signoffai") / "human_edits.json"
        assert chain.is_file(), "记账没落盘"
        record = json.loads(chain.read_text(encoding="utf-8"))["records"][-1]
        assert record["file_path"].endswith("inputs/yaml/uvm/bench.yaml")
        assert record["reason"] == "测试记账"
        assert record["agent"].startswith("human:")

    def test_the_diagnostics_do_not_leak_the_temp_file_name(self, qt_app, settings, run_dir):
        """校验器吃的是文件，所以它会把**临时文件的名字**写进诊断里。

        不换回来的话，人会在诊断里看到一个 `tmpab12cd.yaml` —— 一个盘上根本不存在
        的文件，还得自己猜它是哪一份。
        """
        (run_dir / "inputs" / "yaml" / "uvm" / "bench.yaml").write_text(
            BAD_BENCH, encoding="utf-8")
        mod, widget = _module(qt_app, settings, run_id=run_dir.name)
        try:
            mod.refresh()
            _select(mod, "inputs/yaml/uvm/bench.yaml")
            issue = mod.panel.model.issue_at(0)
            assert "tmp" not in issue.target
            assert "bench.yaml" in issue.target
            assert "tmp" not in issue.message
        finally:
            widget.deleteLater()
            qt_app.processEvents()
