"""IP 规格页 —— 编辑 IP 声明 YAML，边写边校验。

用**真清单 + 真示例文件**（`config/ide/ip_spec.yaml`）建模块，不打桩：这条路径
同时固定了三件事 —— 绑定 `ide.ip_spec` 通、清单的 `input` 解析对、
`run_ip_spec` 的返回形状是界面真正吃得下的那种。

与 `test_manual_nodes_module.py` 是同一套编辑器的两个实例（共享件在
`modules/ide/decl_editor.py`）—— 那边测的是编辑器的行为，这边测的是**这一份
声明接对了没有**：schema 选中了 ip_spec 那一份、高亮词表是 IP 的、示例文件真的
能过校验。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QKeySequence, QTextCursor

MODULE_ID = "ide.ip_spec"
TOOL_NAME = "ide.ip_spec"


def _shipped_spec():
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == MODULE_ID)
    return spec, manifest, manifest_path


@pytest.fixture
def module(qt_app, settings):
    from .conftest import make_ctx
    from ..modules.ide.ip_spec import IpSpecModule

    spec, manifest, manifest_path = _shipped_spec()
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = IpSpecModule(ctx, spec)
    widget = mod.create_widget()
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


class TestDeclarationWiring:
    """这一份声明**接对了没有** —— 基类共享，所以接错会静默用到别家的 schema。"""

    def test_uses_the_ip_spec_schema(self):
        """schema 必须选中 ip_spec 那一份（选错就成了拿人工节点的规则校验 IP）。"""
        from src.runtime_plane.tools.integration.ide_tools.api import IP_SPEC

        assert IP_SPEC.schema_path.name == "ip_spec.schema.json"
        assert IP_SPEC.schema_path.exists()

    def test_highlight_vocabulary_is_ips(self):
        """高亮词表得是 IP 的字段/枚举，不是流程节点的。"""
        from ..modules.ide.ip_spec import IpSpecModule

        assert "registers" in IpSpecModule.DECL.skeleton_keys
        assert "ports" in IpSpecModule.DECL.skeleton_keys
        assert "w1c" in IpSpecModule.DECL.enum_values      # register.access
        assert "verified" in IpSpecModule.DECL.enum_values  # ip.status

    def test_shipped_example_validates_clean(self, module):
        """仓库里那份示例必须**真的能过校验** —— 示例本身错了等于给了个坏榜样。"""
        from src.runtime_plane.tools.integration.ide_tools.api import run_ip_spec

        spec, _m, manifest_path = _shipped_spec()
        target = Path(manifest_path).parent / spec.input
        result = run_ip_spec(str(target))
        assert result.get("valid") is True, result.get("issues")


class TestEditing:
    def test_loads_shipped_example(self, module):
        spec, _m, manifest_path = _shipped_spec()
        module.load(str(Path(manifest_path).parent / spec.input))
        assert "apb_uart" in module.editor.text()
        assert module.editor.dirty is False          # 刚打开不算脏

    def test_bad_edit_is_reported_not_silently_accepted(self, module):
        """改坏了要**在界面上报出来** —— 静默接受等于让人存下一份坏规格。"""
        module.load(str(_example_path()))
        module.editor.set_text("ips:\n  - {category: 缺名字}\n")   # name 是必填
        module._revalidate()
        assert any(i.is_error for i in module.issues)

    def test_editing_marks_dirty(self, module):
        """改一下就得标脏。

        **不能拿 `set_text` 模拟输入** —— 它的语义是「载入并标记为与磁盘一致」
        （内部 `setModified(False)`），用它当输入永远标不脏。要走 Qt 的编辑 API。
        """
        module.load(str(_example_path()))
        _type(module, "\n")
        assert module.editor.dirty is True

    def test_can_close_blocks_on_dirty(self, module, monkeypatch):
        """有未保存改动时必须拦一道 —— 返回 False 表示「别关」。"""
        module.load(str(_example_path()))
        _type(module, "\n")
        assert module.editor.dirty is True, "前提没成立：得先真的标脏"
        monkeypatch.setattr(module, "_confirm_discard", lambda: False)
        assert module.can_close() is False

    def test_save_writes_back_verbatim(self, module, tmp_path):
        """保存**原样写回**（不经过 YAML 往返，注释与格式都保留）。"""
        target = tmp_path / "ip_spec.yaml"
        original = "# 我的注释\nversion: 1\nips:\n  - name: demo\n"   # 注释必须活下来
        target.write_text(original, encoding="utf-8")
        module.load(str(target))
        assert module.save_model() is True
        assert target.read_text(encoding="utf-8") == original
        assert module.editor.dirty is False

    def test_save_records_human_edit(self, module, tmp_path, monkeypatch):
        """保存要把这次编辑记进证据链 —— 漏了这一步，这次修改等于没发生过。

        `set_status` 走的是**平台状态栏**（`ctx.status`），不是本模块的脚注 label，
        所以要把消息截下来看，别去读 `module.status`。
        """
        target = tmp_path / "ip_spec.yaml"
        target.write_text("version: 1\nips:\n  - name: demo\n", encoding="utf-8")
        module.load(str(target))
        module.reason_edit.setText("补一个 IP")
        _type(module, "# 补一行\n")

        seen: list = []
        monkeypatch.setattr(module, "set_status", seen.append)

        assert module.save_model() is True
        assert target.read_text(encoding="utf-8").endswith("# 补一行\n")
        joined = " ".join(seen)
        assert "已保存" in joined
        assert "已记账" in joined, f"保存没进证据链：{seen}"

    def test_actions_bound_to_standard_keys(self, module):
        """Ctrl+S / Ctrl+O 要绑上 —— 编辑器没有保存快捷键是没法用的。"""
        shortcuts = [a.shortcut() for a in module.create_actions()]
        assert QKeySequence.StandardKey.Save in shortcuts
        assert QKeySequence.StandardKey.Open in shortcuts


def _example_path() -> Path:
    spec, _m, manifest_path = _shipped_spec()
    return Path(manifest_path).parent / spec.input


def _type(module, text: str) -> None:
    """**模拟用户输入** —— 走 Qt 的编辑 API，会真的把文档标脏。

    不要用 `editor.set_text(...)` 代替：那个方法的语义是「载入并标记为与磁盘
    一致」，拿它当输入用测试会永远看不到脏状态，从而漏掉「改动没被拦住」这类 bug。
    """
    module.editor.moveCursor(QTextCursor.MoveOperation.End)
    module.editor.insertPlainText(text)


class TestManifest:
    def test_placed_above_manual_nodes(self):
        """在「集成设计环境」里排在人工节点**上面** —— 先声明 IP 是什么，再声明流程在哪等人。"""
        from .conftest import shipped_manifest

        manifest, _ = shipped_manifest()
        ide = [s for s in manifest.modules if s.group == "ide"]
        ids = [s.id for s in ide]
        assert ids.index("ide.ip_spec") < ids.index("ide.manual_nodes")
        assert manifest.module(MODULE_ID).order < manifest.module("ide.manual_nodes").order

    def test_binding_is_pure(self):
        from ..bridge.catalog import by_name

        binding = by_name(TOOL_NAME)
        assert binding is not None and binding.kind == "json" and binding.pure is True
