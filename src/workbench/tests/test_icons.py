"""图标 —— 自绘 SVG 与 Qt 标准图标的取用。

这套图标存在的理由是**工具栏要有图标**（Verdi 是图标+小字）。所以最要紧的
两条是：名字都取得到、引用到的名字都存在。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ..ui import theme
from ..ui.theme import icons


def _app_source() -> str:
    """`app.py` 的源码 —— 它引用的图标名要与 `icons.names()` 对得上。

    路径从 `ui` 包往上数一层（`ui/` 的父是 `workbench/`）—— 别从 `icons.__file__`
    数：那个搬进 `ui/theme/` 之后，数出来的位置就不对了。
    """
    from .. import ui as ui_pkg
    app = Path(ui_pkg.__file__).resolve().parent.parent / "app.py"
    return app.read_text(encoding="utf-8")


class TestRender:
    def test_every_named_icon_renders(self, qt_app):
        for name in icons.names():
            pixmap = icons.icon(name).pixmap(16, 16)
            assert not pixmap.isNull(), f"{name} 渲染不出来"

    def test_unknown_name_is_an_empty_icon_not_none(self, qt_app):
        """返回空 QIcon 而不是 None —— None 会让 setIcon 之外的调用点炸掉。"""
        result = icons.icon("绝不存在的图标")
        assert result is not None
        assert result.isNull()

    def test_svg_icons_are_transparent_and_sized(self, qt_app):
        pixmap = icons.render_pixmap("wave", 16)
        assert pixmap.width() == 16 and pixmap.height() == 16
        # 图标是线描，四周不留底色 —— 否则贴在深色工具栏上是一块浅色方块
        assert pixmap.toImage().pixelColor(0, 0).alpha() == 0

    def test_standard_icons_come_from_qstyle(self, qt_app):
        assert not icons.icon("reload").pixmap(16, 16).isNull()
        assert not icons.icon("save").pixmap(16, 16).isNull()


class TestColoring:
    def test_icon_follows_the_current_theme_color(self, qt_app):
        """同一个名字、两套主题色，渲出来的位图必须不一样。"""
        light = icons.render_pixmap("wave", 16, "#000000")
        dark = icons.render_pixmap("wave", 16, "#d6dae0")
        assert light.toImage() != dark.toImage()

    def test_cache_is_keyed_by_color(self, qt_app):
        a = icons.icon("wave", 16, "#000000")
        b = icons.icon("wave", 16, "#ffffff")
        assert a is not b
        assert icons.icon("wave", 16, "#000000") is a        # 同键复用

    def test_switching_theme_changes_what_icon_returns(self, qt_app):
        """按 `dark` 标志挑两套调色板，而不是写死名字 —— 名字会改，这个属性不会。

        （写名字踩过坑：`theme.apply()` 遇到不认识的名字**静默保持原样**，
        于是两次渲染用的是同一套色，测试就变成了空转。）
        """
        dark_name = next(n for n, p in theme.PALETTES.items() if p.dark)
        light_name = next(n for n, p in theme.PALETTES.items() if not p.dark)
        original = theme.current().name

        try:
            theme.apply(qt_app, dark_name)
            icons.clear_cache()
            dark = icons.icon("tree").pixmap(16, 16).toImage()

            theme.apply(qt_app, light_name)
            icons.clear_cache()
            light = icons.icon("tree").pixmap(16, 16).toImage()

            assert dark != light, "换主题后图标没跟着换色"
        finally:
            theme.apply(qt_app, original)
            icons.clear_cache()


class TestReferences:
    """引用了不存在的图标名，界面上只是「这个按钮没图标」—— 不报错、很难发现。"""

    @staticmethod
    def _names_used(source: str):
        return set(re.findall(r'icons\.icon\(\s*"([^"]+)"', source))

    def test_app_icons_all_exist(self):
        used = self._names_used(_app_source())
        assert used, "app.py 里一个图标都没用上？"
        assert used <= set(icons.names()), f"app.py 引用了不存在的图标：{used - set(icons.names())}"

    def test_casemodel_action_icons_all_exist(self):
        from src.workbench.modules.verify.casemodel.module import CasemodelModule
        wanted = set(CasemodelModule.ACTION_ICONS.values())
        assert wanted <= set(icons.names()), \
            f"case 建模引用了不存在的图标：{wanted - set(icons.names())}"

    def test_every_hand_drawn_svg_has_a_color_placeholder(self):
        """SVG 忘了写 {color} 就会永远是一个颜色，主题换了它不换。"""
        for name, body in icons._SVG.items():
            assert "{color}" in body, f"{name} 的 SVG 里没有 {{color}} 占位"
