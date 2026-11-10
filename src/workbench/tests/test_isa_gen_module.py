"""ISA 激励模块 —— .ir.txt 在界面上编译成命令流。

界面只经 bridge 绑定访问工具，所以这份测试同时验了两件事：
模块把产物摆对了，以及**绑定表里的那条路真的通**。
"""
from __future__ import annotations

import hashlib

import pytest

from ..modules.verify.isa_gen.module import SAMPLE

MODULE_ID = "verify.isa_gen"


@pytest.fixture
def module(qt_app, settings, tmp_path):
    """装着真清单的真窗口，并打开 ISA 模块（center 是懒加载的）。"""
    from .conftest import make_ctx, make_window, shipped_manifest

    manifest, manifest_path = shipped_manifest()
    win = make_window(qt_app, make_ctx(manifest, manifest_path, settings))
    win.manager.open(MODULE_ID)
    found = win.manager.module(MODULE_ID)
    assert found is not None, f"模块没建出来：{win.manager.failures()}"
    yield found
    win.manager.mark_all_clean()
    win.close()
    win.deleteLater()
    qt_app.processEvents()


class TestWiring:
    def test_the_module_is_declared_and_builds(self, qt_app, settings):
        from .conftest import make_ctx, make_window, shipped_manifest
        manifest, manifest_path = shipped_manifest()
        win = make_window(qt_app, make_ctx(manifest, manifest_path, settings))
        try:
            assert win.manager.failures() == {}
            win.manager.open(MODULE_ID)
            assert win.manager.module(MODULE_ID) is not None
            assert win.manager.pane_of(MODULE_ID) == "center"
        finally:
            win.manager.mark_all_clean()
            win.close()

    def test_every_tool_it_needs_is_bound(self):
        """界面**只能**经这张白名单到工具 —— 少一条就点不动。"""
        from ..bridge.catalog import default_registry
        registry = default_registry()
        for name in ("isa_ir.validate", "isa_ir.build"):
            assert registry.has(name), name

    def test_the_reader_is_pure_and_the_builder_is_not(self):
        """校验反复点也没代价；编译落盘要起子进程并写盘，必须显式触发。"""
        from ..bridge.catalog import default_registry
        registry = default_registry()
        assert registry.get("isa_ir.validate").pure is True
        assert registry.get("isa_ir.build").pure is False


class TestValidate:
    def test_the_shipped_case_is_parsed_into_actions(self, module):
        module.check_ir()
        assert module.validation is not None
        rows = module.action_model.rows
        assert len(rows) == 15
        ops = {row["op"] for row in rows}
        assert {"group_mask_drv_xn", "tld_drv_xn", "tst_drv_xn",
                "mem_init", "mem_scrub", "wait_done"} <= ops
        assert {"指令", "控制"} <= {row["kind"] for row in rows}

    def test_the_summary_reports_counts_and_revision(self, module):
        module.check_ir()
        text = module.summary.text()
        assert "动作 15" in text
        assert "ISA_VERSION_V1.4" in text

    def test_a_broken_ir_shows_an_error_not_a_traceback(self, module):
        module.editor.setPlainText("this is not an instruction(")
        module.check_ir()
        assert module.validation is None
        assert module.action_model.rowCount() == 0
        assert "校验失败" in module.summary.text()

    def test_the_sample_compiles_as_a_control_program(self, module):
        module.editor.setPlainText(SAMPLE)
        module.check_ir()
        assert module.validation is not None
        assert module.validation["counts"]["actions"] == 1
        assert module.validation["counts"]["tensors"] == 1


class TestBuild:
    def _build(self, module, tmp_path, monkeypatch):
        from ..modules.verify.isa_gen import module as isa_module
        monkeypatch.setattr(isa_module.QFileDialog, "getExistingDirectory",
                            lambda *args, **kwargs: str(tmp_path))
        module.check_ir()
        module.build_ir()
        return tmp_path / "sanity_glsu_local_dram_smoke"

    def test_build_writes_the_three_stage_bundle(self, module, tmp_path,
                                                 monkeypatch):
        bundle = self._build(module, tmp_path, monkeypatch)
        assert (bundle / "02_ir" / "seq.ir").is_file()
        assert (bundle / "03_commands" / "commands.tsv").is_file()
        assert (bundle / "03_commands" / "cmddata.memh").is_file()
        assert module.command_model.rowCount() == 15
        assert module.seq_text.toPlainText().startswith("// Operand-resolved IR")
        assert "已编译 15 条记录" in module.summary.text()

    def test_the_same_source_builds_byte_identical_commands(self, module,
                                                           tmp_path,
                                                           monkeypatch):
        first = self._build(module, tmp_path, monkeypatch)
        digest = hashlib.sha256((first / "03_commands" / "cmddata.memh").read_bytes())
        second = self._build(module, tmp_path, monkeypatch)
        assert (second / "03_commands" / "cmddata.memh").read_bytes() == \
            (first / "03_commands" / "cmddata.memh").read_bytes()
        assert digest.hexdigest()

    def test_build_is_refused_without_force(self, module, tmp_path):
        """写盘那条不许被顺手调用 —— 切个标签页就往磁盘写是不可逆的。"""
        from ..bridge.binding import ToolError
        module.check_ir()
        with pytest.raises(ToolError):
            module.ctx.tools.call("isa_ir.build",
                                  source_text=module.editor.toPlainText(),
                                  out_dir=str(tmp_path))
