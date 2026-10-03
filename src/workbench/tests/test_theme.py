"""主题 —— 调色板的自洽、QSS 的覆盖面、横幅跟着主题走。

这一组是**结构性守卫**，不是像素比对：调色板是一大堆手写 hex，最典型的错法
是「漏填一个字段」（那个控件就变成透明或黑块）和「定义了一个没人用的字段」
（下一个人以为改它有用）。两条都能在测试里查出来。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QColor

from ..ui import theme
from ..ui.banner import Banner, _colors

#: 非颜色字段（没有 hex 值，不参与「值合法吗」的检查）
_NON_COLOR = {"name", "dark"}


def _package_root() -> Path:
    return Path(theme.__file__).resolve().parents[1]


def _all_sources() -> str:
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in _package_root().rglob("*.py"))


class TestPalette:
    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_every_color_field_is_a_valid_hex(self, name):
        palette = theme.PALETTES[name]
        bad = [field for field in palette.__dataclass_fields__
               if field not in _NON_COLOR
               and not QColor(getattr(palette, field)).isValid()]
        assert not bad, f"{name} 里有非法颜色：{bad}"

    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_selection_and_its_text_contrast(self, name):
        """选中行是深蓝底，字必须浅 —— 反过来就是「选中了但看不见字」。

        这类错不会报错，只会让人以为选中没生效，所以在这里钉住。
        """
        palette = theme.PALETTES[name]
        background = QColor(palette.selection).lightness()
        foreground = QColor(palette.selection_text).lightness()
        assert abs(background - foreground) > 90, \
            f"{name}：选中底与字的明度差只有 {abs(background - foreground)}"

    def test_default_is_the_classic_light_palette(self):
        """默认是经典 Verdi 浅灰 —— 深色只是备选。"""
        assert not theme.current().dark
        assert theme.DEFAULT_THEME in theme.PALETTES

    def test_initial_current_matches_default(self):
        """没调过 apply() 时 current() 也该给默认那套。"""
        assert theme.PALETTES[theme.DEFAULT_THEME] is theme.CLASSIC

    def test_both_palettes_have_a_dark_and_a_light(self):
        """一深一浅 —— 界面上要能真的切出两种观感。"""
        flags = {p.dark for p in theme.PALETTES.values()}
        assert flags == {True, False}


class TestStylesheet:
    def test_has_no_dock_rules(self):
        """工作台用三窗格分割条，一个 dock 都没有 —— 写了就是死代码，
        下一个人会以为还有 dock 需要照顾。"""
        assert "QDockWidget" not in theme._stylesheet(theme.CLASSIC)

    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_renders_without_leftover_braces(self, name):
        qss = theme._stylesheet(theme.PALETTES[name])
        # f-string 漏了转义会留下单个 { 或 }，Qt 会静默忽略整条规则
        assert qss.count("{") == qss.count("}"), "QSS 里的花括号不配对"
        assert "None" not in qss and "{" + "p." not in qss

    def test_covers_the_chrome_the_verdi_look_needs(self):
        qss = theme._stylesheet(theme.CLASSIC)
        for selector in ("QMenuBar::item", "QMenu::separator",
                         "QToolBar QToolButton", "QTabBar::tab:selected",
                         "QLabel#paneHeader", "QHeaderView::section",
                         "QTableCornerButton::section", "QSplitter::handle",
                         "QStatusBar QLabel", "QGroupBox",
                         "QComboBox::drop-down"):
            assert selector in qss, f"QSS 里缺 {selector}"


class TestNoDeadFields:
    """定义了却没人用的字段，下一个人改它以为有用 —— 这种字段排查起来很费劲。"""

    def test_every_palette_field_is_referenced_somewhere(self):
        source = _all_sources()
        fields = [f for f in theme.CLASSIC.__dataclass_fields__
                  if f not in _NON_COLOR and f != "toolbar_gradient"]
        unused = [f for f in fields if f".{f}" not in source]
        assert not unused, f"这些调色板字段没有任何地方引用：{unused}"


class TestThemePersistence:
    """在「视图」里切了主题，下次开要还是那套。

    `saved_theme()` 写进去却没人读的话，用户切到深色、重启又变回浅色 ——
    看着像「主题切换没生效」，其实是根本没存住。
    """

    @staticmethod
    def _store(tmp_path):
        from PySide6.QtCore import QSettings

        from ..settings_store import SettingsStore

        return SettingsStore(QSettings(str(tmp_path / "s.ini"),
                                       QSettings.Format.IniFormat))

    def test_saved_theme_is_used_when_the_manifest_says_nothing(
            self, qt_app, tmp_path, monkeypatch):
        import src.workbench.app as app_module

        store = self._store(tmp_path)
        store.set_value("window/theme", theme.DARK.name)
        monkeypatch.setattr(app_module, "SettingsStore", lambda: store)

        _app, window, _ctx = app_module.build_workbench([])
        try:
            assert theme.current().name == theme.DARK.name
        finally:
            window.manager.mark_all_clean()
            window.close()
            theme.apply(qt_app, theme.DEFAULT_THEME)

    def test_manifest_theme_beats_the_saved_one(self, qt_app, tmp_path, monkeypatch):
        """清单明确写了主题就听清单的 —— 那是作者意图，不是随手切的偏好。"""
        import src.workbench.app as app_module

        store = self._store(tmp_path)
        store.set_value("window/theme", theme.DARK.name)
        monkeypatch.setattr(app_module, "SettingsStore", lambda: store)

        manifest_path = tmp_path / "m.yaml"
        manifest_path.write_text(
            f'window: {{theme: "{theme.CLASSIC.name}"}}\n'
            "groups: []\nmodules: []\n", encoding="utf-8")

        _app, window, _ctx = app_module.build_workbench([str(manifest_path)])
        try:
            assert theme.current().name == theme.CLASSIC.name
        finally:
            window.manager.mark_all_clean()
            window.close()


class TestBannerFollowsTheme:
    """横幅的底色原先写死成浅色 —— 深色主题下是一块惨白的盒子，比它要提示的
    错误还扎眼。这条是那个 bug 的回归。"""

    def test_colors_differ_between_the_two_palettes(self, qt_app):
        original = theme.current().name
        try:
            theme.apply(qt_app, theme.CLASSIC.name)
            light = _colors("error")
            theme.apply(qt_app, theme.DARK.name)
            dark = _colors("error")
        finally:
            theme.apply(qt_app, original)
        assert light != dark, "换主题后横幅底色没跟着变"

    def test_banner_picks_up_the_current_palette(self, qt_app):
        original = theme.current().name
        try:
            theme.apply(qt_app, theme.CLASSIC.name)
            banner = Banner()
            banner.show_message("出问题了", "error")
            assert banner.colors == _colors("error")
            assert banner.kind == "error"
        finally:
            theme.apply(qt_app, original)

    def test_unknown_kind_falls_back_to_info(self, qt_app):
        banner = Banner()
        banner.show_message("x", "紫色")
        assert banner.kind == "info"
