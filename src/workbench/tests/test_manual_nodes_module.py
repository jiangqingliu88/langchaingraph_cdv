"""人工节点编辑模块。

用**真清单 + 真样例**（`config/ide/manual_nodes.yaml`）建模块，不打桩 —— 固定
「绑定 ide.manual_nodes 通、清单 input 解析对、编辑器载入文本、校验通过」。
再模拟改坏一处，固定「实时校验真的会报错 + 双击跳转找得到行」。

不建整窗口：本模块不依赖别的模块，也不需要平台布局。
"""
from __future__ import annotations

from pathlib import Path

import pytest

MODULE_ID = "ide.manual_nodes"


def _shipped_spec():
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == MODULE_ID)
    return spec, manifest, manifest_path


def _module(spec, manifest, manifest_path, settings, qt_app):
    from .conftest import make_ctx
    from ..modules.ide.manual_nodes import ManualNodesModule

    ctx = make_ctx(manifest, manifest_path, settings)
    mod = ManualNodesModule(ctx, spec)
    widget = mod.create_widget()
    return mod, widget


@pytest.fixture
def module(qt_app, settings):
    spec, manifest, manifest_path = _shipped_spec()
    mod, widget = _module(spec, manifest, manifest_path, settings, qt_app)
    mod.load(str(Path(manifest_path).parent / spec.input))   # 模拟清单 input 载入
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


class TestLoadAndValidate:
    def test_loads_shipped_example(self, module):
        assert "nodes:" in module.editor.text()
        assert module.path is not None and module.path.name == "manual_nodes.yaml"

    def test_example_validates_clean(self, module):
        module._revalidate()
        assert [i for i in module.issues if i.is_error] == []
        assert "校验通过" in module.status.text()

    def test_panel_shows_no_errors(self, module):
        module._revalidate()
        assert module.panel.model.rowCount() == 0

    def test_not_dirty_after_load(self, module):
        assert module.editor.dirty is False
        assert module.can_close() is True


class TestLiveValidation:
    def test_breaking_a_node_surfaces_an_error(self, module):
        """把一行的 kind 改成非法值 —— 手动触发校验就该报出来。"""
        text = module.editor.text().replace("    kind: review", "    kind: bogus")
        module.editor.set_text(text)
        module._revalidate()
        assert "invalid_enum" in {i.rule for i in module.issues}
        assert module.panel.model.rowCount() > 0

    def test_status_line_counts_errors(self, module):
        module.editor.set_text("nodes:\n  - {title: 没 id}\n")
        module._revalidate()
        assert "1 error" in module.status.text()

    def test_empty_text_is_not_an_error(self, module):
        module.editor.set_text("")
        module._revalidate()
        assert module.issues == []
        assert "空" in module.status.text()

    def test_unknown_key_reported(self, module):
        module.editor.set_text("nodes:\n  - {id: a, typo: 1}\n")
        module._revalidate()
        assert any(i.rule == "unknown_property" for i in module.issues)


class TestDirtyGuard:
    def test_typing_marks_dirty(self, module):
        module.editor.insertPlainText("# 改一下\n")
        assert module.editor.dirty is True
        assert module._dirty_label.text() == "● 未保存"

    def test_can_close_false_when_dirty(self, qt_app, settings, monkeypatch):
        spec, manifest, manifest_path = _shipped_spec()
        mod, widget = _module(spec, manifest, manifest_path, settings, qt_app)
        try:
            mod.load(str(Path(manifest_path).parent / spec.input))
            mod.editor.insertPlainText("# dirty\n")
            # 不弹模态框 —— 直接看守卫有没有拦（_confirm_discard 会 exec 对话框）
            monkeypatch.setattr(mod, "_confirm_discard", lambda: False)
            assert mod.can_close() is False
            monkeypatch.setattr(mod, "_confirm_discard", lambda: True)
            assert mod.can_close() is True
        finally:
            widget.deleteLater()
            qt_app.processEvents()


