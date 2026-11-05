"""case 建模模块的 YAML 编辑器 —— 打开 / 改 / 保存。

原在 `src/layers/l3_decision/casemodel/tests/test_editor.py`，随界面一起迁到工作台。

最要紧的两条不变式：
  1. **保存不改动原文** —— 注释、键顺序、别名写法都原样保留。
     这是选文本编辑器而不是表单编辑器的全部理由（归一化是有损的）。
  2. **刷新不碰文本** —— 其它页面刷新分析结果时，绝不允许覆盖用户正在编的内容。
"""
from __future__ import annotations

import shutil

import pytest

from .conftest import CPU, FC, FC_REAL, load_into, type_into


def _module_module():
    """模块所在的 python 模块 —— 弹窗/文件对话框都从它上面拦。"""
    from src.workbench.modules.verify.casemodel import module as module_module
    return module_module


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """一份可写的模型副本 + 被拦下的弹窗。"""
    target = tmp_path / "model.yaml"
    shutil.copy(CPU, target)
    calls = {"question": [], "critical": [], "information": [], "answer": None}
    monkeypatch.setattr(
        _module_module().QMessageBox, "question",
        staticmethod(lambda *a, **k: (calls["question"].append(a),
                                      calls["answer"])[1]))
    monkeypatch.setattr(_module_module().QMessageBox, "critical",
                        staticmethod(lambda *a, **k: calls["critical"].append(a)))
    monkeypatch.setattr(_module_module().QMessageBox, "information",
                        staticmethod(lambda *a, **k: calls["information"].append(a)))
    return target, calls


def _yes():
    from PySide6.QtWidgets import QMessageBox
    return QMessageBox.StandardButton.Yes


def _no():
    from PySide6.QtWidgets import QMessageBox
    return QMessageBox.StandardButton.No


def _status(casemodel) -> str:
    """模块的状态消息现在落在**平台的状态栏**上（它归窗口管）。"""
    return casemodel.ctx.window.status_label.text()


# ════════════════════════════════════════════════════════════
# 位置与加载
# ════════════════════════════════════════════════════════════

def test_editor_loads_file_text_verbatim(casemodel_empty, sandbox):
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    assert casemodel_empty.editor.get_text() == target.read_text(encoding="utf-8")
    assert not casemodel_empty.editor.dirty


def test_editor_no_spurious_trailing_newline(casemodel_empty, sandbox):
    """"载入 → 直接保存" 必须逐字节相同（结尾换行也不能变）。"""
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    before = target.read_text(encoding="utf-8")
    assert casemodel_empty.save_model() is True
    assert target.read_text(encoding="utf-8") == before


def test_editor_reports_line_count_and_schema(casemodel_empty, sandbox):
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    assert "校验通过" in casemodel_empty.editor.status.text()
    assert "行" in casemodel_empty.editor.status.text()


# ════════════════════════════════════════════════════════════
# 脏标记
# ════════════════════════════════════════════════════════════

def test_typing_marks_dirty_on_the_tab_title(casemodel_empty, sandbox):
    """脏状态标在**标签页标题**上，不是窗口标题 —— 窗口是整个工作台的，
    而没存的是这**一个**模块。同时开着几个模块时，这个区别才有用。"""
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    type_into(casemodel_empty.editor, "# 我加的一行注释\n")
    assert casemodel_empty.editor.dirty
    assert "●" in _module_tab_title(casemodel_empty)
    assert "未保存" in _status(casemodel_empty)


def _module_tab_title(casemodel) -> str:
    """本模块所在子窗口的标题 —— 走它自己的窗口，别借别的夹具的。"""
    window = casemodel.ctx.window
    for sub in window.workspace.subwindows_of(casemodel.module_id):
        return sub.windowTitle()
    return ""


def test_saving_clears_dirty(casemodel_empty, sandbox):
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    type_into(casemodel_empty.editor, "# 一行\n")
    assert casemodel_empty.editor.dirty
    assert casemodel_empty.save_model() is True
    assert not casemodel_empty.editor.dirty
    assert "●" not in _module_tab_title(casemodel_empty)
    assert "未保存" not in _status(casemodel_empty)


