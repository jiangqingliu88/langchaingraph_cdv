"""错误指纹页 —— 贴一段报错，取它可比较的指纹。

用**真清单**（`config/workbench.yaml` 的 `debug.fingerprint`）建模块，不打桩。
这条路径同时钉住四件事：

  1. 清单条目还在，且 factory 解析得到
  2. 绑定 `debug.fingerprint_error` 通 —— 指纹是工具算的，界面不自己实现
  3. **菜单里有它的入口**（`create_actions` 是一段时期内的空实现，
     于是这个模块只在「窗口」菜单里有个显隐开关，调试菜单里什么都没有）
  4. 取指纹真的把结果铺进表格

第 3 条是这次加的东西，也是这个文件存在的主要理由：模块**建得起来**
但它没进菜单，从测试上看不出来 —— 只有断言菜单动作才能发现。
"""
from __future__ import annotations

import json

import pytest

MODULE_ID = "debug.fingerprint"
TOOL_NAME = "debug.fingerprint_error"


def _shipped_spec():
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == MODULE_ID)
    return spec, manifest, manifest_path


@pytest.fixture
def module(qt_app, settings):
    from .conftest import make_ctx
    from ..modules.debug.fingerprint import FingerprintModule

    spec, manifest, manifest_path = _shipped_spec()
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = FingerprintModule(ctx, spec)
    widget = mod.create_widget()
    yield mod
    widget.deleteLater()


class TestDeclared:
    def test_the_manifest_entry_survives(self):
        """清单里的 id / 标题 / 工具绑定一个字都不能漂 ——
        改了 id 就是另一个模块，`create_actions` 也挂不到它头上。"""
        spec, _m, _p = _shipped_spec()
        assert spec.title == "错误指纹"
        assert spec.group == "debug"
        assert spec.factory.endswith(":FingerprintModule")
        assert spec.tool.name == TOOL_NAME

    def test_it_builds(self, module):
        assert module.editor is not None
        assert module.model is not None


class TestMenuEntry:
    def test_it_has_menu_actions(self, module):
        """**这条是本次改动的回归点。**

        `create_actions()` 空着时，`registry` 不会往业务线菜单里加任何东西
        —— 模块照样能建、能用，只是**从菜单里找不到入口**。那种缺失从
        "模块能不能构造"这类测试上完全看不出来。
        """
        actions = module.create_actions()
        assert actions, "错误指纹没有菜单动作 —— 调试菜单里会找不到它"

    def test_the_entry_is_named_after_the_module(self, module):
        """菜单里第一条是**这个模块的入口**，用模块名，不用动词。

        旁边还有别的模块的动作（它们也以动词命名），叫"取指纹"会分不清归属 ——
        `registry` 已经在动作前插了模块标题作分隔行。
        """
        action = module.create_actions()[0]
        assert action.text() == "错误指纹"
        assert action.statusTip(), "菜单项没有 statusTip，鼠标悬停时说不清它做什么"

    def test_the_entry_lands_in_the_debug_menu(self, qt_app, ctx, settings):
        """**端到端**：用真清单建真窗口，「调试」菜单里应当看得到这条。

        上面两条只证明"模块愿意给动作"；能不能真的挂到菜单上还取决于
        清单的 `group`（`action_menu_for` 按它分流：debug → 调试，
        其余 → 工具）。这一段把两者接起来验。
        """
        from .conftest import make_window, menu_by_title, shipped_manifest

        manifest, manifest_path = shipped_manifest()
        ctx.manifest = manifest
        ctx.manifest_path = manifest_path
        window = make_window(qt_app, ctx)
        try:
            debug_menu = [a.text() for a in menu_by_title(window, "调试").actions()]
            assert "错误指纹" in debug_menu, (
                f"调试菜单里没有「错误指纹」：{debug_menu}")
            # 而且不该跑到「工具」菜单里去
            tools_menu = [a.text() for a in menu_by_title(window, "工具").actions()]
            assert "错误指纹" not in tools_menu, (
                "debug 业务线的动作跑进工具菜单了 —— `action_menu_for` 的分流错了")
        finally:
            window.manager.mark_all_clean()
            window.close()