class TestGotoIssue:
    def test_needle_extraction(self):
        from ..modules.ide.decl_editor import _needle_of

        assert _needle_of("manual_nodes.yaml::nodes[0].kind") == "kind"
        assert _needle_of("manual_nodes.yaml::nodes[0]") == "nodes"
        assert _needle_of("manual_nodes.yaml::<root>") == "<root>"
        assert _needle_of("") == ""

    def test_double_click_finds_the_offending_line(self, module):
        module.editor.set_text(
            "version: 1\nnodes:\n  - id: a\n    kind: wat\n")
        module._revalidate()
        issue = next(i for i in module.issues if i.rule == "invalid_enum")
        module.goto_issue(issue)
        # kind 在第 4 行 —— 跳转后光标应落在那一行
        assert module.editor.cursor_position()[0] == 4


class TestMissingInput:
    def test_missing_file_is_loud(self, qt_app, settings):
        spec, manifest, manifest_path = _shipped_spec()
        spec = spec.model_copy(update={"input": "ide/nope.yaml"})
        mod, widget = _module(spec, manifest, manifest_path, settings, qt_app)
        try:
            # 清单 input 不存在时平台不会自动载入；模块自己不该崩
            assert mod.editor.text() == ""
            mod.show_warning("找不到人工节点：ide/nope.yaml")
            assert mod.banner.is_showing
        finally:
            widget.deleteLater()
            qt_app.processEvents()


class TestHumanEditIsRecorded:
    """保存之后必须**记账** —— 这是"改了有没有痕迹"唯一的那条线。

    L2 那边的语义（链怎么续写、篡改怎么被发现、为什么不能塞进运行链）在
    `tests/test_human_edit_evidence.py` 里测透；这里只钉**接线**：写盘之后到底
    有没有带着"文件 + 理由"去调记账。
    """

    def test_saving_records_the_edit_with_the_reason(self, module, monkeypatch):
        calls = []
        monkeypatch.setattr(module, "record_human_edit",
                            lambda path, reason="": calls.append((str(path), reason))
                            or {"seq": 7, "author": "jiang"})
        module.reason_edit.setText("超时从 600 改成 900")

        assert module.save_model() is True

        assert calls == [(str(module.path), "超时从 600 改成 900")]

    def test_the_reason_does_not_leak_to_the_next_save(self, module, monkeypatch):
        """理由跟着**这一次**保存走 —— 留着的话下一笔会带着上次的说明入账。"""
        monkeypatch.setattr(module, "record_human_edit",
                            lambda path, reason="": {"seq": 1, "author": "j"})
        module.reason_edit.setText("第一次")
        module.save_model()
        assert module.reason_edit.text() == ""

    def test_the_status_line_shows_the_chain_position(self, module, monkeypatch):
        """"已保存 / 已记账"经 `set_status` 走**平台状态栏**（窗口底部）。

        模块自己那个 `status` 标签是校验结果的落点（`_revalidate` 直接 setText），
        两处不是一回事 —— 断言错地方会得出"没记账"的假结论。
        """
        monkeypatch.setattr(module, "record_human_edit",
                            lambda path, reason="": {"seq": 12, "author": "jiang"})
        seen = []
        monkeypatch.setattr(module, "set_status", seen.append)

        module.save_model()

        assert any("已记账 #12" in s and "jiang" in s for s in seen), seen

    def test_a_failed_recording_is_loud(self, module, monkeypatch):
        """记账失败**必须说出来** —— 静默失败等于那个洞还在。

        换的是 `run_tool`（基类实现真正去调工具的那一步），**不能**把
        `record_human_edit` 整个替换掉 —— 那样连要验的警告逻辑一起换没了。
        """
        monkeypatch.setattr(module, "run_tool",
                            lambda *a, **kw: {"recorded": False, "error": "盘写不进去"})

        module.save_model()

        assert module.banner.is_showing
        assert "没有记进证据链" in module.banner.text()


class TestBinding:
    def test_binding_is_registered_and_pure(self):
        from ..bridge.catalog import by_name

        binding = by_name("ide.manual_nodes")
        assert binding is not None
        assert binding.kind == "json"
        assert binding.pure is True

    def test_input_resolves_under_config(self):
        spec, _manifest, manifest_path = _shipped_spec()
        resolved = (Path(manifest_path).parent / spec.input).resolve()
        assert resolved.exists(), resolved
        assert resolved.name == "manual_nodes.yaml"

    def test_module_lands_in_ide_group(self):
        spec, _manifest, _path = _shipped_spec()
        assert spec.group == "ide"
