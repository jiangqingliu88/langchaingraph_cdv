"""主题 —— 调色板的自洽、QSS 的覆盖面、横幅跟着主题走。

这一组是**结构性守卫**，不是像素比对：调色板是一大堆手写 hex，最典型的错法
是「漏填一个字段」（那个控件就变成透明或黑块）和「定义了一个没人用的字段」
（下一个人以为改它有用）。两条都能在测试里查出来。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage, QPalette

from ..ui import theme
from ..ui.widgets.banner import Banner, _colors

#: 非颜色字段（没有 hex 值，不参与「值合法吗」的检查）
_NON_COLOR = {"name", "dark"}


def _contrast(a: str, b: str) -> float:
    """两色的 WCAG 对比度（1~21）。配色改得读不读得出来，只有这个数是客观的。"""
    def luminance(hex_: str) -> float:
        channel = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                  for c in channel]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _package_root() -> Path:
    """**`workbench/` 包**的根 —— 扫源码查"这个调色板字段有没有人用"。

    **注意是 `ui/` 的上一层，不是 `ui/`**：调色板字段常被 `app.py` 与各业务模块
    用到，只扫 `ui/` 会把那些引用漏掉、把在用字段误报成"死字段"（真踩过）。
    从 `ui` 包往上数两层，比从某个子模块数稳 —— 子模块在 `ui/` 里的深度会变。
    """
    from .. import ui as ui_pkg
    return Path(ui_pkg.__file__).resolve().parent.parent


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
        """默认是浅色 —— 深色只是备选。"""
        assert not theme.current().dark
        assert theme.DEFAULT_THEME in theme.PALETTES

    def test_initial_current_matches_default(self):
        """没调过 apply() 时 current() 也该给默认那套。"""
        assert theme.PALETTES[theme.DEFAULT_THEME] is theme.CLASSIC

    def test_both_palettes_have_a_dark_and_a_light(self):
        """一深一浅 —— 界面上要能真的切出两种观感。"""
        flags = {p.dark for p in theme.PALETTES.values()}
        assert flags == {True, False}


class TestBrandAccent:
    """强调色是**新思紫**，不是库默认的那族蓝。

    品牌色在界面上有**三条独立的路**：自绘控件（矩阵 / 折线 / 行号槽）读的
    `Palette` 字段、库 QSS 里编译死的 hex、以及库那批"像素就是强调色"的图标。
    任何一条漏了，界面上都是"一半紫一半蓝"—— 而且不会报错，只是看着不对。
    所以三条各钉一条测试。
    """

    #: 紫的色相区间。取值都在 264° 附近（浅色 264、深色 261），这里留宽一些，
    #: 好让以后微调色相不至于动测试，但蓝色（~210）和品红（~300）进不来。
    PURPLE = range(240, 295)

    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_accent_selection_and_current_line_are_purple(self, name):
        palette = theme.PALETTES[name]
        for field in ("accent", "selection", "current_line"):
            hue = QColor(getattr(palette, field)).hue()
            assert hue in self.PURPLE, \
                f"{name}.{field} 的色相是 {hue}°，不是紫"

    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_accent_is_readable_on_its_own_panel(self, name):
        """强调色画在内容面上（链接、当前行号、折线），对比度得够 —— 换色最容易
        踩的就是"看着是紫的，但暗底上读不出来"（深色主题的颜色是为此专门上提
        一档明度的）。"""
        palette = theme.PALETTES[name]
        assert _contrast(palette.accent, palette.panel) >= 4.5, \
            f"{name}：强调色在内容面上的对比度只有 {_contrast(palette.accent, palette.panel):.1f}"

    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_stylesheet_keeps_no_library_blue(self, qt_app, name):
        """库那份 QSS 里编译进去的强调色 hex，一个都不该剩。

        **库这一版改不了色**：`load_stylesheet(palette=...)` 只拿它的 ID 选深浅，
        颜色是 SCSS 编译产物。所以换色靠替换 —— 这条查替换有没有漏档。
        """
        palette = theme.PALETTES[name]
        qss = theme._stylesheet(palette)
        leftover = [hex_ for level, hex_ in theme._BLUE.items()
                    if level in theme._ACCENT_SWAP[palette.dark] and hex_ in qss]
        assert not leftover, f"{name} 的样式表里还留着库的蓝：{leftover}"

    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_accent_icons_are_recolored(self, qt_app, name):
        """那批图标的**像素**就是强调色，QSS 换不掉，只能换图。

        树上那个焦点箭头、复选框的焦点框、停靠窗标题栏的按钮都在这一批里 ——
        漏了它们在日常使用中是看得见的（点到树上某个节点，展开箭头会闪一下蓝）。
        """
        import re

        palette = theme.PALETTES[name]
        qss = theme._stylesheet(palette)
        # 换 URL 时只换路径、别把 `url(...)` 再包一层 —— 包了 Qt 会静默不加载，
        # 图标变成空白，而"样式表里有这个路径"的其他检查全都发现不了
        assert 'url("url(' not in qss, "图标 URL 被套了两层 url(...)"
        swapped = [url for url in re.findall(r'url\("([^"]+)"\)', qss)
                   if "signoffai-theme-icons" in url]
        assert swapped, f"{name}：没有任何图标被换成品牌色"
        branch = [url for url in swapped if "branch_open_focus" in url]
        assert branch, f"{name}：树的展开箭头（branch_open_focus）没被换"
        assert Path(branch[0]).exists(), f"样式表指向的图标不存在：{branch[0]}"

        image = QImage(branch[0])
        assert not image.isNull(), f"换出来的图标读不了：{branch[0]}"
        colored = [image.pixelColor(x, y)
                   for y in range(image.height()) for x in range(image.width())
                   if image.pixelColor(x, y).alpha() > 40
                   and image.pixelColor(x, y).saturation() > 60]
        assert colored, "这张图里一个带色的不透明像素都没有 —— 测试就没意义了"
        wrong = sorted({c.name() for c in colored if c.hue() not in self.PURPLE})
        assert not wrong, f"{name}：换过的图标里还有非紫的像素 {wrong}"

    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_inactive_selection_keeps_the_brand_hue(self, qt_app, name):
        """库把"选中了但焦点不在这个窗格"画成中性灰。

        在通用主题里这条规矩成立，在这个工作台里不成立：点一下导航树，焦点立刻
        被中央标签页拿走 —— 于是"我在哪个模块"这唯一的提示常年停在灰档上，
        品牌色只在按下的那一瞬看得见。所以那一档要留在品牌色里。

        但**只准改这一条选择器**：那个灰同时用在交替行、表头、悬停上，全局
        替换会把它们一起染紫 —— 顺带把"灰还在别处"钉住。
        """
        import re

        from qdarkstyle.colorsystem import Gray

        palette = theme.PALETTES[name]
        qss = theme._stylesheet(palette)
        color = theme._INACTIVE_SELECTION[palette.dark]
        rules = [body for sel, body in re.findall(r"([^{}]*)\{([^}]*)\}", qss)
                 if "::item:selected:!active" in sel]
        assert rules, "样式表里找不到「非活动选中」那条规则"
        assert all(color.upper() in body for body in rules), \
            f"{name}：非活动选中没换成品牌色"
        # 两档合一：选中了就该是紫的，跟焦点在不在无关（理由见 palette.py）
        assert color == palette.selection
        assert QColor(color).hue() in self.PURPLE
        # 同一个灰在别处（交替行 / 表头 / 悬停）走的是**品牌底色**，不是选中色 ——
        # 两处要是同一个颜色，要么选中看不出来，要么那块底色压根没上品牌
        surface = theme._SURFACE_SWAP[palette.dark]["B120" if not palette.dark else "B30"]
        assert surface.upper() in qss, "交替行/表头那块底色没跟着品牌走"
        assert all(surface.upper() not in body for body in rules)

    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_surface_is_brand_tinted(self, qt_app, name):
        """窗框、边框、交替行这些"底"也要走品牌紫。

        只换强调色的话，界面看上去还是一套灰色工具（紫色只在选中/悬停的那一瞬
        闪一下，而那恰恰是最不容易看见的）。这里查**紫的方向** —— 不用色相：
        这几档饱和度低，色相不可靠；但"紫"在 RGB 上稳定地是 B ≥ R ≥ G。
        """
        palette = theme.PALETTES[name]
        for field in ("panel", "panel_alt", "border", "text", "muted", "gutter_bg"):
            c = QColor(getattr(palette, field))
            assert c.blue() >= c.red() >= c.green(), \
                f"{name}.{field} = {c.name()} 不是紫调"

    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_stylesheet_keeps_no_library_gray(self, qt_app, name):
        """库那份 QSS 里的灰阶，一个都不该剩 —— 剩一个就是一块没上品牌色的窗框。"""
        palette = theme.PALETTES[name]
        qss = theme._stylesheet(palette)
        leftover = [level for level, hex_ in theme._GRAY.items()
                    if level in theme._SURFACE_SWAP[palette.dark] and hex_.upper() in qss]
        assert not leftover, f"{name} 的样式表里还留着库的灰：{leftover}"

    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_app_palette_has_no_foreign_colors(self, qt_app, name):
        """调色板是**第二份真相**：样式表管不到的缝（富文本链接、个别原生控件）
        从这里取色。库只刷了 `Link`，选中的 `Highlight` 一直是 Qt 默认的蓝、
        `LinkVisited` 是品红 —— 留着它们，界面里就藏着一处非品牌色。
        """
        palette = theme.PALETTES[name]
        original = theme.current().name
        try:
            theme.apply(qt_app, name)
            app_palette = qt_app.palette()
            for role in (QPalette.ColorRole.Highlight, QPalette.ColorRole.Link,
                         QPalette.ColorRole.LinkVisited):
                hue = app_palette.color(role).hue()
                assert hue in self.PURPLE, \
                    f"{name}：{role.name} 是 {app_palette.color(role).name()}"
            assert app_palette.color(QPalette.ColorRole.Highlight).name() \
                == palette.selection
        finally:
            theme.apply(qt_app, original)

    def test_colorless_icons_are_left_alone(self, qt_app):
        """不带强调色的图标（灰的那批）不该被复制一份 —— 复制了也还是灰的，
        只是多一个"这文件为什么在这儿"的疑问。"""
        qss = theme._stylesheet(theme.CLASSIC)
        assert ':/qss_icons/light/rc/checkbox_checked_disabled.png' in qss

    def test_app_link_color_follows_the_brand(self, qt_app):
        """富文本里的链接取的是调色板的 Link，**不吃样式表** —— 库会把它刷成
        它那族蓝，得按回来。"""
        original = theme.current().name
        try:
            theme.apply(qt_app, theme.DARK.name)
            link = qt_app.palette().color(QPalette.ColorRole.Link)
            assert link.hue() in self.PURPLE, f"Link 还是 {link.name()}"
        finally:
            theme.apply(qt_app, original)


class TestStylesheet:
    """样式表的**归属**：标准控件归 QDarkStyle，我们只补自己那几个 objectName。

    早先这里断言的是"我们手写的 QSS 覆盖了哪些选择器"。那套已经不成立了 ——
    手臂写的 1 万多字符 QSS 换成了库，该守的不变式也随之换了：

      · 我们补的那几条**只能碰自己的 objectName**（不能又开始跟库抢按钮）；
      · 库那部分**必须真的接在当前配色对应的色板上**（否则深浅切换是假的）。
    """

    def test_is_the_library_stylesheet_plus_our_overlay(self, qt_app):
        import qdarkstyle

        light = qdarkstyle.load_stylesheet(qt_api="pyside6",
                                           palette=qdarkstyle.LightPalette)
        assert theme._stylesheet(theme.CLASSIC).startswith(light[:400])

    def test_dark_theme_actually_loads_the_dark_palette(self, qt_app):
        import qdarkstyle

        dark = qdarkstyle.load_stylesheet(qt_api="pyside6",
                                          palette=qdarkstyle.DarkPalette)
        assert theme._stylesheet(theme.DARK).startswith(dark[:400])
        assert theme._stylesheet(theme.DARK) != theme._stylesheet(theme.CLASSIC)

    @pytest.mark.parametrize("name", list(theme.PALETTES))
    def test_renders_without_leftover_braces(self, qt_app, name):
        qss = theme._stylesheet(theme.PALETTES[name])
        # f-string 漏了转义会留下单个 { 或 }，Qt 会静默忽略整条规则
        assert qss.count("{") == qss.count("}"), "QSS 里的花括号不配对"
        assert "None" not in qss and "{" + "p." not in qss

    def test_overlay_only_touches_our_own_object_names(self):
        """补充的那几条**每个选择器都得带 `#objectName`**。

        守的是这条边界：一旦在补充里写 `QPushButton { ... }`，就又是"两处各
        描述一遍按钮"，跟库打架 —— 谁后加载谁赢，升级库的时候表现会莫名其妙
        地变。`#paneHeader` 这种名字我们独有，库里不可能有，写在这儿不冲突。
        """
        # **先剥掉注释**：注释里常引用被 override 的那条库规则
        # （`QAbstractScrollArea { border: 1px }`），不剥的话它的花括号
        # 会把选择器切歪，测试报一个根本不存在的问题（真踩过）
        import re

        overlay = re.sub(r"/\*.*?\*/", "", theme._app_overlay(theme.CLASSIC),
                         flags=re.S)
        selectors = []
        for chunk in overlay.split("{")[:-1]:
            lines = [line.strip() for line in chunk.splitlines() if line.strip()]
            if lines:
                selectors.append(lines[-1])
        assert selectors, "补充里一条规则都没有 —— 这条测试就没意义了"
        bad = [s for s in selectors if "#" not in s]
        assert not bad, f"补充里出现了不带 objectName 的选择器：{bad}"

    def test_overlay_covers_the_apps_own_widgets(self):
        """本工作台自己的两个 objectName 要有规则，否则窗格标题条就是一条
        裸的灰字，跟内容糊在一起。"""
        overlay = theme._app_overlay(theme.CLASSIC)
        assert "QLabel#paneHeader" in overlay
        assert "QWidget#paneHost" in overlay


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