def test_set_text_does_not_count_as_user_edit(casemodel_empty, sandbox):
    """载入/替换文本算「与磁盘一致」，不该标脏 —— 否则一打开就提示未保存。"""
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    casemodel_empty.editor.set_text("object: X\nobject_code: XX\n")
    assert not casemodel_empty.editor.dirty


def test_editor_widget_dirty_flag(qt_app):
    """控件层：Qt 的 document().isModified() 够可靠，不必自己记标志。"""
    from src.workbench.ui.editors.yaml import YamlEditor
    editor = YamlEditor()
    editor.set_text("object: X\ndimensions: []\n")
    assert editor.text() == "object: X\ndimensions: []\n"   # 不多不少一个换行
    assert not editor.dirty
    cursor = editor.textCursor()
    cursor.insertText("# x\n")
    assert editor.dirty
    editor.mark_clean()
    assert not editor.dirty


def test_editor_tab_inserts_spaces(qt_app):
    """Tab 插两个空格 —— YAML 缩进敏感，别让 Tab 跳出焦点。"""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from src.workbench.ui.editors.yaml import YamlEditor
    editor = YamlEditor()
    editor.set_text("a: 1")
    editor.moveCursor(editor.textCursor().MoveOperation.End)   # 像用户那样在末尾敲
    editor.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab,
                                   Qt.KeyboardModifier.NoModifier))
    assert editor.text() == "a: 1  "


# ════════════════════════════════════════════════════════════
# 保存保真 —— 选文本编辑器的全部理由
# ════════════════════════════════════════════════════════════

def test_save_preserves_comments_and_key_order(casemodel_empty, sandbox):
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    type_into(casemodel_empty.editor, "# 顶部注释：这段必须活下来\n")
    assert casemodel_empty.save_model() is True
    disk = target.read_text(encoding="utf-8")
    assert disk.startswith("# 顶部注释：这段必须活下来")
    assert "object: CpuPipeline" in disk


def test_save_preserves_raw_aliases(casemodel_empty, sandbox):
    """别名写法也要原样保留 —— 归一化会把 RANDOM 改写成 RND，但我们不归一化。"""
    target, _calls = sandbox
    raw = ("object: X\nobject_code: XX\n"
           "methods: [RANDOM, 定向]\n"          # 宽松写法，解析后是 RND / D
           "checks: [功能]\n"
           "dimensions:\n  - name: D\n    fields:\n"
           "      - {name: f, type: enum, values: [a]}\n")
    target.write_text(raw, encoding="utf-8")
    load_into(casemodel_empty, target)
    assert casemodel_empty.result is not None                # 宽松写法能解析
    assert casemodel_empty.result.model.methods == ["RND", "D"]
    # schema 与归一层对「别名算不算合法」必须给同一个答案 —— 否则这里会弹窗
    assert not [i for i in casemodel_empty.schema_issues if i.is_error]
    assert casemodel_empty.save_model() is True
    disk = target.read_text(encoding="utf-8")
    assert "RANDOM" in disk and "RND" not in disk     # 原文没被改写
    assert "定向" in disk


def test_save_reanalyzes_automatically(casemodel_empty, sandbox):
    target, calls = sandbox
    load_into(casemodel_empty, target)
    before = casemodel_empty.result.score.total
    type_into(casemodel_empty.editor, "# 注释不影响语义\n")
    assert casemodel_empty.save_model() is True
    assert casemodel_empty.result.score.total == before
    assert "已保存" in _status(casemodel_empty)
    assert not calls["critical"]


# ════════════════════════════════════════════════════════════
# 保存前校验
# ════════════════════════════════════════════════════════════

def test_save_asks_before_writing_schema_errors(casemodel_empty, sandbox):
    target, calls = sandbox
    load_into(casemodel_empty, target)
    casemodel_empty.editor.set_text("object: CpuPipeline\nobject_code: XX\nwidht: 1\n")
    type_into(casemodel_empty.editor, "# dirty\n")
    before = target.read_text(encoding="utf-8")

    calls["answer"] = _no()
    assert casemodel_empty.save_model() is False
    assert target.read_text(encoding="utf-8") == before      # 没写
    assert calls["question"]                                 # 问过了
    assert "取消" in _status(casemodel_empty)

    calls["answer"] = _yes()
    assert casemodel_empty.save_model() is True              # 选「是」就写
    assert "widht" in target.read_text(encoding="utf-8")