class TestPinnedToViewMenu:
    """清单里 `pin_to_view: true` → 显隐开关**也**挂到「视图」菜单。

    为什么两处都要：视图菜单列的是**窗格**（导航树 / 控制台 / 布局 / 主题），
    而错误指纹本质就是一个底部窗格 —— 用户想收起它时来视图里找。
    窗口菜单里那份照旧（那是"哪个模块开着"的完整清单）。
    """

    @pytest.fixture
    def real_window(self, qt_app, ctx):
        """用**真清单**建真窗口 —— 菜单接线是平台做的，打桩验不出来。"""
        from .conftest import make_window, shipped_manifest

        manifest, manifest_path = shipped_manifest()
        ctx.manifest = manifest
        ctx.manifest_path = manifest_path
        window = make_window(qt_app, ctx)
        yield window
        window.manager.mark_all_clean()
        window.close()

    def test_the_manifest_declares_it(self):
        spec, _m, _p = _shipped_spec()
        assert spec.pin_to_view is True, (
            "清单里的 debug.fingerprint 没有 pin_to_view —— 视图菜单里不会有它")

    def test_it_appears_in_the_view_menu(self, real_window):
        from .conftest import menu_by_title
        texts = [a.text() for a in menu_by_title(real_window, "视图").actions()]
        assert "错误指纹" in texts, f"视图菜单里没有它：{texts}"

    def test_it_sits_with_the_panes_not_after_the_themes(self, real_window):
        """插在「模块导航树 / 控制台」那一组后面，**不是**追加到末尾。

        视图菜单末尾是主题；追加到那儿，这条就分不清自己属于哪一类了。
        """
        from .conftest import menu_by_title
        texts = [a.text() for a in menu_by_title(real_window, "视图").actions()]
        i_fp = texts.index("错误指纹")
        assert texts.index("控制台") < i_fp, "跑到窗格那一组前面去了"
        assert i_fp < texts.index("重置布局"), "掉到布局/主题那一段去了"

    def test_it_is_the_same_action_as_the_window_menu_one(self, real_window):
        """两个菜单挂的是**同一个 QAction** —— 勾选状态因此天然同步。

        各建一份的话会出现"视图里开着、窗口里关着"，而且得再写一套同步代码。
        """
        from .conftest import menu_by_title
        v = [a for a in menu_by_title(real_window, "视图").actions()
             if a.text() == "错误指纹"]
        c = [a for a in menu_by_title(real_window, "窗口").actions()
             if "错误指纹" in a.text()]
        assert v and c, "两个菜单里至少有一个没挂上"
        assert v[0] is c[0], "是两份不同的 QAction —— 状态会打架"

    def test_toggling_from_the_view_menu_actually_hides_the_dock(self, real_window):
        """它是个**真开关**，不是个标签。"""
        from .conftest import menu_by_title
        entry = next(a for a in menu_by_title(real_window, "视图").actions()
                     if a.text() == "错误指纹")
        assert entry.isCheckable() and entry.isChecked()

        entry.setChecked(False)
        assert not real_window.workspace.contains(MODULE_ID)

        entry.setChecked(True)
        assert real_window.workspace.contains(MODULE_ID)


class TestTakingFingerprint:
    def test_the_sample_fills_the_editor(self, module):
        """示例要能被填进去 —— 空着的时候没有东西可试。"""
        module.editor.setPlainText("")
        sample_action = module.create_actions()[1]
        sample_action.trigger()
        assert module.editor.toPlainText().strip()

    def test_an_empty_editor_warns_instead_of_calling_the_tool(self, module):
        seen = []
        module.show_warning = lambda text: seen.append(text)     # type: ignore[method-assign]
        module.editor.setPlainText("   ")
        module.take_fingerprint()
        assert seen, "空输入应当提示，而不是拿空串去调工具"
        assert module.model.rowCount() == 0

    def test_a_real_error_yields_a_fingerprint(self, module):
        """指纹由工具算 —— 界面的职责只是把它铺出来。"""
        module.editor.setPlainText(
            "ERROR: tb_fifo.sv(128): Undefined variable 'rd_ptr'\n")
        module.take_fingerprint()
        rows = {r["键"]: r["值"] for r in module.model.rows}
        # 工具返回的键里有 fingerprint；没有的话说明绑定或返回形状变了
        assert "fingerprint" in rows, f"表格里没有 fingerprint：{sorted(rows)}"
        assert rows["fingerprint"], "指纹是空的"
        assert "指纹" in module.summary.text()

    def test_the_same_error_at_a_different_line_has_the_same_fingerprint(self, module):
        """指纹的意义就在这里：行号变了，"还是同一个 bug"要能判出来。"""
        def fp(text: str) -> str:
            module.editor.setPlainText(text)
            module.take_fingerprint()
            return {r["键"]: r["值"] for r in module.model.rows}.get("fingerprint", "")

        a = fp("ERROR: tb_fifo.sv(128): Undefined variable 'rd_ptr'\n")
        b = fp("ERROR: tb_fifo.sv(512): Undefined variable 'rd_ptr'\n")
        assert a and b, "两次都没取到指纹，先看上面那条"
        assert a == b, f"行号不同不该改变指纹：{a!r} vs {b!r}"

    def test_the_rows_are_json_safe(self, module):
        """表格里放的是字符串 —— 嵌套 dict 被展开一层，不是塞进去。"""
        module.take_fingerprint()
        for row in module.model.rows:
            assert isinstance(row["键"], str)
            assert isinstance(row["值"], str)
        # 展开后的东西仍然是可序列化的（回归时界面要能导出）
        json.dumps(module.model.rows, ensure_ascii=False)
