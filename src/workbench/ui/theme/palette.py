"""主题系统 —— **底座是 QDarkStyle，我们只补它管不到的那部分**。

放在 `ui/` 顶层而不是 `ui/widgets/` 下：**models 也要用**（诊断按严重度
着色、组织树按覆盖状况着色都在模型的 `data()` 里）。models 与 widgets 是
兄弟目录，把主题埋进 widgets 会逼着 models 反向依赖 widgets。

设计要点：模块级名字（`theme.TEXT` / `theme.SEVERITY` / `theme.mono_font()`）
**始终解析到当前激活的那套配色**，所以切换主题不用改任何调用点 ——
所有控件与模型下次重绘时自然跟上。

    from src.workbench.ui import theme
    painter.setPen(theme.TEXT)
    theme.apply(app, "浅色")

两套预设：
  · **浅色**（默认）—— 紫灰窗框 + 近白（带紫）内容面 + 新思紫强调色。
  · **深色**        —— 同一套层次关系反过来，长时间盯日志舒服。

> 配色换过四代。第一代是照着一张 Verdi 截图像素采样搬的（灰底、深蓝高亮、
> 2px 立体边框）；第二代只把灰阶拉开一档 —— 结果只有 10 来个 RGB 单位的差，
> 屏幕上根本看不出来，还是"一整块灰"；第三代把控件外观整套交给 QDarkStyle，
> 立体边框去掉，**层次靠明度差**（窗框 vs 内容面差 20 多单位）。但那一代
> 只有强调色是紫的，窗框仍是库的中性灰 —— 紫色只存在于"选中 / 悬停 / 按下"
> 那几个瞬态里，而那几个瞬态恰恰最不容易被看见（点一下导航树，焦点立刻被
> 中央标签页拿走）。所以这一代把**灰阶也整体挪到品牌色那一侧**。
>
> Verdi 那套窗格布局与七项菜单栏还留着（见 `readme.md`），只是不再连
> "长什么样"都照抄。
>
> 本文件原在 `src/layers/l3_decision/casemodel/view/gui/theme.py`，工作台第一轮
> 上提为平台通用件。
>
> **整套界面是新思紫**（品牌紫 `#573885` 那一族），不是库默认的灰 + 蓝。
> 颜色分两张表：`_SURFACE_SWAP` 管"底"（窗框 / 边框 / 表头 / 交替行 / 文字），
> `_ACCENT_SWAP` 管"强调"（选中 / 悬停 / 焦点框 / 链接）。两张表都只换颜色、
> **不换档位**，所以"哪块比哪块深"这层关系还是库定的。
>
> 而颜色在界面上有**四条独立的路**要走到，只改一条就是"一半紫一半灰"：
>
>   1. 我们自绘的控件（矩阵 / 折线 / 覆盖条 / 行号槽）读的 `Palette` 字段；
>   2. 库那份 QSS —— 颜色是 SCSS 编译时写死的**字面量 hex**；
>   3. 库那批**像素就是强调色**的图标（`*_focus.png` / `*_pressed.png`）；
>   4. `QPalette` —— 样式表管不到的缝（富文本链接、少数按调色板取色的控件）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import qdarkstyle
from qdarkstyle.colorsystem import Blue as _Blue
from qdarkstyle.colorsystem import Gray as _Gray
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

# ════════════════════════════════════════════════════════════
# 一套配色
# ════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Palette:
    """**只剩"库管不到"的那些颜色** —— 自绘控件与领域语义用。

    标准控件（按钮 / 表格 / 页签 / 滚动条 / 菜单 / 工具栏…）长什么样归
    **QDarkStyle**，这里**不再重复描述一遍** —— 早先这个类有 60 多个字段，
    一半是在手写那套 QSS，两处各记一份必然漂移。现在砍到只留两类：

      · **自绘控件要的**：交叉矩阵、覆盖条、折线、源码高亮、导航树着色
        都是自己 `QPainter` 画的，QSS 管不到 —— 它们的底与线只能从这儿拿。
      · **领域语义**：error/warning/ok、语法高亮九档、交叉矩阵三档底色…
        这些是"验证领域"的词，任何通用主题库都不可能提供。

    骨架那几档（panel/text/border/accent/selection…）**从 QDarkStyle 的
    色阶里读出来**，不另写一份 hex —— 见 `_from_qdarkstyle`。这样库升级换色，
    自绘控件跟着走。领域那几档没法derive，仍然手工给，**明暗各一套**：
    同一个深绿放在 `#fafafa` 上看得清，放在 `#19232d` 上就糊了。
    """
    name: str
    dark: bool

    # ── 骨架（自绘控件用的底与线，来自 QDarkStyle 色阶）──
    panel: str           # 表格/画布背景
    panel_alt: str       # 交替行 / 表头行 / 窗格标题条
    text: str            # 正文
    muted: str           # 次要文字（提示、行号、单位）
    grid: str            # 表格网格线
    border: str          # 分隔线、边框
    accent: str          # 强调（选中、链接、当前行号、折线）
    selection: str       # 选中行背景
    selection_text: str  # 选中行前景

    # ── 语义 ──
    error: str
    warning: str
    info: str
    ok: str

    # ── 代码区 ──
    # （没有 `editor_bg`：代码区的底色现在由库的 QSS 给。我们只管**行号槽**
    #   与**当前行**这两处自绘的地方，它们库画不到。）
    gutter_bg: str
    current_line: str    # 当前行高亮

    # ── YAML 语法高亮 ──
    syn_key: str         # 键名
    syn_string: str      # 字符串
    syn_number: str      # 数字
    syn_bool: str        # true/false/null
    syn_comment: str     # 注释（斜体）
    syn_marker: str      # 列表项 "-"、文档分隔符
    syn_anchor: str      # &锚点 *引用
    syn_enum: str        # 工具认得的枚举值（D/RND/G、CHECK-XXX、P0…）
    syn_meta: str        # 顶层保留键（object/dimensions/themes…）

    # ── 交叉矩阵：格子底色 ──
    cross_required: str
    cross_optional: str
    cross_forbidden: str

    # ── 交叉矩阵：标记前景色（必须与上面的底色对比，否则标记看不见）──
    mark_required: str
    mark_optional: str
    mark_forbidden: str
    mark_none: str

    # ── 评分（概览页那个大分数）──
    score_good: str
    score_warn: str
    score_bad: str

    # ── 顶部横幅三对（原来写死在 banner.py 里，深色主题下是一块惨白的盒子）──
    banner_error_bg: str
    banner_error_fg: str
    banner_warning_bg: str
    banner_warning_fg: str
    banner_info_bg: str
    banner_info_fg: str

    def q(self, name: str) -> QColor:
        """按字段名取 QColor —— 供调用方按需构造。"""
        return QColor(getattr(self, name))

    def banner_colors(self, kind: str) -> tuple:
        """横幅的 (底, 字)。

        写成显式的分支而不是 `getattr(self, f"banner_{kind}_bg")` —— 动态取名字
        会让那六个字段在源码里**一个引用都没有**，于是「定义了却没人用」的检查
        看不见它们，改造时容易漏。
        """
        if kind == "error":
            return self.banner_error_bg, self.banner_error_fg
        if kind == "warning":
            return self.banner_warning_bg, self.banner_warning_fg
        return self.banner_info_bg, self.banner_info_fg


#: **领域配色** —— 这两组**没法从库里 derive**，只能手工给，明暗各一套。
#:
#: 判断标准只有一条：**放到该主题的内容面上读不读得出来**。同一个深绿
#: `#2e7d32` 放在 `#fafafa` 上很清楚，放在 `#19232d` 上就糊成一片 ——
#: 所以下面每档都得给两遍。
_LIGHT_DOMAIN = dict(
    error="#c62828", warning="#a15c00", info="#1565c0", ok="#2e7d32",
    syn_key="#1565c0", syn_string="#2e7d32", syn_number="#a15c00",
    syn_bool="#7b1fa2", syn_comment="#7a8794", syn_marker="#7a8794",
    syn_anchor="#a15c00", syn_enum="#5e35b1", syn_meta="#00695c",
    cross_required="#f8d7da", cross_optional="#fff3cd",
    cross_forbidden="#e9ecef",
    mark_required="#9c1a22", mark_optional="#8a5f10",
    mark_forbidden="#5f6b7a", mark_none="#adb5bd",
    score_good="#2e7d32", score_warn="#a15c00", score_bad="#c62828",
    banner_error_bg="#fdecea", banner_error_fg="#a01a14",
    banner_warning_bg="#fef6e0", banner_warning_fg="#7a4a00",
    banner_info_bg="#e8f1fb", banner_info_fg="#0d4478",
)

_DARK_DOMAIN = dict(
    error="#ff6b6b", warning="#f2b352", info="#5aa9e6", ok="#6cc070",
    syn_key="#79b8ff", syn_string="#8ed88a", syn_number="#f0a45d",
    syn_bool="#d183e0", syn_comment="#7a8794", syn_marker="#9da9b5",
    syn_anchor="#f0a45d", syn_enum="#d9d98a", syn_meta="#5cbecf",
    cross_required="#5a2b30", cross_optional="#4a4220",
    cross_forbidden="#37414f",
    mark_required="#ff9d9d", mark_optional="#ffd479",
    mark_forbidden="#9aa4ae", mark_none="#5a646e",
    score_good="#6cc070", score_warn="#f2b352", score_bad="#ff6b6b",
    banner_error_bg="#3a2224", banner_error_fg="#ff9d9d",
    banner_warning_bg="#382f1e", banner_warning_fg="#ffd479",
    banner_info_bg="#1b2b3a", banner_info_fg="#9ac4e8",
)


# ════════════════════════════════════════════════════════════
# 品牌强调色 —— 新思紫
# ════════════════════════════════════════════════════════════
#
# QDarkStyle 的色阶里只有灰、蓝两族，没有紫。这里自己补一族，**并且只有一张表**
# 描述它 —— `_ACCENT_SWAP`。强调色在界面上有**三条独立的路**要走到：
#
#   1. `_from_qdarkstyle`：自绘控件（交叉矩阵 / 折线 / 覆盖条 / 行号槽）读的骨架；
#   2. 库的 QSS：选中行、页签下划线、悬停、焦点框 —— 颜色是 SCSS 编译时
#      **写死进 qss 资源**的，`load_stylesheet(palette=...)` 那个参数只拿
#      `palette.ID` 选深浅，改不了色（见 `_qdarkstyle_palette` 的注释）；
#   3. 库的强调色图标：`*_focus.png` / `*_pressed.png` 这一批 PNG 的像素
#      就是强调色（树的展开箭头、缩进引导线、复选框、停靠窗标题栏按钮）。
#
# 三条路各写一份颜色，必然出现"矩阵紫了、树上那个焦点箭头还是蓝的"。所以
# 三条都从这一张表换算。
#
# **只拧色相、不动明暗关系**：下面这些值是把库那族蓝逐个转到 264° 紫算出来的，
# 明度一对一照搬，饱和度压到 ~80%（同一个 HSL 饱和度，紫看着比蓝重）。
# 明度关系没变，所以"选中看不清字""焦点框糊住"这类问题不会因为换色冒出来。
# 锚点是新思的品牌紫 `#573885`：深色板的选中底 `#64459c` 就落在它旁边。
#
# 两张色板各一张表，不是一张共用：**紫在同一明度上的实际亮度比蓝低一截**，
# 暗色主题若照抄浅色的取值，链接和当前行号会暗到读不出来（实测对比度 2.5，
# 库原本那族蓝在 5 上下）。所以暗色那张整体上提一档明度。
#
# 键是库色阶的档位名（`qdarkstyle.colorsystem.Blue` 里的 `B20`…`B130`），
# 不是 hex —— 库升级换色时键不用改，只要它还是同一档。

#: 浅色主题用到的五档（在 `#fafafa` 上）。库的浅色 QSS 用前四档，
#: 强调色图标用第五档（`B70`），所以五档都得给。
_ACCENT_SWAP = {
    False: {
        "B130": "#e6d7fb",   # 悬停底 / 当前行 / 页签下划线
        "B100": "#c9aaf6",   # 选中底（配深字，对比度 8.0）
        "B90":  "#ae81f1",
        "B80":  "#8b4bea",   # 焦点框
        "B70":  "#7838d5",   # 强调：链接、当前行号、折线、焦点态图标（白底 6.0）
    },
    True: {
        "B20":  "#4a3373",
        "B40":  "#64459c",   # 选中底（配浅字，对比度 5.6）
        "B50":  "#7b57bd",
        "B70":  "#a884ea",   # 强调
        "B80":  "#c6a8f7",   # 焦点态图标（深色板的图标用这一档）
    },
}

#: 每张色板从哪一档取"选中底 / 当前行 / 强调" —— **库自己的取法，照搬**。
#: 浅色板是 `ACCENT_5 / 2 / 1`，深色板是 `ACCENT_4 / 2 / 1`，落到档位上
#: 正好都是 `B70 / B100|B40 / B130|B20`。
_ACCENT_ROLES = {
    False: {"accent": "B70", "selection": "B100", "current_line": "B130"},
    True: {"accent": "B70", "selection": "B40", "current_line": "B20"},
}

#: 已访问的链接取哪一档 —— 得和未访问的强调色（`B70`）区分开，取中间那档。
#: 只在富文本里见得到（关于框），但留着品红就是留着一处非品牌色。
_ACCENT_VISITED = {False: "B90", True: "B50"}

#: 库色阶里那几档蓝的实际 hex —— 替换用的键从这里现取，不手抄。
_BLUE = {k: str(getattr(_Blue, k)) for k in
         ("B20", "B40", "B50", "B70", "B80", "B90", "B100", "B130")}


# ════════════════════════════════════════════════════════════
# 品牌底色 —— 那套灰也上品牌倾向
# ════════════════════════════════════════════════════════════
#
# 强调色换成紫只是第一步：整个窗框（菜单栏 / 工具栏 / 状态栏 / 停靠窗标题条 /
# 窗格标题）在库里是**中性灰**叠出来的，只换强调色的话，界面看上去还是一套
# 灰色工具，紫色只存在于"选中/悬停/按下"的那一瞬 —— 而那几个瞬态恰恰是用户
# 最不容易看见的（点一下导航树，焦点立刻被中央标签页拿走）。
#
# 所以这一张表把库的灰阶整体挪到品牌色那一侧：**档位不变、明暗关系照搬**，
# 只把色相往紫偏、饱和度给一点点。这样"哪块是内容、哪块是窗框、哪块是边框"
# 的层次完全没动，读起来还是同一套界面。
#
# 键同样是档位名（`Gray.B10`…`B140`）。两张色板各一张 —— 浅色把灰往紫白偏，
# 深色往紫黑偏，不是同一组值换明度。

#: 浅色：内容面近白（带一点紫）、窗框是紫灰。正文与弱化字的对比度都核过
#: （16.5 / 4.8，库原来那套是 15.3 / 3.3）。
_SURFACE_SWAP = {
    False: {
        "B140": "#f9f5fe",   # 内容面 / 表格底
        "B130": "#ece3fa",   # 交替行 / 窗格标题条 / 行号槽
        "B120": "#e0d6f2",   # 表头行 / 悬停
        "B110": "#cfc2e6",   # 菜单栏 / 工具栏 / 状态栏 / 停靠窗标题 + 边框
        "B100": "#c5b9dd",
        "B90":  "#bdb0d4",
        "B80":  "#a99cc2",   # 禁用文字
        "B70":  "#75678d",   # 弱化文字（提示、行号、单位）
        "B10":  "#1c1526",   # 正文（近黑的紫，不纯黑 —— 纯黑在紫底上发脏）
    },
    True: {
        "B10":  "#171122",   # 内容面
        "B20":  "#221a33",   # 交替行 / 窗格标题条 / 行号槽
        "B30":  "#2d2440",   # 表头行 / 悬停
        "B40":  "#3a2f52",   # 菜单栏 / 工具栏 / 状态栏 / 停靠窗标题 + 边框
        "B50":  "#453a5f",
        "B60":  "#4f4369",
        "B70":  "#8d7cab",   # 弱化文字
        "B80":  "#a99cc4",   # 禁用文字
        "B130": "#eae1f8",   # 正文
    },
}

#: 灰阶的档位名 → 实际 hex，与上面两张表配合做替换（认不出档位就原样留着）。
_GRAY = {k: str(getattr(_Gray, k)) for k in
         ("B10", "B20", "B30", "B40", "B50", "B60", "B70", "B80", "B90",
          "B100", "B110", "B120", "B130", "B140")}

#: 库的灰 hex → 品牌化后的 hex（大写键，与 QSS 里的字面量一致）。
_SURFACE_BY_HEX = {
    dark: {_GRAY[level].upper(): tint for level, tint in _SURFACE_SWAP[dark].items()}
    for dark in (False, True)
}


def _tint(hex_: str, dark: bool) -> str:
    """把库灰阶里的一档换成品牌化后的那一档 —— 认不出就原样返回（小写）。

    只认灰阶：强调色那几档不归这张表管（它们在 `_ACCENT_SWAP` 里）。
    """
    return _SURFACE_BY_HEX[dark].get(hex_.upper(), hex_.lower())


def _from_qdarkstyle(theme_palette, *, name: str, dark: bool, domain: dict):
    """把 QDarkStyle 的色阶翻成我们的 `Palette`。

    **档位从库里读，颜色走品牌表** —— 这是这一版改造的要点。色阶的语义
    （`COLOR_BACKGROUND_1` 是主背景、`_4` 是边框/表头、`COLOR_TEXT_4` 是
    次要文字…）在 QDarkStyle 的 QSS 里是稳定的约定，我们跟着它走：库升级、
    重排色阶时，档位名不变，自绘控件与 QSS 仍然对得上。

    但库给的颜色是**它自己的那套**（中性灰 + 蓝强调），我们要的是新思紫：
    灰阶过 `_SURFACE_SWAP`（同档位的紫灰），强调色过 `_ACCENT_SWAP`
    （同档位的紫）。两处都只换颜色、不换档位，所以"哪块比哪块深"这层关系
    还是库定的，换色换不出对比度问题。

    取出来的 hex **一律转小写**：库里的常量是大写（`#FAFAFA`），而 `QColor.name()`
    给的是小写 —— 两处不一致的话，"这个颜色是不是那个颜色"的字符串比较会
    莫名其妙地判否（真踩过）。
    """
    def c(name_: str) -> str:
        """库色阶里的那一档，换成我们的颜色。"""
        return _tint(str(getattr(theme_palette, name_)), dark)

    brand = _ACCENT_SWAP[dark]
    role = _ACCENT_ROLES[dark]

    return Palette(
        name=name, dark=dark,
        # ── 骨架：对应色阶里的"底 / 交替 / 线 / 强调 / 选中" ──
        panel=c("COLOR_BACKGROUND_1"),
        panel_alt=c("COLOR_BACKGROUND_2"),
        text=c("COLOR_TEXT_1"),
        muted=c("COLOR_TEXT_4"),
        grid=c("COLOR_BACKGROUND_3"),
        border=c("COLOR_BACKGROUND_4"),
        # ── 强调色三档：**档位跟着库走，颜色走品牌表**（见上面那张表）──
        accent=brand[role["accent"]],
        # 选中底/字**必须和库实际用的那对一致**，否则自绘控件里选中的那一格
        # 和旁边 QSS 画的选中行是两个颜色（库用的是 ACCENT_2 + TEXT_1）
        selection=brand[role["selection"]],
        selection_text=c("COLOR_TEXT_1"),
        gutter_bg=c("COLOR_BACKGROUND_2"),
        current_line=brand[role["current_line"]],
        **domain,
    )


#: **浅色**（默认）—— 冷灰窗框 + 近白内容面 + 新思紫强调色
CLASSIC = _from_qdarkstyle(
    qdarkstyle.LightPalette, name="浅色", dark=False, domain=_LIGHT_DOMAIN)

#: **深色** —— 同一套层次关系反过来，强调色仍是新思紫
DARK = _from_qdarkstyle(
    qdarkstyle.DarkPalette, name="深色", dark=True, domain=_DARK_DOMAIN)

PALETTES: Dict[str, Palette] = {p.name: p for p in (CLASSIC, DARK)}
DEFAULT_THEME = CLASSIC.name


# ════════════════════════════════════════════════════════════
# 激活的那一套
# ════════════════════════════════════════════════════════════

#: 初始就是默认那一套 —— 没调过 `apply()` 时 `theme.current()` 也该给默认色，
#: 而不是「恰好写在文件靠前的那个」。
_current: Palette = CLASSIC


def current() -> Palette:
    return _current


def exists(name: str) -> bool:
    return name in PALETTES


def apply(app: Optional[QApplication], name: str) -> Palette:
    """切换主题 —— **Fusion 基底 + QDarkStyle 样式表**（含它自带的调色板）。

    三件事，顺序有讲究：

      · `QStyleFactory.create("Fusion")` —— 同一段 QSS 在不同平台原生风格下
        表现不一样（实测：给 `::drop-down` 写个 background，Windows 11 风格下
        下拉箭头直接消失）。先把基底固定成 Fusion，QSS 才可预测。
      · `app.setFont(...)` —— 中文回退链，否则部分控件是「豆腐块」。
      · `qdarkstyle.load_stylesheet(...)` —— 样式表**和 `QPalette` 一起**给：
        它内部会调 `_apply_application_patches` 把应用调色板也刷成配套的那套。
        所以我们**不再自己 setPalette** —— 那只是和它抢，谁后跑谁赢，
        哪天库改了顺序表现就变了。

    两个例外仍要我们自己按一下，都是"库给的是它那族蓝、而我们要紫"的地方：
    `QPalette` 的 Link（库用 `ACCENT_3` 刷，不吃样式表），以及 `QMdiArea` 的底
    （它抓的是一份构造时的快照），后者见 `WorkspaceArea.apply_theme`。
    """
    global _current
    ensure_fonts()                       # 先保证有字可用，再谈配色
    if name in PALETTES:
        _current = PALETTES[name]
    if app is not None:
        app.setFont(ui_font())
        app.setStyle(QStyleFactory.create("Fusion"))
        app.setStyleSheet(_stylesheet(_current))
        # 样式表管不到的那几处取色（富文本链接、少数按调色板取色的控件）走的
        # 是应用调色板。库只刷了 `Link` 一项，选中的 `Highlight` 还是 **Qt 默认
        # 的蓝 `#308cc6`**、`LinkVisited` 是品红 `#ff00ff` —— 那就是"另一份真相"：
        # 换个控件、换个 Qt 版本，它就可能从缝里冒出来。这里按品牌色一次性收编。
        app_palette = app.palette()
        app_palette.setColor(QPalette.ColorRole.Highlight, QColor(_current.selection))
        app_palette.setColor(QPalette.ColorRole.HighlightedText,
                             QColor(_current.selection_text))
        app_palette.setColor(QPalette.ColorRole.Link, QColor(_current.accent))
        app_palette.setColor(QPalette.ColorRole.LinkVisited,
                             QColor(_ACCENT_SWAP[_current.dark][_ACCENT_VISITED[_current.dark]]))
        app.setPalette(app_palette)
    return _current


def _qdarkstyle_palette(p: Palette):
    """这套配色对应 QDarkStyle 的哪个色板类 —— **只能给库自带的那两个**。

    这不是"偷懒没传我们的色板"，是**库这一版的接口就到这里**：
    `_load_stylesheet` 拿 `palette.ID` 判完深浅分支后，会把传进来的类**换成**
    它自己的 `LightPalette` / `DarkPalette`（ID 不认识还会直接 `sys.exit(1)`），
    而 QSS 里的颜色是 SCSS 编译时就写死的。所以这个参数实际只干两件事：
    选加载哪份 qss 资源、以及 `_apply_application_patches` 刷应用调色板。

    换色因此走另外两条路：QSS 文本替换（`_rebrand`）+ 图标逐像素替换
    （`_brand_icons`），两者都从 `_ACCENT_SWAP` 取色。
    """
    return qdarkstyle.DarkPalette if p.dark else qdarkstyle.LightPalette


def _stylesheet(p: Palette) -> str:
    """全局 QSS = **QDarkStyle 的样式表（换成新思紫）+ 我们那几条补充**。

    标准控件（按钮 / 表格 / 页签 / 滚动条 / 菜单 / 工具栏 / 输入框…）长什么样
    **一律交给 QDarkStyle**。早先这里手写了 1 万多字符的 QSS，等于把"一个 Qt
    应用该长什么样"重新描述一遍 —— 描述不全，还得跟着 Qt 版本追。
    """
    library = qdarkstyle.load_stylesheet(
        qt_api="pyside6", palette=_qdarkstyle_palette(p))
    # `_app_overlay` 的返回值以换行开头，直接接上就行（后加载的规则优先）
    return _rebrand(library, p.dark) + _app_overlay(p)


# ── 换色：把库那份 QSS 里的强调色改成品牌紫 ────────────────────────
#
# 为什么是"替换"而不是"重写规则"：库的 QSS 里强调色是**字面量 hex**（编译产物），
# 每份 QSS 里各出现四种（实测：浅色 `DAEDFF/9FCBFF/73C7FF/37AEFE`，
# 深色 `26486B/346792/1A72BB/259AE9`）。替换表就是这个映射，一眼看得全；
# 而在 `_app_overlay` 里重写 `QTableView::item:selected`、`QTabBar::tab:selected`
# 这一大堆规则，就又是"一处按钮两处描述"，正是本文件反复要避开的事。
#
# 图标是同一件事的延续：那批 `*_focus.png` 的像素**就是**强调色（浅色板用第五档
# `B70`、深色板用 `B80`），QSS 里换不了，只能把 PNG 也换掉。


def _rebrand(qss: str, dark: bool) -> str:
    """把库那份 QSS 里的强调色换成品牌紫（含它引用到的强调色图标）。

    替换的是**字面量 hex**：库的 QSS 是 SCSS 编译产物，颜色写死在文本里。
    **按档位精确替换**，不做模糊匹配 —— 一份 QSS 里就那四种强调色，连灰阶里
    最像的 `#9DA9B5` 也和它们差着 100 多，不存在误伤。
    """
    # 灰阶先换：整套窗框、边框、表头、交替行都在这儿（见 `_SURFACE_SWAP`）。
    # 顺序无所谓 —— 两张表的键（灰 / 蓝）在库的色阶里没有交集。
    for gray, tint in _SURFACE_BY_HEX[dark].items():
        qss = qss.replace(gray, tint.upper())
    for level, purple in _ACCENT_SWAP[dark].items():
        qss = qss.replace(_BLUE[level], purple.upper())
    qss = _brand_inactive_selection(qss, dark)
    return _brand_icons(qss, dark)


#: "**选中了，但焦点不在这个窗格**"那一档 —— 库给的是中性灰，我们**直接
#: 用选中色本身**（不是调淡一档的近似色）。
#:
#: 库的规矩是 `::item:selected:active` 用强调色、`:selected:!active` 退回
#: `BACKGROUND_3` 灰。这在通用主题里成立，在这个工作台里不成立：**点一下导航树，
#: 焦点立刻被中央标签页拿走** —— 于是"我现在在哪个模块"这唯一的视觉提示常年
#: 是灰的，品牌色只在鼠标按下的那一瞬看得见。所以两档合一：选中了就是紫的，
#: 跟焦点在不在无关。
#:
#: 从 `_ACCENT_SWAP` 现取，不另写 hex —— 这一档就是"选中色"，没有第二份定义。
_INACTIVE_SELECTION = {dark: _ACCENT_SWAP[dark][_ACCENT_ROLES[dark]["selection"]]
                       for dark in (False, True)}


def _brand_inactive_selection(qss: str, dark: bool) -> str:
    """把"非活动选中"那档灰换成选中色 —— **只改这一条选择器**。

    为什么不并进 `_ACCENT_SWAP` 一起做全局替换：那个灰（`#D2D5D8` / `#37414F`）
    在库里同时用在交替行、表头、悬停上，全局换会把它们一起染紫。这是唯一一处
    **必须按选择器**改的地方，所以单独一件事、单独一条注释。
    """
    import re

    color = _INACTIVE_SELECTION[dark]

    def per_rule(match) -> str:
        selector, body = match.group(1), match.group(2)
        if "::item:selected:!active" not in selector:
            return match.group(0)
        return selector + "{" + re.sub(
            r"background-color:\s*#[0-9A-Fa-f]{6}",
            f"background-color: {color.upper()}", body) + "}"

    return re.sub(r"([^{}]*)\{([^}]*)\}", per_rule, qss)


#: 认亲容差 —— 这批 PNG 的边缘像素带着抗锯齿杂色（实测强调色 `(37,154,233)`
#: 周围散布着 `(42,156,227)`、`(40,159,239)` 这类）。严格相等会把它们漏在原地，
#: 缩到 16px 就是一圈蓝边。取 8 是照着实测定的：再往下漏的就是 alpha ≤ 9 的
#: 杂点（3% 不透明度，肉眼不可见），再往上就朝着灰阶去了。
_ICON_TOLERANCE = 8


def _icon_cache_dir(dark: bool):
    """换过色的图标放这儿。

    不写进库目录（那是 site-packages，重装就没了），也不写进仓库 —— 它是
    **缓存**，随时可以丢。目录名带上"色表指纹 + 认亲容差 + 库版本"：改了品牌色、
    改了换色算法、或升级了 qdarkstyle，都自然落到一个新目录，不会读上一次留下的
    旧色图标。
    """
    from hashlib import md5
    from pathlib import Path
    from tempfile import gettempdir

    fingerprint = (repr(sorted(_ACCENT_SWAP[dark].items()))
                   + str(_ICON_TOLERANCE) + qdarkstyle.__version__)
    key = md5(fingerprint.encode()).hexdigest()[:8]
    name = "dark" if dark else "light"
    return Path(gettempdir()) / "signoffai-theme-icons" / f"{name}-{key}"


def _icon_sources():
    """库的强调色图标在磁盘上的位置 —— QSS 里的 `:/qss_icons/...` 就是它。"""
    from pathlib import Path

    return Path(qdarkstyle.__file__).resolve().parent


def _recolor_icon(src, swap_pairs) -> Optional[bytes]:
    """把图标里那几种强调色像素换成紫色，返回 PNG 字节；**没命中就返回 None**。

    这类图标是**单色 + alpha** 的（实测：一张 `checkbox_checked_focus.png` 里
    249 个不透明像素全是同一个强调色，其余是它的半透明边缘），所以只需换掉
    RGB、**alpha 原样保留** —— 边缘那一圈半透明像素跟着变成半透明的紫，
    图标形状与过渡都不动。

    没命中 = 这张图本来就不带强调色（`*_disabled` 那批是灰的），调用方据此
    **整张跳过**、QSS 里的 URL 也不动 —— 少一次文件读写，也少一个"为什么这个
    图标会被复制一份"的疑问。
    """
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    image = QImage(str(src))
    if image.isNull():
        return None
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    buf = bytearray(image.constBits())
    # 内存序是 B,G,R,A；先拆成裸 int，免得在内层循环里反复问 QColor 要分量
    targets = [(old.blue(), old.green(), old.red(),
                new.blue(), new.green(), new.red())
               for old, new in swap_pairs]
    hit = False
    for at in range(0, len(buf), 4):
        if buf[at + 3] == 0:               # 全透明像素没有颜色可换
            continue
        for ob, og, orr, nb, ng, nr in targets:
            if (abs(buf[at] - ob) <= _ICON_TOLERANCE
                    and abs(buf[at + 1] - og) <= _ICON_TOLERANCE
                    and abs(buf[at + 2] - orr) <= _ICON_TOLERANCE):
                buf[at], buf[at + 1], buf[at + 2] = nb, ng, nr
                hit = True
                break
    if not hit:
        return None
    # `QImage(bytes, ...)` 不持有那块缓冲，`.copy()` 之后才谈得上编码
    out = QImage(bytes(buf), image.width(), image.height(),
                 image.bytesPerLine(), QImage.Format.Format_ARGB32).copy()
    store = QByteArray()
    device = QBuffer(store)
    device.open(QIODevice.OpenModeFlag.WriteOnly)
    out.save(device, "PNG")
    return bytes(store)


#: QSS 里引用库图标的整条写法（含 `url(...)` 外壳）：`url(":/qss_icons/<主题>/rc/<名>")`。
#: **连外壳一起匹配**，是为了整条换掉 —— 只换路径的话得自己拼引号，拼错就是
#: `url("url("…")")` 这种套娃，Qt 会静默不加载，图标变成空白（真踩过）。
_ICON_REF = r"""url\((["']?):/qss_icons/(light|dark)/rc/([^"')\s]+)\1\)"""


def _brand_icons(qss: str, dark: bool) -> str:
    """把 QSS 里引用到的强调色图标换成紫色副本，并让 URL 指到副本上。

    库的图标名形如 `:/qss_icons/light/rc/branch_open_focus.png`，磁盘上就是
    `<qdarkstyle>/light/rc/branch_open_focus.png`。

    **不带强调色的图标原样留着**（整条 `url(...)` 不动，仍指向库的资源）——
    那批是灰的（`*_disabled`、`transparent` …），没有可换的颜色，复制一份
    只是浪费。
    """
    import re

    referenced = {(theme_, name) for _q, theme_, name in re.findall(_ICON_REF, qss)}
    mapping = _icon_url_map(dark, referenced)

    def rewrite(match) -> str:
        target = mapping.get((match.group(2), match.group(3)))
        return f'url("{target}")' if target else match.group(0)

    return re.sub(_ICON_REF, rewrite, qss)


def _icon_url_map(dark: bool, referenced) -> Dict[tuple, Optional[str]]:
    """`(主题, 图标名) → 换过色的副本路径`（`None` = 不带强调色，别管它）。

    **这张表跟副本一起缓存在磁盘上**，因为算它的代价不小：要把每张 PNG 拆开
    逐像素找强调色（几十张小图，首次约 150ms）。只缓存副本文件是不够的 ——
    那样每次还是得把每张图重新扫一遍，才知道该不该用它。

    表里缺哪张就补哪张（同一份库的 QSS 引用集合是固定的，缺的话说明库换过
    图标名了），补完整体落盘。
    """
    import json

    cache = _icon_cache_dir(dark)
    manifest = cache / "manifest.json"
    known: Dict[tuple, Optional[str]] = {}
    if manifest.exists():
        try:
            known = {tuple(key.split("|", 1)): value
                     for key, value in json.loads(manifest.read_text("utf-8")).items()}
        except (OSError, ValueError):
            known = {}                # 缓存坏了就重算，不是错误
    missing = [ref for ref in sorted(referenced) if ref not in known]
    if missing:
        pairs = [(QColor(_BLUE[level]), QColor(purple))
                 for level, purple in _ACCENT_SWAP[dark].items()]
        for ref in missing:
            known[ref] = _copy_brand_variant(cache, ref, pairs)
        cache.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({f"{t}|{n}": v for (t, n), v in known.items()}),
                            encoding="utf-8")
    return known


def _copy_brand_variant(cache, ref, pairs) -> Optional[str]:
    """换一张图（含 `@2x` 变体）并落到缓存，返回 QSS 里该用的 URL。

    `@2x` 必须跟着换 —— Qt 是按"同名带 @2x"自己去旁边找的，只换 1x 那版等于
    高分屏上还留着蓝的。
    """
    import os

    theme, name = ref
    variants = [name]
    if not name.endswith("@2x.png"):
        variants.append(name[:-4] + "@2x.png")
    # 只有**主名那一版**换成功了才改 URL —— QSS 引用的是主名，主名没换出来
    # 却把 URL 指过去，就是指向一个不存在的文件，图标直接空
    copied = False
    for variant in variants:
        src = _icon_sources() / theme / "rc" / variant
        if not src.exists():
            continue
        data = _recolor_icon(src, pairs)
        if data is None:
            continue
        cache.mkdir(parents=True, exist_ok=True)
        # 先写临时文件再改名：图标是给 Qt 直接读的，半截文件会画成空白
        tmp = cache / (variant + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, cache / variant)
        copied = copied or variant == name
    if not copied:
        return None
    # 正斜杠：QSS 的 url() 不认反斜杠（Windows 上会被当成转义）
    return str(cache / name).replace("\\", "/")


def _app_overlay(p: Palette) -> str:
    """**只碰本工作台自己的 objectName** 的那几条 QSS。

    守住这条边界很重要：一旦在这里写 `QPushButton { ... }`，就又是"两处各描述
    一遍按钮"，跟 QDarkStyle 打架 —— 谁后加载谁赢，升级库的时候表现会莫名其妙
    地变。而 `#paneHeader` 这种名字是**我们独有的**，库里不可能有，不冲突。
    """
    return f"""
    /* ── 以下每条都以本工作台自己的 objectName 开头 ── */

    QLabel#paneHeader {{ background: {p.panel_alt}; color: {p.text};
                         font-weight: bold; padding: 4px 8px;
                         border-bottom: 1px solid {p.border}; }}

    QWidget#paneHost {{ background: {p.panel}; }}

    /* 中央工作区**不是**滚动区，却被库那条通用的
       `QAbstractScrollArea {{ border: 1px; padding: 2px }}` 命中 —— 于是
       MDI 子窗口四周凭空多出 6px，标签页模式下露出三条边。它也不该有
       4px 圆角（嵌在分割器里，圆角只会跟相邻窗格对不齐）。 */
    QMdiArea#mdiArea {{ border: 0; padding: 0; border-radius: 0; }}
    """


# ════════════════════════════════════════════════════════════
# 语义配色表（保持旧名字，调用点不必改）
# ════════════════════════════════════════════════════════════

class _PaletteView:
    """把「当前配色」包成旧的名字，`theme.TEXT` / `theme.SEVERITY` 继续可用。

    做成只读视图而不是拷贝：切主题之后调用点拿到的自然是新值，
    不用满仓库改 import 或手动刷新。
    """

    def __getattr__(self, name: str):
        return getattr(_current, name)

    # ── 字典式访问，供 `theme.SEVERITY["error"]` 这种写法 ──

    @property
    def SEVERITY(self) -> Dict[str, QColor]:
        p = _current
        return {"error": QColor(p.error), "warning": QColor(p.warning),
                "info": QColor(p.info)}

    @property
    def COVERAGE(self) -> Dict[str, QColor]:
        p = _current
        return {"full": QColor(p.ok), "part": QColor(p.warning),
                "none": QColor(p.error), "derived": QColor(p.muted)}

    @property
    def CROSS_LEVEL(self) -> Dict[str, QColor]:
        p = _current
        return {"required": QColor(p.cross_required),
                "optional": QColor(p.cross_optional),
                "forbidden": QColor(p.cross_forbidden),
                "none": QColor(p.panel)}

    @property
    def MARK(self) -> Dict[str, QColor]:
        """交叉矩阵的标记色 —— 与 CROSS_LEVEL（底色）配对使用。"""
        p = _current
        return {"required": QColor(p.mark_required),
                "optional": QColor(p.mark_optional),
                "forbidden": QColor(p.mark_forbidden),
                "none": QColor(p.mark_none)}

    @property
    def TEXT(self) -> QColor:
        return QColor(_current.text)

    @property
    def MUTED(self) -> QColor:
        return QColor(_current.muted)

    @property
    def GRID(self) -> QColor:
        return QColor(_current.grid)

    @property
    def PANEL(self) -> QColor:
        return QColor(_current.panel)

    @property
    def GUTTER(self) -> QColor:
        return QColor(_current.gutter_bg)

    @property
    def ACCENT(self) -> QColor:
        return QColor(_current.accent)

    # ── 评分三档（概览页那个大分数用它，不写死 hex）──

    @property
    def GRADE_GOOD(self) -> QColor:
        return QColor(_current.score_good)

    @property
    def GRADE_WARN(self) -> QColor:
        return QColor(_current.score_warn)

    @property
    def GRADE_BAD(self) -> QColor:
        return QColor(_current.score_bad)


view = _PaletteView()


def __getattr__(name: str):
    """模块级动态属性（PEP 562）。

    让 `theme.TEXT` / `theme.SEVERITY` 这类访问**始终解析到当前激活的配色**
    —— 切主题之后不用改任何调用点、也不用手动刷新，下次重绘拿到的自然是新值。

    只在常规属性查找失败时才调用，所以 `theme.mono_font` / `theme.apply`
    这些真函数不受影响。
    """
    return getattr(view, name)


# ════════════════════════════════════════════════════════════
# 字体
# ════════════════════════════════════════════════════════════

#: 工程工具的字号偏小 —— 一屏能放下更多行，这正是「工程界面」的要点
UI_SIZE = 9
#: 等宽字号**比界面大一号**：代码区是「要盯着看」的地方，chrome 不是。
#: Verdi 的源码窗格也是这个关系。
MONO_SIZE = 10
ROW_HEIGHT = 22          # 表格行高：比 Qt 默认 24 紧凑，比原来的 20 松一点 ——
                         # 20 行连排时字挤在一起，"密"变成了"糊"
#: 概览页那个大分数的字号 —— 它是「一眼看到」的数字，写死在页面里会各页不一。
#: 26 而不是 30：那个数字旁边还有四行摘要，字号再大就把摘要挤成一条了。
SCORE_SIZE = 26

CJK_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                  "Noto Sans CJK SC", "WenQuanYi Micro Hei", "SimHei")

#: 字体库为空时按顺序试的字体文件 —— 覆盖三平台的常见位置
FALLBACK_FONT_FILES = (
    "C:/Windows/Fonts/msyh.ttc",          # 微软雅黑
    "C:/Windows/Fonts/simsun.ttc",        # 宋体
    "C:/Windows/Fonts/consola.ttf",       # Consolas（等宽）
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)


def ensure_fonts() -> int:
    """字体库为空时，从常见路径手动注册几款。

    为什么要这个：一个中文界面上全是「豆腐块」是没法用的。正常情况下 Qt 会自己
    枚举系统字体，这里什么都不做；但在枚举不到的环境（某些容器、CI、无头会话里
    跑 offscreen）就得手动喂给它。返回实际加载的字体数。

    必须在 QApplication 建好之后调用。
    """
    try:
        if QFontDatabase.families():
            return 0
    except Exception:                        # noqa: BLE001  还没建 app
        return 0

    from pathlib import Path
    loaded = 0
    for path in FALLBACK_FONT_FILES:
        if Path(path).exists() and QFontDatabase.addApplicationFont(path) >= 0:
            loaded += 1
    return loaded


#: 等宽候选 —— 兼顾 ASCII 好看的代码字体与中文覆盖
MONO_CANDIDATES = ("Consolas", "Cascadia Mono", "JetBrains Mono", "Menlo",
                   "DejaVu Sans Mono", "Courier New")


def _available(candidates) -> list:
    families = set(QFontDatabase.families())
    return [f for f in candidates if f in families]


def mono_font(size: int = MONO_SIZE) -> QFont:
    """等宽字体 —— 编辑器、矩阵标签、case_id 用。

    **用 setFamilies 组一条回退链**，而不是只设一个族：Consolas 没有中文字形，
    模型的注释与字段名大量是中文，只给它一个族的话中文全是「豆腐块」。
    Qt 会按顺序逐字找字形 —— ASCII 走 Consolas，中文落到后面的中文字体。
    """
    chain = _available(MONO_CANDIDATES) + _available(CJK_CANDIDATES)
    font = QFont()
    if chain:
        font.setFamilies(chain)
        font.setFamily(chain[0])
    else:
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(size)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    return font


def ui_font(size: int = UI_SIZE, bold: bool = False) -> QFont:
    """界面字体 —— 中文优先，后面挂一串回退。"""
    chain = _available(CJK_CANDIDATES) + _available(MONO_CANDIDATES)
    font = QFont()
    if chain:
        font.setFamilies(chain)
        font.setFamily(chain[0])
    font.setPointSize(size)
    font.setBold(bold)
    return font