def test_editor_status_shows_schema_errors(casemodel_empty, sandbox):
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    casemodel_empty.editor.set_text("object: X\nobject_code: XX\nwidht: 1\n")
    type_into(casemodel_empty.editor, "# dirty\n")
    casemodel_empty.reanalyze()
    status = casemodel_empty.editor.status.text()
    assert "schema" in status and "error" in status


# ════════════════════════════════════════════════════════════
# 重新分析用未保存的文本
# ════════════════════════════════════════════════════════════

def test_reanalyze_uses_unsaved_text(casemodel_empty, sandbox):
    """「改一行、马上知道它坏了哪条规则」—— 不保存也能分析。"""
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    before = casemodel_empty.result.score.total
    casemodel_empty.editor.set_text(
        casemodel_empty.editor.get_text().replace("priority: P2", "priority: P4"))
    type_into(casemodel_empty.editor, "# 触发 dirty\n")
    casemodel_empty.reanalyze()
    assert casemodel_empty.result.score.total != before
    assert any(i.rule == "theme_priority_gap"
               for i in casemodel_empty.result.model_issues)
    assert "P4" not in target.read_text(encoding="utf-8")    # 确实没写盘


# ════════════════════════════════════════════════════════════
# 构不出模型时的兜底
# ════════════════════════════════════════════════════════════

def test_unbuildable_text_keeps_last_result_and_shows_banner(casemodel_empty,
                                                             sandbox):
    """改到一半构不出模型时保留上次结果 + 红条说明，而不是一片空白。"""
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    good = casemodel_empty.result.score.total
    casemodel_empty.editor.set_text("object: [1, 2]\ndimensions: []\n")
    type_into(casemodel_empty.editor, "# dirty\n")
    casemodel_empty.reanalyze()
    assert casemodel_empty.result is not None
    assert casemodel_empty.result.score.total == good
    assert "构不出模型" in casemodel_empty.banner.text()
    assert not casemodel_empty.banner.isHidden()
    assert casemodel_empty.editor.get_text().startswith("# dirty")   # 文本没被清


def test_banner_clears_after_text_is_fixed(casemodel_empty, sandbox):
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    casemodel_empty.editor.set_text("object: [1, 2]\ndimensions: []\n")
    type_into(casemodel_empty.editor, "# dirty\n")
    casemodel_empty.reanalyze()
    assert casemodel_empty.banner.text()
    casemodel_empty.editor.set_text(target.read_text(encoding="utf-8"))
    type_into(casemodel_empty.editor, "# dirty\n")
    casemodel_empty.reanalyze()
    assert casemodel_empty.banner.text() == ""


def test_empty_editor_clears_pages_instead_of_crashing(casemodel_empty, sandbox):
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    assert casemodel_empty.pages["Case 属性表"].model.rowCount() > 0
    casemodel_empty.editor.set_text("")
    casemodel_empty.reanalyze()
    assert casemodel_empty.result is None
    assert "空的" in casemodel_empty.banner.text()
    assert casemodel_empty.pages["Case 属性表"].model.rowCount() == 0   # 页面已清空


# ════════════════════════════════════════════════════════════
# 刷新不碰文本
# ════════════════════════════════════════════════════════════

def test_refresh_never_touches_the_editor_text(casemodel_empty, sandbox):
    """其它页面刷新时绝不能覆盖用户正在编的内容。"""
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    assert casemodel_empty.editor.get_text() == target.read_text(encoding="utf-8")
    casemodel_empty.refresh()
    assert casemodel_empty.editor.get_text() == target.read_text(encoding="utf-8")

    type_into(casemodel_empty.editor, "# 编到一半\n")
    marked = casemodel_empty.editor.get_text()
    casemodel_empty.refresh()
    assert casemodel_empty.editor.get_text() == marked


# ════════════════════════════════════════════════════════════
# 另存为 / 关闭提醒
# ════════════════════════════════════════════════════════════

