"""ISA 激励模块 —— 场景 DSL 在界面上编译成 IR。

界面只经 bridge 绑定访问工具，所以这份测试同时验了两件事：
模块把产物摆对了，以及**绑定表里的那条路真的通**。
"""
from __future__ import annotations

import pytest

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
        for name in ("isa_gen.validate", "isa_gen.compile", "isa_gen.explain",
                     "isa_gen.ops", "isa_gen.export"):
            assert registry.has(name), name

    def test_the_readers_are_pure_and_the_writer_is_not(self):
        """读的三条反复点也没代价；落盘那条**写盘**，必须显式触发。"""
        from ..bridge.catalog import default_registry
        registry = default_registry()
        for name in ("isa_gen.validate", "isa_gen.compile", "isa_gen.explain"):
            assert registry.get(name).pure, name
        assert registry.get("isa_gen.export").pure is False


class TestCompile:
    def test_the_manifest_input_is_loaded(self, module):
        """清单里配了 `input` —— 打开就该有东西可编译，不是空编辑框。"""
        assert "npu_gemm_smoke" in module.editor.toPlainText()

    def test_compiling_fills_all_six_tables(self, module):
        module.compile_dsl()
        assert module.instruction_model.rowCount() > 0     # IR
        assert module.encode_model.rowCount() > 0          # L3 编码后的字
        assert module.tensor_model.rowCount() > 0          # tensor_gen 的产物
        assert module.report_model.rowCount() > 0
        assert module.alloc_model.rowCount() > 0
        assert module.payload is not None

    def test_the_encode_tab_shows_words_isa_and_register_values(self, module):
        """编码清单要能回答"这个字是哪条指令、读的哪个寄存器、里面是什么值"。

        三样缺一都得回去翻别的文件：word 缺了没法对着 ISS 找、
        `isa` 缺了分不出 nice/vnice（opcode 不同）、寄存器值缺了还得开 reg-init。
        """
        module.compile_dsl()
        rows = module.encode_model.rows
        assert all(len(r["word"]) == 8 for r in rows), "word 应是 8 位 hex"
        assert {r["isa"] for r in rows} <= {"nice", "vnice"}
        # `rs1` 那一格带值（`x2 = 0x4000`），不是光一个号
        assert any("= 0x" in r["rs1"] for r in rows), [r["rs1"] for r in rows][:4]
        # 使能位没置位的槽显示 `—`，而不是骗人的 `x0`
        assert any(r["rs2"] == "—" for r in rows)

    def test_gaps_are_marked_on_the_row_not_only_in_a_footnote(self, module):
        """没填出来的操作数槽**当场标在那一行**。

        不标的话，它看起来就像"故意读 x0" —— 而 0 是合法操作数，
        仿真不会在那里报错。这正是这个工具最该防的那类静默。
        """
        module.compile_dsl()
        encode = module.payload["encode"]
        if not encode.get("gaps"):
            pytest.skip("这份示例没有空操作数槽")
        notes = "　".join(r["note"] for r in module.encode_model.rows)
        assert "未填" in notes, [r["note"] for r in module.encode_model.rows]

    def test_the_tensor_tab_shows_layout_and_content_hash(self, module):
        """张量那一页要能看出"这块数据是怎么摆的"，不只是"有多大"。"""
        module.compile_dsl()
        rows = module.tensor_model.rows
        assert all(r["name"] and r["dtype"] for r in rows)
        assert all(r["hash"] for r in rows), "content_hash 是 E7 缓存键，不能空"
        assert all("stride1=" in r["layout"] for r in rows)

    def test_the_summary_reports_the_shape(self, module):
        module.compile_dsl()
        text = module.summary.text()
        for field in ("事务", "指令", "epoch", "seed="):
            assert field in text, text

    def test_instructions_carry_tag_op_mask_and_data(self, module):
        module.compile_dsl()
        rows = module.instruction_model.rows
        assert all(r["op"] for r in rows)
        assert any(r["mask"] for r in rows)
        assert any(r["ref"] for r in rows)      # 有的指令带 binds/writes

    def test_the_report_records_the_derived_streams(self, module):
        """派生流是可复现链的一部分 —— 界面上要看得见。"""
        module.compile_dsl()
        keys = {r["key"] for r in module.report_model.rows}
        assert "派生流" in keys
        assert "seed" in keys

    def test_a_broken_dsl_shows_the_banner_not_a_traceback(self, module):
        module.editor.setPlainText("meta: {name: x}\nintend: {}")
        module.compile_dsl()
        assert module.payload is None
        assert module.btn_export.isEnabled() is False

    def test_validate_reports_issues_into_the_notes_tab(self, module):
        module.editor.setPlainText("meta: {name: x}\nintend: {}")
        module.check_dsl()
        assert module.notes_model.rowCount() == 1
        assert "unknown_property" in module.notes_model.rows[0]["kind"]

    def test_validate_on_a_good_dsl_says_so(self, module):
        module.check_dsl()
        assert module.notes_model.rowCount() == 0

    def test_export_is_disabled_before_compiling(self, module):
        assert module.btn_export.isEnabled() is False


class TestDeterminism:
    def test_the_same_seed_compiles_the_same_instructions(self, module):
        """可复现链在界面上也要成立 —— 同一个 seed 编两次，指令流一模一样。"""
        module.compile_dsl()
        first = [i["op"] for i in module.payload["ir"]["instructions"]]
        module.compile_dsl()
        second = [i["op"] for i in module.payload["ir"]["instructions"]]
        assert first == second
        assert first == second

    def test_the_seed_spinbox_overrides_the_dsl(self, module):
        module.seed_spin.setValue(777)
        module.compile_dsl()
        assert module.payload["seed"] == 777


class TestExport:
    def test_export_writes_the_documented_artifacts(self, module, tmp_path,
                                                    monkeypatch):
        """落盘走 `isa_gen.export` 那条绑定 —— 界面不自己写文件。"""
        module.compile_dsl()
        target = tmp_path / "out"

        # 跳过目录选择对话框，直接喂路径
        monkeypatch.setattr(module, "export_artifacts", module.export_artifacts)
        result = module.run_tool("isa_gen.export", force=True,
                                 out_dir=str(target), payload=module.payload)
        # §3.6 的六件套全在 —— 编码器（seq.hex / seq.lst / reg-init）
        # 与 tensor_gen（tensors/ · manifest/ · registry.json）都由这里落盘
        written = result["written"]
        assert {"case.json", "seq.ir.json", "preload.json", "expect.json",
                "seq.hex", "seq.lst", "reg-init.txt", "registry.json"} <= set(written)
        assert any(w.startswith("tensors/") for w in written)
        assert any(w.startswith("manifest/") for w in written)
        # 顶层文件与 `written` 对得上（子目录里的另算）
        top = {p.name for p in target.iterdir() if p.is_file()}
        assert top == {w for w in written if "/" not in w}

    def test_export_is_refused_without_force(self, module, tmp_path):
        """写盘的那条不许被顺手调用 —— 切个标签页就往磁盘写东西是不可逆的。"""
        from ..bridge.binding import ToolError
        module.compile_dsl()
        with pytest.raises(ToolError):
            module.ctx.tools.call("isa_gen.export", out_dir=str(tmp_path),
                                  payload=module.payload)
