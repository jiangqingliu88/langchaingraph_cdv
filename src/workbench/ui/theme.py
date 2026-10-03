"""主题系统 —— 工程工具风（Verdi 那一类）。

放在 `ui/` 顶层而不是 `ui/widgets/` 下：**models 也要用**（诊断按严重度
着色、组织树按覆盖状况着色都在模型的 `data()` 里）。models 与 widgets 是
兄弟目录，把主题埋进 widgets 会逼着 models 反向依赖 widgets。

设计要点：模块级名字（`theme.TEXT` / `theme.SEVERITY` / `theme.mono_font()`）
**始终解析到当前激活的那套配色**，所以切换主题不用改任何调用点 ——
所有控件与模型下次重绘时自然跟上。

    from src.workbench.ui import theme
    painter.setPen(theme.TEXT)
    theme.apply(app, "经典 Verdi 浅灰")

两套预设：
  · **经典 Verdi 浅灰** —— Verdi 的本色：灰底、深蓝高亮、2px 立体边框。
    这是默认。工程工具用这套看久了不累，投影/截屏也清楚。
  · **深色（现代）**   —— 现代编辑器那种深色，长时间盯日志舒服。

> 早先那份深色叫「深色（Verdi 风）」是个误称 —— Verdi 本身是浅灰的，
> 没有深色主题。改名的同时把默认也换成了真正的 Verdi 观感。
>
> 本文件原在 `src/tools/casemodel_tools/view/gui/theme.py`，工作台第一轮
> 上提为平台通用件。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

# ════════════════════════════════════════════════════════════
# 一套配色
# ════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Palette:
    """一套完整配色。字段名就是用途，避免出现「这个灰到底指什么」。"""
    name: str
    dark: bool

    # ── 骨架 ──
    window: str          # 主背景
    panel: str           # 表格/画布背景
    panel_alt: str       # 交替行
    toolbar: str         # 工具栏/菜单栏
    statusbar: str       # 状态栏
    text: str            # 正文
    muted: str           # 次要文字（提示、行号、单位）
    grid: str            # 表格网格线
    border: str          # 分隔线、边框
    accent: str          # 强调（选中、链接、当前行号）
    selection: str       # 选中行背景

    # ── 语义 ──
    error: str
    warning: str
    info: str
    ok: str

    # ── 代码区 ──
    editor_bg: str
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

    # ══ 以下这一组是「chrome」—— 窗口边框、工具栏、页签那一层 ══
    # 它们**全部显式给值、不留默认**：漏一个就是一个看得见的缺陷（比如
    # 选中行深蓝底配深蓝字 = 一片糊），宁可写全也不要默认值把问题藏起来。

    # ── 立体边框：Windows classic 那套 2px 凸起/凹陷，Verdi 的观感一半靠它 ──
    bevel_light: str     # 凸起的上/左边
    bevel_dark: str      # 凸起的下/右边（也是所有普通边框）
    bevel_shadow: str    # 更深一档，用于菜单/对话框的外框

    # ── 菜单栏 ──
    # （没有「窗口标题栏」的字段：标题栏归操作系统，QSS 改不到它。真要做，
    #   得把窗口做成无边框自己画，那会丢掉原生的贴边/最大化，不值当。）
    menubar: str
    menu_highlight: str  # 菜单键盘导航的高亮条

    # ── 工具栏：是**竖向渐变**，不是平色 ──
    toolbar_grad_top: str
    toolbar_grad_bottom: str

    # ── 窗格 / 分割条 / 页签 ──
    pane_header: str       # 窗格顶部的标题条
    pane_header_text: str
    sash: str              # 分割条
    tab_active: str        # 页签正面（当前页）
    tab_inactive: str      # 页签背面

    # ── 选中态 ──
    selection_text: str  # 选中行前景。写 p.text 的话，深蓝底 + 深色字 = 看不见
    on_accent: str       # 压在 accent 上的文字

    # ── 表头：比面板深一截，是 Verdi 表头的样子 ──
    table_header: str
    table_header_text: str

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

    @property
    def toolbar_gradient(self) -> str:
        """工具栏/按钮用的竖向渐变 QSS 片段 —— 四处共用，写一次。"""
        return (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                f"stop:0 {self.toolbar_grad_top}, stop:1 {self.toolbar_grad_bottom})")

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


#: **经典 Verdi 浅灰** —— 数值全部来自一张真实 Verdi 截图的**像素采样**，
#: 不是凭印象调的（前两版分别是 Windows 2000 的土黄面灰和一套拼凑的深色，
#: 都不对）。采样点与结论：
#:
#: ```text
#: 窗格 / 表格 / 源码区   #e0e0e0   中性灰 —— 源码区也是灰的，不是白的
#: 菜单栏 / 工具栏        #c4d0e4 → #e0ecf4   浅蓝灰竖向渐变
#: 页签条                 #ecf0f8
#: 表头                   #a0a0a0  比面板深一截
#: 选中态                 #5858a4  蓝紫
#: 波形区                 #000000  纯黑，标尺 #808080
#: 正文                   #101014  近黑
#: ```
#:
#: 整体是**扁平**的：结构靠 1px 细线与表头色差划出来，没有 2px 立体凸起。
#: 唯一有渐变的地方是菜单栏/工具栏那两条横带 —— 那是 Verdi 的招牌观感。
CLASSIC = Palette(
    name="经典 Verdi 浅灰", dark=False,
    window="#e0e0e0", panel="#e0e0e0", panel_alt="#e8e8e8",
    toolbar="#d4e0ee", statusbar="#d8e4f4",
    text="#101010", muted="#606060", grid="#b8b8b8", border="#909090",
    accent="#5858a4", selection="#5858a4",
    error="#a80000", warning="#8a5300", info="#000080", ok="#006000",
    editor_bg="#e0e0e0", gutter_bg="#d8d8d8", current_line="#cfdcee",
    syn_key="#0000a0", syn_string="#006000", syn_number="#7a4a00",
    syn_bool="#800080", syn_comment="#707070", syn_marker="#707070",
    syn_anchor="#7a4a00", syn_enum="#4a3a8a", syn_meta="#005f6b",
    cross_required="#f0c8c8", cross_optional="#f0e4b0",
    cross_forbidden="#d0d0d0",
    mark_required="#800000", mark_optional="#806000",
    mark_forbidden="#606060", mark_none="#a8a8a8",
    # 扁平：浅的那道边只比底色亮一点，深的那道边才画结构
    bevel_light="#f2f2f2", bevel_dark="#909090", bevel_shadow="#606060",
    menubar="#d8e2f0", menu_highlight="#5858a4",
    toolbar_grad_top="#e8f0f8", toolbar_grad_bottom="#c4d4e8",
    pane_header="#e0e0e0", pane_header_text="#101010", sash="#a0a0a0",
    tab_active="#f2f6fb", tab_inactive="#dde8f4",
    selection_text="#ffffff", on_accent="#ffffff",
    table_header="#a0a0a0", table_header_text="#101010",
    score_good="#006000", score_warn="#8a5300", score_bad="#a80000",
    banner_error_bg="#fbeaea", banner_error_fg="#a80000",
    banner_warning_bg="#faf3e0", banner_warning_fg="#7a4a00",
    banner_info_bg="#e8f0f8", banner_info_fg="#0a3a6a",
)

#: **深色（现代）** —— 现代编辑器那种深色，长时间盯日志舒服。
#: 早先它叫「深色（Verdi 风）」是个误称：Verdi 本身是浅灰的，没有深色主题。
DARK = Palette(
    name="深色（现代）", dark=True,
    window="#1e2227", panel="#262b31", panel_alt="#2b3138",
    toolbar="#2a3037", statusbar="#22272c",
    text="#d6dae0", muted="#8a94a0", grid="#3a4149", border="#454d56",
    accent="#4a90d9", selection="#2f4a6b",
    error="#ff6b6b", warning="#ffb454", info="#5aa9e6", ok="#6cc070",
    editor_bg="#22272c", gutter_bg="#1b1f24", current_line="#2b3440",
    syn_key="#7fb3ff", syn_string="#9cdc8a", syn_number="#f0a45d",
    syn_bool="#c586c0", syn_comment="#6f7f6f", syn_marker="#8a94a0",
    syn_anchor="#f0a45d", syn_enum="#dcdcaa", syn_meta="#63b8c9",
    cross_required="#5c2b2f", cross_optional="#4d441f",
    cross_forbidden="#3a3f45",
    mark_required="#ff9d9d", mark_optional="#ffd479",
    mark_forbidden="#9aa4ae", mark_none="#5c666f",
    bevel_light="#4a525c", bevel_dark="#161a1e", bevel_shadow="#0e1114",
    menubar="#2a3037", menu_highlight="#2f4a6b",
    toolbar_grad_top="#333a42", toolbar_grad_bottom="#262b31",
    pane_header="#2a3037", pane_header_text="#d6dae0", sash="#3a4149",
    tab_active="#262b31", tab_inactive="#2a3037",
    # accent 是浅蓝，压在上面的字得是深色 —— 这里和 CLASSIC 是相反的
    selection_text="#ffffff", on_accent="#1e2227",
    table_header="#333a42", table_header_text="#d6dae0",
    score_good="#6cc070", score_warn="#ffb454", score_bad="#ff6b6b",
    banner_error_bg="#3a2326", banner_error_fg="#ff9d9d",
    banner_warning_bg="#3a3220", banner_warning_fg="#ffd479",
    banner_info_bg="#20303a", banner_info_fg="#9ac4e8",
)

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
    """切换主题并生成全局样式表 —— 返回新的配色。

    样式表在 QApplication 上，所以一次设置全体生效；调用方只需在切换后
    让自绘控件重画（`update()`）。
    """
    global _current
    ensure_fonts()                       # 先保证有字可用，再谈配色
    if name in PALETTES:
        _current = PALETTES[name]
    if app is not None:
        # 设**应用级字体**：中文界面上部分控件落到没有中文字形的默认字体，
        # 就会渲染成「豆腐块」。这一行让所有控件都拿到带中文的回退链。
        app.setFont(ui_font())
        app.setStyleSheet(_stylesheet(_current))
    return _current


def _stylesheet(p: Palette) -> str:
    """全局 QSS —— Verdi 的观感靠它：灰底、深蓝高亮、2px 立体边框、密集小字号。

    四条**踩过的坑**写在这里，改的时候别踩回去：

    1. **不写 `QDockWidget` 规则**。工作台用三窗格分割条，一个 dock 都没有 ——
       写了就是死代码，下一个人会以为还有 dock 需要照顾。
    2. **`QToolButton` 一律限定在 `QToolBar` 里**。页签的滚动箭头、下拉框的箭头
       也是这个类，全局写会把它们一起涂成工具栏按钮。
    3. **`QTabBar::tab` 是全局的**，会同时作用到窗格页签与 case 建模模块内层那
       11 个页签 —— 对 Verdi 来说这是对的（它的内层页签也长这样）。
    4. **不写 `QToolBar::handle`**：主工具栏 `setMovable(False)`，那条规则永远
       不会渲染。
    """
    bevel = (f"border: 1px solid {p.bevel_dark}; "
             f"border-top-color: {p.bevel_light}; "
             f"border-left-color: {p.bevel_light};")
    sunken = (f"border: 1px solid {p.bevel_light}; "
              f"border-top-color: {p.bevel_shadow}; "
              f"border-left-color: {p.bevel_shadow};")
    return f"""
    QWidget {{ background: {p.window}; color: {p.text};
               font-size: 9pt; }}

    /* ── 菜单栏 / 菜单 ── */
    QMenuBar {{ background: {p.menubar}; color: {p.text};
                border-bottom: 1px solid {p.bevel_dark}; padding: 1px 2px; }}
    QMenuBar::item {{ background: transparent; padding: 3px 9px; }}
    QMenuBar::item:selected {{ background: {p.menu_highlight};
                               color: {p.on_accent}; }}
    QMenu {{ background: {p.panel}; color: {p.text};
             border: 1px solid {p.bevel_shadow}; padding: 2px; }}
    QMenu::item {{ padding: 4px 26px 4px 26px; }}
    QMenu::item:selected {{ background: {p.menu_highlight};
                            color: {p.on_accent}; }}
    QMenu::item:disabled {{ color: {p.muted}; }}
    QMenu::separator {{ height: 1px; background: {p.bevel_dark};
                        margin: 3px 4px; }}
    QMenu::indicator {{ width: 13px; height: 13px; }}

    /* ── 工具栏：竖向渐变 + 图标按钮的立体反馈 ── */
    QToolBar {{ background: {p.toolbar_gradient}; border: none;
                border-bottom: 1px solid {p.bevel_dark};
                spacing: 2px; padding: 2px 4px; }}
    QToolBar::separator {{ width: 1px; margin: 3px 5px;
                           background: {p.bevel_dark};
                           border-right: 1px solid {p.bevel_light}; }}
    QToolBar QToolButton {{ padding: 3px 7px; margin: 1px;
                            background: transparent; color: {p.text};
                            border: 1px solid transparent; border-radius: 0; }}
    QToolBar QToolButton:hover {{ {bevel}
                                  background: {p.toolbar_grad_top}; }}
    QToolBar QToolButton:pressed {{ {sunken}
                                    background: {p.toolbar_grad_bottom}; }}
    QToolBar QToolButton:checked {{ {sunken}
                                    background: {p.toolbar_grad_bottom}; }}
    QToolBar QToolButton:disabled {{ color: {p.muted}; }}
    QToolBar QToolButton::menu-indicator {{ image: none; }}

    /* ── 按钮：扁平（参考图里的按钮没有立体凸起）── */
    QPushButton {{ background: {p.toolbar}; color: {p.text};
                   border: 1px solid {p.bevel_dark};
                   padding: 3px 12px; border-radius: 0; }}
    QPushButton:hover {{ background: {p.toolbar_grad_top}; }}
    QPushButton:pressed {{ background: {p.toolbar_grad_bottom}; }}
    QPushButton:disabled {{ color: {p.muted}; }}
    QPushButton:default {{ border: 1px solid {p.bevel_shadow}; }}

    /* ── 页签：浅蓝灰的窄条，扁平 ── */
    QTabWidget::pane {{ background: {p.panel};
                        border: 1px solid {p.bevel_dark}; top: -1px; }}
    QTabBar::tab {{ background: {p.tab_inactive}; color: {p.text};
                    border: 1px solid {p.bevel_dark}; border-bottom: none;
                    padding: 3px 11px; margin-right: 2px; }}
    QTabBar::tab:selected {{ background: {p.tab_active};
                             border-bottom: 1px solid {p.tab_active};
                             font-weight: bold; }}
    QTabBar::tab:hover:!selected {{ background: {p.toolbar_grad_top}; }}
    QTabBar::close-button {{ image: none; }}
    QTabBar QToolButton {{ background: {p.tab_inactive};
                           border: 1px solid {p.bevel_dark}; }}

    /* ── 窗格标题条（三窗格的名字就显示在这里）── */
    QLabel#paneHeader {{ background: {p.toolbar_gradient};
                         color: {p.pane_header_text}; font-weight: bold;
                         padding: 2px 6px;
                         border-bottom: 1px solid {p.bevel_dark}; }}
    QWidget#paneHost {{ background: {p.window}; }}

    /* ── 表头：比面板深一截的实色（Verdi 表头是 #a0a0a0 那种中灰），
          左上角那个方块也得跟着，否则缺一角 ── */
    QHeaderView::section {{ background: {p.table_header};
                            color: {p.table_header_text};
                            border: none;
                            border-right: 1px solid {p.bevel_dark};
                            border-bottom: 1px solid {p.bevel_dark};
                            padding: 3px 6px; font-weight: bold; }}
    QTableView QTableCornerButton::section {{
        background: {p.table_header}; border: none;
        border-right: 1px solid {p.bevel_dark};
        border-bottom: 1px solid {p.bevel_dark}; }}

    /* ── 表格 / 树 ── */
    QTableView, QTreeView, QListView {{ background: {p.panel};
                             alternate-background-color: {p.panel_alt};
                             gridline-color: {p.grid};
                             selection-background-color: {p.selection};
                             selection-color: {p.selection_text};
                             border: 1px solid {p.bevel_dark}; }}
    QTableView::item, QTreeView::item, QListView::item {{ padding: 1px 4px; }}
    QTableView::item:selected, QTreeView::item:selected,
    QListView::item:selected {{ background: {p.selection};
                                color: {p.selection_text}; }}
    QTreeView::branch {{ background: transparent; }}

    /* ── 文本区 ── */
    QPlainTextEdit, QTextEdit {{ background: {p.editor_bg}; color: {p.text};
                                 {sunken}
                                 selection-background-color: {p.selection};
                                 selection-color: {p.selection_text}; }}

    /* ── 滚动条：经典方头带立体槽 ── */
    QScrollBar:vertical {{ background: {p.window}; width: 14px;
                           border-left: 1px solid {p.bevel_dark}; }}
    QScrollBar:horizontal {{ background: {p.window}; height: 14px;
                             border-top: 1px solid {p.bevel_dark}; }}
    QScrollBar::handle {{ background: {p.toolbar_gradient};
                          border: 1px solid {p.bevel_dark};
                          min-height: 24px; min-width: 24px; margin: 0; }}
    QScrollBar::handle:hover {{ background: {p.toolbar_grad_top}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ background: {p.window};
                          {bevel} width: 14px; height: 14px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: {p.window}; }}

    /* ── 分割条：三窗格的分界就是它 ── */
    QSplitter::handle {{ background: {p.sash}; }}
    QSplitter::handle:hover {{ background: {p.accent}; }}
    QSplitter::handle:horizontal {{ width: 4px;
        border-left: 1px solid {p.bevel_light};
        border-right: 1px solid {p.bevel_dark}; }}
    QSplitter::handle:vertical {{ height: 4px;
        border-top: 1px solid {p.bevel_light};
        border-bottom: 1px solid {p.bevel_dark}; }}

    /* ── 状态栏：分区凹陷 ── */
    QStatusBar {{ background: {p.statusbar}; color: {p.text};
                  border-top: 1px solid {p.bevel_dark}; }}
    QStatusBar::item {{ border: none; }}
    QStatusBar QLabel {{ background: {p.window}; {sunken}
                         padding: 1px 6px; }}

    QLabel {{ background: transparent; }}
    QToolTip {{ background: {p.panel}; color: {p.text};
                border: 1px solid {p.bevel_shadow}; padding: 3px; }}

    /* ── 输入控件 ── */
    QComboBox, QLineEdit, QSpinBox {{ background: {p.editor_bg}; color: {p.text};
                            {sunken} padding: 2px 6px; border-radius: 0; }}
    QComboBox::drop-down {{ border-left: 1px solid {p.bevel_dark}; width: 16px;
                            background: {p.toolbar_gradient}; }}
    QComboBox QAbstractItemView {{ background: {p.panel}; color: {p.text};
                            border: 1px solid {p.bevel_shadow};
                            selection-background-color: {p.selection};
                            selection-color: {p.selection_text}; }}
    QCheckBox, QRadioButton {{ spacing: 5px; }}
    QCheckBox::indicator, QRadioButton::indicator {{
                            width: 13px; height: 13px;
                            background: {p.editor_bg}; {sunken} }}
    QCheckBox::indicator:checked {{ background: {p.accent}; }}
    QRadioButton::indicator {{ border-radius: 7px; }}

    /* ── 其它 ── */
    QGroupBox {{ border: 1px solid {p.bevel_dark}; margin-top: 8px;
                 padding-top: 6px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 8px;
                        padding: 0 3px; background: transparent; }}
    QProgressBar {{ background: {p.window}; {sunken} text-align: center; }}
    QProgressBar::chunk {{ background: {p.accent}; }}
    QScrollArea {{ background: {p.window}; border: 1px solid {p.bevel_dark}; }}
    QDialog, QMessageBox {{ background: {p.window}; }}
    QMessageBox QLabel {{ background: transparent; }}
    QSizeGrip {{ background: transparent; width: 12px; height: 12px; }}
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
ROW_HEIGHT = 20          # 表格行高，比默认 24 更紧凑
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