def test_save_as_writes_new_path(casemodel_empty, sandbox, tmp_path, monkeypatch):
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    out = tmp_path / "copy.yaml"
    monkeypatch.setattr(_module_module().QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    type_into(casemodel_empty.editor, "# 另存的一份\n")
    assert casemodel_empty.save_model_as() is True
    assert out.read_text(encoding="utf-8").startswith("# 另存的一份")
    assert casemodel_empty.path == out
    assert not casemodel_empty.editor.dirty


def test_save_without_path_falls_back_to_save_as(casemodel_empty, sandbox,
                                                 tmp_path, monkeypatch):
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    out = tmp_path / "new.yaml"
    monkeypatch.setattr(_module_module().QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    casemodel_empty.path = None                      # 模拟「未命名」
    assert casemodel_empty.save_model() is True
    assert out.exists()


def test_save_as_cancel_writes_nothing(casemodel_empty, sandbox, monkeypatch):
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    monkeypatch.setattr(_module_module().QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))   # 用户取消
    type_into(casemodel_empty.editor, "# 未保存\n")
    assert casemodel_empty.save_model_as() is False
    assert casemodel_empty.editor.dirty                          # 还是脏的


def test_close_prompts_only_when_dirty(casemodel_empty, sandbox, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    assert casemodel_empty._confirm_discard() is True            # 干净 → 不问

    type_into(casemodel_empty.editor, "# 未保存\n")
    asked = []
    real = QMessageBox.StandardButton

    class _Box:
        StandardButton = real          # 模块在调用时读它，替身必须带上

        def __init__(self, *_a, **_k):
            asked.append(1)

        def setWindowTitle(self, *_a):
            pass

        def setText(self, *_a):
            pass

        def setStandardButtons(self, *_a):
            pass

        def setDefaultButton(self, *_a):
            pass

        def exec(self):
            return (real.Cancel if len(asked) == 1 else real.Discard)

    monkeypatch.setattr(_module_module(), "QMessageBox", _Box)
    assert casemodel_empty._confirm_discard() is False           # 取消 → 不继续
    assert casemodel_empty._confirm_discard() is True            # 放弃改动 → 继续
    assert len(asked) == 2


def test_can_close_follows_the_dirty_flag(casemodel_empty, sandbox):
    """平台关窗口时逐个模块问 `can_close()` —— 脏模块要拦得住。"""
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    assert casemodel_empty.can_close() is True

    type_into(casemodel_empty.editor, "# 未保存\n")
    casemodel_empty.mark_clean()
    assert casemodel_empty.can_close() is True
    assert not casemodel_empty.editor.dirty


# ════════════════════════════════════════════════════════════
# 输入来源
# ════════════════════════════════════════════════════════════

def test_input_changed_loads_a_file(casemodel_empty):
    casemodel_empty.on_input_changed(FC)
    assert casemodel_empty.path == FC
    assert casemodel_empty.result is not None


def test_input_changed_on_a_directory_picks_a_model(casemodel_empty):
    """指到目录就自己找一份 —— 免得用户还得把文件名写全。"""
    casemodel_empty.on_input_changed(CPU.parent)
    assert casemodel_empty.path is not None
    assert casemodel_empty.path.suffix in (".yaml", ".yml")


def test_input_changed_on_an_empty_directory_warns(casemodel_empty, tmp_path):
    casemodel_empty.on_input_changed(tmp_path)
    assert casemodel_empty.banner.is_showing
    assert "没有 .yaml" in casemodel_empty.banner.text()


# ════════════════════════════════════════════════════════════
# 真实 case 列表
# ════════════════════════════════════════════════════════════

def test_loading_real_cases_reaches_the_external_page(casemodel_empty, sandbox):
    target, _calls = sandbox
    load_into(casemodel_empty, target)
    page = casemodel_empty.pages["真实 case 核对"]
    assert casemodel_empty.result.external is None

    casemodel_empty.cases_path = FC_REAL
    casemodel_empty.load(str(FC))
    assert casemodel_empty.result.external is not None
    assert page.summary_model.rowCount() > 0
