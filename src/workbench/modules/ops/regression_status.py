"""回归状态 —— 这次回归哪条挂了、挂的是什么错。

形状对齐 ExecMan 的回归报表（Figure 32）：一个用例一行，状态用彩色徽章，
后面跟 UVM 消息计数、断言错误数、日志入口、备注。

**数据来自 `src/tools/flow_tools.api:run_regression_status`** —— 模块只负责显示，
判定逻辑（状态怎么定、错因怎么分类）都在工具层，这是全仓库的分层纪律。
订阅 `run.selected`：在「运行历史」里选一次运行，本页跟着切。

两处刻意的诚实设计：

  · **状态带来源**。框架判完落盘的 `status.env` / `report.json` 是**记录**；
    旧运行两者都没有时退回「按配置同源的规则从日志**推断**」。推断会标出来 ——
    不能让推断冒充权威结论，那正是本项目反复踩过的坑。
  · **徽章文案用 detail 而非 status**。`fail` 太粗，ExecMan 那列本来就是分类
    （断言挂 / UVM 挂）。detail 只依据从日志里**数出来的**事实。

## 点一下就打开（人工校对的那条路）

「看回归结论」的下一个动作永远是「让我自己看一眼」。所以这一页把三条路都摆在
一格里（列号见 `COLUMN_INDEX`）：

    点 用例名  → 这轮**实际产出的那门业务**（波形 / 覆盖率；两个都有就让你选）
    点 波形   → 直接开波形（WLF 用系统默认程序，装了 Questa 就是它的波形窗）
    点 覆盖率 → 直接开覆盖率**报告**（覆盖率库是二进制，人看不了 —— 见
                `coverage_tools.cov_api`，那里先用 vcover 摊成 HTML）
    双击某行  → 仿真日志（原来的行为）

**单击与双击会打架**（双击必然先来一次单击），所以「名字列」的单击动作**推迟到
双击窗口之后**再执行，双击一到就取消 —— 否则双击看日志会顺手多开一个波形窗。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import QModelIndex, Qt, QTimer
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton,
                               QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from ...ui import theme
from ...ui.helpers import tables as table_helpers
from ...ui.models import CENTER, LEFT, RowsModel
from ..base import ModuleBase
from . import cov_actions

#: (键, 表头, 列宽, 对齐)。键是 `run_regression_status` 行里的英文键。
#: 末两列（备注 / 编译配置）放窄一点，把宽度让给用例名与日志路径。
COLUMNS = (
    ("name", "用例", 250, LEFT),
    ("detail", "状态", 130, CENTER),
    ("sim_time", "耗时(s)", 70, CENTER),
    ("uvm_error", "UVM_Error", 80, CENTER),
    ("uvm_warning", "UVM_Warn", 80, CENTER),
    ("uvm_info", "UVM_Info", 80, CENTER),
    # ExecMan 报表里这列叫 Vcs_Assertion_Error；措辞随仿真器变（我们在 Questa 上），
    # 所以表头用中性的「断言错误」，含义不变。
    ("assert_error", "断言错误", 80, CENTER),
    ("host", "主机", 120, LEFT),
    ("log", "日志", 300, LEFT),
    # 波形 / 覆盖率两列：这轮开了对应业务才有内容，**点一下就直接打开**（见
    # `_on_cell_clicked`）。它们和「日志」放一起：人校对的顺序就是
    # 「哪条挂了 → 看日志 → 看波形/覆盖率」。
    ("wave", "波形", 230, LEFT),
    ("cov", "覆盖率", 230, LEFT),
    ("comment", "备注", 200, LEFT),
    ("build", "编译配置", 160, LEFT),
)

#: 列名 → 列号。口径只有这一处 —— 上面那张表改了列序，这里跟着变，
#: 不用在几个处理函数里各写一遍魔数。
COLUMN_INDEX = {key: i for i, (key, _t, _w, _a) in enumerate(COLUMNS)}

#: 状态 → 徽章底色。键是 `detail`（分类后的），不是粗粒度的 pass/fail ——
#: 「这条挂了」和「为什么挂」是两件事，颜色标的是后者。
BADGE_COLORS = {
    "pass": "#5cb85c",              # 绿
    "assertion_error": "#d9534f",   # 红 —— 断言挂
    "uvm_error": "#d9534f",         # 红 —— UVM 报错
    "fail": "#d9534f",              # 红 —— 挂了但没数出错因
    "unknown": "#f0ad4e",           # 琥珀 —— 没证据，不等于通过
}

#: 徽章上的显示文案（英文短标签，宽度有限）
BADGE_LABELS = {
    "pass": "pass",
    "assertion_error": "assert_err",
    "uvm_error": "uvm_error",
    "fail": "fail",
    "unknown": "unknown",
}


class StatusBadgeDelegate(QStyledItemDelegate):
    """把状态列画成圆角彩色徽章。

    `RowsModel` 只做「文字 + 前景色」，画不出底色块 —— 而这一列的状态分类
    靠颜色扫读最有效（ExecMan 也是这么做的）。所以在这一列挂个 delegate。

    注意读的是 **DisplayRole**，也就是走的是视图挂的排序代理；排序后行号会变，
    但 delegate 拿到的 index 已经映射好了，不需要自己换算。
    """

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        raw = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        if not raw:
            return
        # 选中态：先铺高亮底，否则徽章会盖住选中反馈
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        color = QColor(BADGE_COLORS.get(raw, BADGE_COLORS["unknown"]))
        rect = option.rect
        badge_w = min(118, rect.width() - 6)
        badge_h = min(20, rect.height() - 4)
        x = rect.x() + (rect.width() - badge_w) // 2
        y = rect.y() + (rect.height() - badge_h) // 2

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(x, y, badge_w, badge_h, 4, 4)
        painter.setPen(QPen(QColor("white")))
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(x, y, badge_w, badge_h, Qt.AlignmentFlag.AlignCenter,
                         BADGE_LABELS.get(raw, raw))
        painter.restore()


class RegressionStatusModule(ModuleBase):
    """回归用例状态表（只读）。"""

    HINT = ("一个用例一行。状态：绿=通过、红=挂了（断言/UVM，见徽章文案）、"
            "琥珀=没证据（日志为空或推不出来，**不等于通过**）。数据源是这次运行"
            "已落盘的回归产物，不重跑。　"
            "校对：点用例名开这轮的波形/覆盖率，点波形列直接开波形，"
            "点覆盖率列直接开覆盖率报告（HTML），双击某行开仿真日志。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id = ""
        self._rows: List[Dict[str, Any]] = []
        self.summary_label: QLabel | None = None
        self.notes_label: QLabel | None = None

    # ════════════════════════════════════════════════════════
    # 搭界面
    # ════════════════════════════════════════════════════════

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QHBoxLayout()
        self.summary_label = QLabel("", root)
        self.summary_label.setStyleSheet("font-weight: bold;")
        head.addWidget(self.summary_label)
        head.addStretch(1)
        # 「打开总覆盖率」：逐条用例的结论在这张表里，**整个环境**的覆盖率在
        # 覆盖率页那边。看这张表的人下一个问题往往就是"那总的覆盖了多少" ——
        # 给一个按钮，别让他去翻左树。
        self.btn_total_coverage = QPushButton("打开总覆盖率报告", root)
        self.btn_total_coverage.setToolTip(
            "整个环境合并后的覆盖率报告。优先打开覆盖率阶段已经生成的那一份"
            "（`sim/coverage/reports/index.html`）；没有再拿合并库现生成。")
        self.btn_total_coverage.clicked.connect(self.open_total_coverage)
        head.addWidget(self.btn_total_coverage)
        layout.addLayout(head)

        self.notes_label = QLabel("", root)
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.notes_label)

        self.run_dir: str = ""          # 当前运行目录（一键定位拼路径用）
        self.model = RowsModel(COLUMNS, root)
        self.table = table_helpers.configure_table(root, self.model)
        # 状态列挂徽章 delegate；`detail` 是第 2 列（0 基下的 1）
        self.table.setItemDelegateForColumn(1, StatusBadgeDelegate(self.table))
        # **一键定位**：双击一行 → 打开那条用例的仿真日志。
        # 这一页的全部价值是"哪条挂了、挂的是什么错"，而下一个动作永远是
        # "让我看看日志" —— 原先是自己去翻 <run>/regression_run/build_*/test_*/。
        self.table.doubleClicked.connect(self._on_row_activated)
        # 单击：名字/波形/覆盖率三格各自直接打开对应该看的东西（见模块文档）
        self.table.clicked.connect(self._on_cell_clicked)
        self._pending_click: QTimer | None = None
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_row_menu)
        layout.addWidget(self.table, 1)
        return root

    # ════════════════════════════════════════════════════════
    # 一键定位：从用例行跳到它的日志 / 目录
    # ════════════════════════════════════════════════════════

    def _row_at(self, index) -> Dict[str, Any]:
        """表格坐标 → 那一行的数据（拿不到就空 dict）。

        **必须过一遍排序代理**。视图挂的是 `SortProxy`（`configure_table` 自动包
        的那层），表头一点排序，视图行号就和数据行号对不上了 —— 直接拿
        `index.row()` 去索引会稳定地打开**另一条**用例的日志/波形。点开的是别人的
        数据，比点不开坏得多。原来只有双击一条路，这个错一直藏着。
        """
        if index is None or not index.isValid():
            return {}
        model = index.model()
        if model is not self.model and hasattr(model, "mapToSource"):
            index = model.mapToSource(index)
        rows = getattr(self, "_rows", None) or []
        if 0 <= index.row() < len(rows):
            return rows[index.row()] or {}
        return {}

    @staticmethod
    def _short_path(raw: str, run_dir: str = "") -> str:
        """列里显示的**短路径** —— 只留用例目录往后那一段。

        完整路径（`D:/SignOffAI/output_x/regression_run/build_.../test_.../waves/a.wlf`）
        把列撑满、真正有信息量的尾部反而被截掉。`work_dir` 是这条用例的目录。
        """
        if not raw:
            return ""
        try:
            p = Path(raw)
            base = str(run_dir or "")
            if base:
                try:
                    return p.relative_to(base).as_posix()
                except ValueError:
                    pass
            # 不在用例目录下（旧运行/绝对路径对不上）→ 退到尾部几段，
            # 至少让"是哪个文件"看得出来
            return "/".join(p.parts[-3:]) if len(p.parts) > 3 else str(p)
        except (TypeError, ValueError):
            return str(raw)

    def _case_log_path(self, row: Dict[str, Any]) -> str:
        """这一行的仿真日志**绝对路径**。

        `log` 列可能是相对运行目录的路径（框架产物就这样），所以拼一次；
        拼完仍不存在就返回空 —— 不返回一个"看起来能打开"的假路径。
        """
        raw = str(row.get("log", "") or "").strip()
        if not raw:
            return ""
        # **相对路径的基准不止一个**：实测 `log` 列给的是**相对项目根**的
        # （`output_xxx/regression_run/build_.../sim_vsim.log`），不是相对运行目录。
        # 所以依次试：原样（绝对路径 / 相对 cwd）→ 拼运行目录。
        # 全都不是就返回空 —— 不返回一个"看起来能打开"的假路径。
        candidates = [Path(raw)]
        if not Path(raw).is_absolute() and self.run_dir:
            candidates.append(Path(self.run_dir) / raw)
        for cand in candidates:
            if cand.exists():
                # **必须 resolve()**：候选可能是相对路径（框架产物就写相对运行根），
                # 而 `QUrl.fromLocalFile(相对路径)` 打开的是一片空气 —— 不报错、也
                # 什么都不弹。返相对路径出去，这页的点击就是"点了没反应"。
                return str(cand.resolve())
        return ""

    def _case_wave_path(self, row: Dict[str, Any]) -> str:
        """这一行的**波形文件**绝对路径（没有就空串 —— 别给个打不开的假路径）。

        与 `_case_log_path` 同样先试原样、再拼运行目录：工具层给的是扫出来的
        真实路径，但基准目录随调用方而异（相对运行根 / 绝对），两种都得认。
        """
        raw = str(row.get("wave", "") or "").strip()
        if not raw:
            return ""
        candidates = [Path(raw)]
        if not Path(raw).is_absolute() and self.run_dir:
            candidates.append(Path(self.run_dir) / raw)
        for cand in candidates:
            if cand.exists():
                # **必须 resolve()**：候选可能是相对路径（框架产物就写相对运行根），
                # 而 `QUrl.fromLocalFile(相对路径)` 打开的是一片空气 —— 不报错、也
                # 什么都不弹。返相对路径出去，这页的点击就是"点了没反应"。
                return str(cand.resolve())
        return ""

    def _case_cov_path(self, row: Dict[str, Any]) -> str:
        """这一行的**覆盖率库**绝对路径（没有就空串）。同 `_case_log_path` 的兜底。"""
        raw = str(row.get("cov", "") or "").strip()
        if not raw:
            return ""
        candidates = [Path(raw)]
        if not Path(raw).is_absolute() and self.run_dir:
            candidates.append(Path(self.run_dir) / raw)
        for cand in candidates:
            if cand.exists():
                # **必须 resolve()**：候选可能是相对路径（框架产物就写相对运行根），
                # 而 `QUrl.fromLocalFile(相对路径)` 打开的是一片空气 —— 不报错、也
                # 什么都不弹。返相对路径出去，这页的点击就是"点了没反应"。
                return str(cand.resolve())
        return ""

    def _open_case_wave(self, row: Dict[str, Any]) -> None:
        """打开这条用例的波形。

        **不是**交给系统默认程序 —— `.wlf` 在 Windows 上没有关联，双击只会弹
        "选择打开方式"。实现放在 `ops.cov_actions` 里（回归波形页点一行走的是
        同一条路）：用 Questa Visualizer（`visualizer.exe <wlf>`）直接拉起，
        并显式检查成败，不"假报成功"。
        """
        cov_actions.open_wave(self, self._case_wave_path(row))

    def _open_case_coverage(self, row: Dict[str, Any]) -> None:
        """打开这条用例的**覆盖率报告**。

        **不是**打开覆盖率库 —— 那是二进制，双击它人什么也看不到。实现放在
        `ops.cov_actions` 里（回归覆盖率页点一行走的是同一条路）—— 两处各写一遍
        的代价是行为会漂：一个页面复用已有报告、另一个每次重跑 vcover。
        """
        cov_actions.open_case_coverage(self, self._case_cov_path(row))

    def _open_case_coverage_visualizer(self, row: Dict[str, Any]) -> None:
        """用 Visualizer 打开这条用例的覆盖率库 —— 可下钻看这个 test 覆盖到啥。"""
        cov_actions.open_case_coverage_visualizer(self, self._case_cov_path(row))

    def open_total_coverage(self) -> None:
        """打开**整个环境**的总覆盖率报告（页头那个按钮 + 右键入口）。"""
        cov_actions.open_total_coverage(self, self.run_dir)

    def open_total_coverage_visualizer(self) -> None:
        """用 Visualizer 打开**合并覆盖率库** —— 可下钻看整体还差哪些 bin。"""
        cov_actions.open_total_coverage_visualizer(self, self.run_dir)

    def _open_case_artifact(self, row: Dict[str, Any], pos=None) -> None:
        """点「用例名」时的落点：**这轮实际产出的那门业务**。

        判断依据是**磁盘上有没有产物**，不是工具栏下拉当前选的是什么 ——
        那次运行用的是当时的选择，之后下拉可能早换了；按当前下拉去开，开的是
        "你以为跑过的"东西。

        一门业务有就直接开（这才是"直接打开"）；两门都有就问一句 ——
        一个点击对应两个窗口，猜哪个都不是好猜的。
        """
        from PySide6.QtWidgets import QMenu

        wave = self._case_wave_path(row)
        cov = self._case_cov_path(row)
        if wave and cov:
            menu = QMenu(self.table)
            menu.addAction("打开波形", lambda: self._open_case_wave(row))
            menu.addAction("打开覆盖率报告", lambda: self._open_case_coverage(row))
            menu.addAction("在 Visualizer 看覆盖率",
                           lambda: self._open_case_coverage_visualizer(row))
            menu.addSeparator()
            menu.addAction("打开仿真日志", lambda: self._open_case_log(row))
            anchor = pos or self.table.viewport().rect().center()
            menu.exec(self.table.viewport().mapToGlobal(anchor))
            return
        if wave:
            self._open_case_wave(row)
            return
        if cov:
            self._open_case_coverage(row)
            return
        # 两门业务都没产物：把"为什么"说清楚，别让人以为是这一页坏了
        self.set_status(f"{row.get('name', '这条用例')}：这轮没产出波形也没产出覆盖率"
                        " —— 回归的仿真业务里没开 `wave`/`cov`")

    # ════════════════════════════════════════════════════════
    # 点击分发（单击开业务产物，双击开日志）
    # ════════════════════════════════════════════════════════

    def _defer_click(self, action) -> None:
        """把一次单击**推迟到双击窗口之后**再执行。

        双击必然先送达一次单击。名字列上单击是"开业务产物"、双击是"开日志" ——
        不推迟的话，双击看日志会顺手多开一个波形窗口（实测的体感就是"点了两下，
        弹了三个窗"）。双击一到就 `_cancel_click`，单击动作不再执行。
        """
        self._cancel_click()
        self._pending_click = QTimer(self.content)
        self._pending_click.setSingleShot(True)
        self._pending_click.timeout.connect(action)
        self._pending_click.start(QApplication.doubleClickInterval())

    def _cancel_click(self) -> None:
        pending = getattr(self, "_pending_click", None)
        if pending is not None:
            pending.stop()
            pending.deleteLater()
            self._pending_click = None

    def _on_cell_clicked(self, index) -> None:
        """单击：**哪一格就开哪个**（名字格有一个就开一个，两个都有让你选）。"""
        if index is None or not index.isValid():
            return
        column = index.column()
        row = self._row_at(index)
        if not row:
            return
        if column == COLUMN_INDEX["wave"]:
            self._open_case_wave(row)
        elif column == COLUMN_INDEX["cov"]:
            self._open_case_coverage(row)
        elif column == COLUMN_INDEX["name"]:
            pos = self.table.visualRect(index).center()
            self._defer_click(lambda: self._open_case_artifact(row, pos))

    def _open_case_log(self, row: Dict[str, Any]) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        path = self._case_log_path(row)
        if not path:
            self.set_status("这条用例没有可打开的日志（日志列是空的或文件不在了）")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        self.set_status(f"已打开日志：{path}")

    def _reveal_case_dir(self, row: Dict[str, Any]) -> None:
        """在文件管理器里定位到那条用例的目录（日志不在时也能找到别的产物）。"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        path = self._case_log_path(row)
        target = str(Path(path).parent) if path else (
            str(Path(self.run_dir) / "regression_run") if self.run_dir else "")
        if not target or not Path(target).exists():
            self.set_status("找不到这条用例的目录")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))
        self.set_status(f"已打开目录：{target}")

    def _on_row_activated(self, index) -> None:
        """双击 → 仿真日志（原行为）。**先取消挂起的那次单击** —— 见 `_defer_click`。"""
        self._cancel_click()
        self._open_case_log(self._row_at(index))

    def _on_row_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        row = self._row_at(self.table.indexAt(pos))
        if not row:
            return
        menu = QMenu(self.table)
        menu.addAction("打开仿真日志", lambda: self._open_case_log(row))
        menu.addAction("打开用例目录", lambda: self._reveal_case_dir(row))
        menu.addAction("打开总覆盖率报告", self.open_total_coverage)
        menu.addAction("在 Visualizer 看总覆盖率", self.open_total_coverage_visualizer)
        wave = self._case_wave_path(row)
        cov = self._case_cov_path(row)
        # 没产物时**也挂这一条**（置灰说明原因）—— 菜单里凭空少一项，人会怀疑
        # 是这页的 bug；挂上并说明"这轮没开这门业务"，指向的是该动的那个开关。
        wave_action = menu.addAction("打开波形", lambda: self._open_case_wave(row))
        wave_action.setEnabled(bool(wave))
        if not wave:
            wave_action.setToolTip("这轮回归的仿真业务里没有开 `wave`")
        cov_action = menu.addAction("打开覆盖率报告",
                                    lambda: self._open_case_coverage(row))
        cov_action.setEnabled(bool(cov))
        cov_vis_action = menu.addAction("在 Visualizer 看覆盖率",
                                        lambda: self._open_case_coverage_visualizer(row))
        cov_vis_action.setEnabled(bool(cov))
        if not cov:
            cov_action.setToolTip("这轮回归的仿真业务里没有开 `cov`")
            cov_vis_action.setToolTip("这轮回归的仿真业务里没有开 `cov`")
        menu.addSeparator()
        path = self._case_log_path(row)
        if path:
            menu.addAction("复制日志路径", lambda: self._copy(path))
        if wave:
            menu.addAction("复制波形路径", lambda: self._copy(wave))
        if cov:
            menu.addAction("复制覆盖率库路径", lambda: self._copy(cov))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self.set_status(f"已复制：{text[:80]}")

    def create_actions(self) -> List[QAction]:
        action = QAction(f"刷新{self.title}", self.content)
        action.setShortcut("Ctrl+Shift+R")
        action.triggered.connect(lambda: self.load(self.run_id))
        return [action]

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def on_activated(self) -> None:
        if self.run_id:
            self.load(self.run_id)

    def on_refresh(self, payload: Any = None) -> None:
        # 订阅 `run.selected`：payload 就是被选中的 run id
        run_id = str(payload or "")
        if run_id and run_id != self.run_id:
            self.load(run_id)

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def load(self, run_id: str) -> None:
        """按 run id 取回归状态。run id → 运行目录走 `pipeline.detail`（与其它页面一致）。"""
        if not run_id:
            self._clear()
            self.show_info("先在左边「运行历史」里选一次运行。")
            return
        detail = self.run_tool("pipeline.detail", quiet=True, run_id=run_id)
        if not isinstance(detail, dict) or self.report_payload_error(detail):
            return
        run_dir = str(detail.get("dir", "") or "")
        self.run_dir = run_dir          # 一键定位要用（拼相对日志路径）
        payload = self.run_tool("flow.regression_status", quiet=True, run_dir=run_dir)
        if not isinstance(payload, dict):
            return
        if self.report_payload_error(payload):
            self._clear()
            return
        self.run_id = run_id
        self._fill(payload)

    def _fill(self, payload: Dict[str, Any]) -> None:
        # `self._rows` 存**原始行**（路径是完整的，点开要用）；表格里显示的是
        # 短路径的副本。两份的顺序一一对应，`_row_at` 靠这个对应关系取数据。
        self._rows = list(payload.get("rows") or [])
        self.model.set_rows([self._display_row(r) for r in self._rows])
        self.model.apply_column_widths(self.table)

        stats = payload.get("stats") or {}
        if not self._rows:
            self.summary_label.setText("没有回归用例")
        else:
            # 波形/覆盖率条数进摘要：不然"这一列为什么是空的"得靠人去翻工具栏才知道
            waves = sum(1 for r in self._rows if r.get("wave"))
            covs = sum(1 for r in self._rows if r.get("cov"))
            self.summary_label.setText(
                f"共 {stats.get('total', 0)} 个用例　"
                f"通过 {stats.get('pass', 0)}　"
                f"失败 {stats.get('fail', 0)}　"
                f"无结论 {stats.get('unknown', 0)}　"
                f"波形 {waves}　覆盖率 {covs}")

        # 数据来源的情况必须显示出来 —— 「这页的结论凭什么可信」是它的全部价值
        sources = payload.get("sources") or {}
        bits: List[str] = []
        derived = int(sources.get("derived_rows") or 0)
        if derived:
            bits.append(f"{derived} 条结论是从日志推断的（非框架判完的记录）")
        if not sources.get("report_json"):
            bits.append("无 report.json")
        if not sources.get("status_env"):
            bits.append("无 status.env")
        bits.extend(str(n) for n in (payload.get("notes") or []))
        self.notes_label.setText("　·　".join(dict.fromkeys(bits)))

    def _display_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """喂给表格的那一份：路径只留用例目录往后一段（完整路径撑满列、尾部反被截）。

        没有产物时**不留空**：空列会被读成"路径没加上 / 这页坏了"，而真实原因是
        这轮没开那门仿真业务。填一句指路的话（与「回归波形/覆盖率」两页共用同一句
        `cov_actions.missing_artifact_note`）—— 列窄会被截断，**悬停看全句**
        （`RowsModel` 的 tooltip 就是完整文本）。
        """
        base = str(row.get("work_dir", "") or "")
        wave = self._short_path(row.get("wave", ""), base)
        cov = self._short_path(row.get("cov", ""), base)
        return {**row,
                "wave": wave or cov_actions.missing_artifact_note("波形", "波形库"),
                "cov": cov or cov_actions.missing_artifact_note("覆盖率", "覆盖率库")}

    def _clear(self) -> None:
        self._rows = []
        self.model.set_rows([])
        if self.summary_label:
            self.summary_label.setText("")
        if self.notes_label:
            self.notes_label.setText("")
