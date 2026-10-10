"""**回归波形 / 回归覆盖率** —— 逐条用例确认产物的两页。

## 为什么要单独两页（而不是在「回归状态」里看）

「回归状态」回答的是**判定**问题：哪条挂了、挂的是什么错。而"人工校对"是另一
个动作：**一条一条对过去**，把每条用例的波形/覆盖率打开看一眼。两者的列、点击
的落点、缺产物时该说的话都不一样 —— 硬塞进一张表，两条路都会变难走。

所以：状态页保留（判定 + 一个「打开总覆盖率」的按钮），这里两条专门的路：

    回归波形页   一个用例一行，点一行 → 开那条用例的 **WLF**
    回归覆盖率页 一个用例一行，点一行 → 开那条用例的 **覆盖率报告**（HTML）
                 页头另给**总覆盖率**（含"打开总覆盖率报告"按钮）

## 页面形状

一个用例一行，四列：用例 / 状态 / 文件 / 大小 / 时间。**缺产物的也列出来** ——
"这条为什么没有波形"本身就是校对要找的东西（挂死被看门狗掐掉的那条，往往就是
一分钱覆盖率都没采到的那条）。缺的行、缺的那格都标出来，不隐藏。

两页只差三件事：看数据层的哪个字段、点开是什么、页头多说哪几句 —— 所以差异做成
类属性 + 一个 `_open` 钩子，取数/路径绝对化/大小格式化/菜单这些一处实现。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QPushButton,
                               QVBoxLayout, QWidget)

from ...ui import theme
from ...ui.helpers import tables as table_helpers
from ...ui.models import CENTER, LEFT, RowsModel
from ..base import ModuleBase
from . import cov_actions

#: (键, 表头, 列宽, 对齐)。`artifact` 那一格放**绝对路径**（见 `_display_row`）——
#: 列给得宽，是因为绝对路径本来就是长的：截短了就看不出是哪个 build/哪条用例。
COLUMNS = (
    ("name", "用例", 240, LEFT),
    ("detail", "状态", 110, CENTER),
    ("artifact", "文件（绝对路径）", 560, LEFT),
    ("size", "大小", 90, CENTER),
    ("time", "时间", 150, CENTER),
    ("source", "来源", 90, CENTER),
)

#: 列名 → 列号（和「回归状态」同一套口径：表改了列序，这里跟着变，不写魔数）
COLUMN_OF = {key: i for i, (key, _t, _w, _a) in enumerate(COLUMNS)}

def _abs_artifact_path(raw: str, run_dir: str = "", work_dir: str = "") -> str:
    """产物路径 → **绝对路径**（显示与打开用同一个值）。取不到就给空串。

    ## 为什么必须绝对化（而不是显示成好看的一段）

    回归框架落盘的 `wave_path` / 覆盖率库路径是**相对路径**（相对运行目录），
    而打开走的是 `QDesktopServices.openUrl(QUrl.fromLocalFile(path))` ——
    给它一个相对路径，**它什么都不做，也不报错**：点了没反应，人只会以为这页坏了。
    所以相对路径必须在**交给桌面服务之前**落一次绝对化。

    显示也用同一个值：人看到的就是点开的那一个 —— 显示相对、打开绝对，对不上账时
    根本没法对。

    查找顺序：原样（相对 CWD，工具的落盘口径就是它）→ `run_dir/raw` →
    `work_dir/raw`；都碰不到文件时，仍返回一个**绝对**路径（按 CWD 解析）——
    "这条本该在哪"本身就是要看的信息，给空串等于把线索也扔了。
    """
    raw = str(raw or "").strip()
    if not raw:
        return ""
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    candidates = [p]
    for base in (run_dir, work_dir):
        if base:
            candidates.append(Path(str(base)) / raw)
    for cand in candidates:
        if cand.exists():
            return str(cand.resolve())
    return str(candidates[0].resolve())


def _fmt_size(kb) -> str:
    """KB → 给人看的单位。**没有就给空**（不是 "0 KB" —— 0 和没有是两件事）。"""
    if kb is None:
        return ""
    try:
        value = float(kb)
    except (TypeError, ValueError):
        return ""
    if value >= 1024:
        return f"{value / 1024:.1f} MB"
    return f"{value:.1f} KB"


class _ArtifactPage(ModuleBase):
    """「一个用例一行 + 一份产物」两页的共同部分（见模块文档）。"""

    ARTIFACT_KEY = ""          #: 数据层里那个键（wave / cov）
    ARTIFACT_NOUN = ""         #: 中文名，用在页头与提示里
    OPEN_LABEL = ""            #: 右键菜单里那个动作的文案
    HINT = ""

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id = ""
        self.run_dir = ""
        self._rows: List[Dict[str, Any]] = []

    # ── 搭界面 ──

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
        for button in self.header_buttons(root):
            head.addWidget(button)
        layout.addLayout(head)

        self.notes_label = QLabel("", root)
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.notes_label)

        self.model = RowsModel(COLUMNS, root)
        self.table = table_helpers.configure_table(root, self.model)
        self.table.clicked.connect(self._on_cell_clicked)
        self.table.doubleClicked.connect(self._on_activated)
        self.table.customContextMenuRequested.connect(self._on_menu)
        layout.addWidget(self.table, 1)
        return root

    def header_buttons(self, parent) -> List[QWidget]:
        """页头按钮 —— 默认没有，子类按需加（如"打开总覆盖率报告"）。"""
        return []

    def create_actions(self) -> List[QAction]:
        action = QAction(f"刷新{self.title}", self.content)
        action.triggered.connect(lambda: self.load(self.run_id))
        return [action]

    # ── 平台钩子 ──

    def on_activated(self) -> None:
        if self.run_id:
            self.load(self.run_id)

    def on_refresh(self, payload: Any = None) -> None:
        run_id = str(payload or "")
        if run_id and run_id != self.run_id:
            self.load(run_id)

    # ── 数据 ──

    def load(self, run_id: str) -> None:
        if not run_id:
            self._clear()
            self.show_info("先在左边「运行历史」里选一次运行。")
            return
        detail = self.run_tool("pipeline.detail", quiet=True, run_id=run_id)
        if not isinstance(detail, dict) or self.report_payload_error(detail):
            return
        self.run_dir = str(detail.get("dir", "") or "")
        payload = self.run_tool("flow.regression_status", quiet=True,
                                run_dir=self.run_dir)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            self._clear()
            return
        self.run_id = run_id
        self._fill(payload)

    def _fill(self, payload: Dict[str, Any]) -> None:
        self._rows = list(payload.get("rows") or [])
        rows = []
        colors: Dict[tuple, QColor] = {}
        for index, row in enumerate(self._rows):
            # 「文件」那一格标灰：它不是"这里没内容"，是"少了东西"。判据是
            # **文件真在不在**（不是"数据层有没有给路径"）—— 路径给了但文件没落盘,
            # 同样是缺。颜色取自主题的弱化色，换主题跟着变（别写死一个灰）。
            if not self._artifact_path(row):
                colors[(index, COLUMN_OF["artifact"])] = QColor(theme.current().muted)
            rows.append(self._display_row(row))
        self.model.set_rows(rows, cell_colors=colors)
        self.model.apply_column_widths(self.table)

        total = len(self._rows)
        have = sum(1 for r in self._rows if r.get(self.ARTIFACT_KEY))
        # 摘要正文存一份：子类的页头要往后面追加东西（总覆盖率那几个数），
        # 追加必须从**正文**重算，否则每刷一次就多叠一段（切来切去会调很多次）。
        self._base_summary = (
            f"{total} 条用例，{have} 条有{self.ARTIFACT_NOUN}"
            + (f"，**{total - have} 条没有**" if total - have else ""))
        self.summary_label.setText(self._base_summary)
        self.notes_label.setText(self._notes(payload))
        # 子类追加东西必须从**正文**重算（同 `_base_summary` 的道理）——
        # 在已设置的文本上再加，刷几次就叠几段。
        self._base_notes = self.notes_label.text()

    def _notes(self, payload: Dict[str, Any]) -> str:
        bits: List[str] = []
        total = len(self._rows)
        have = sum(1 for r in self._rows if r.get(self.ARTIFACT_KEY))
        if self._rows and not have:
            bits.append(f"一条都没有 —— 这轮回归的仿真业务里没开"
                        f"「{self._artifact_mode}」（工具栏「仿真业务」下拉可切）")
        elif 0 < have < total:
            bits.append(f"缺的那些大多是**没跑到底**的用例（挂死被看门狗掐掉、"
                        f"或编译不过）—— 少了产物本身就是要看的东西")
        bits.extend(str(n) for n in (payload.get("notes") or []))
        return "　·　".join(dict.fromkeys(bits))

    @property
    def _artifact_mode(self) -> str:
        return {"wave": "波形", "cov": "覆盖率"}.get(self.ARTIFACT_KEY,
                                                    self.ARTIFACT_NOUN)

    def _display_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        path = self._abs_path(row)
        if not path:
            # 没有产物时**不留空那一格** —— 文案与「回归状态」页共用同一句
            # （`cov_actions.missing_artifact_note`，一处实现不会漂）。
            path = cov_actions.missing_artifact_note(self._artifact_mode,
                                                      self.ARTIFACT_NOUN)
        return {**row,
                # 文件那一格显示**绝对路径** —— 与点开时用的是同一个字符串；
                # 没有产物时是上面那句解释（不是空串）。
                "artifact": path,
                "size": _fmt_size(row.get(f"{self.ARTIFACT_KEY}_kb")),
                "time": row.get(f"{self.ARTIFACT_KEY}_time", "") or "",
                "source": row.get(f"{self.ARTIFACT_KEY}_source", "") or "",
                "detail": row.get("detail", "") or ""}

    # ── 点开 ──

    def _row_at(self, index: QModelIndex) -> Dict[str, Any]:
        """视图坐标 → 原始行（**过一遍排序代理**，否则排序后会开错别人的产物）。"""
        if index is None or not index.isValid():
            return {}
        model = index.model()
        if model is not self.model and hasattr(model, "mapToSource"):
            index = model.mapToSource(index)
        rows = getattr(self, "_rows", None) or []
        return rows[index.row()] if 0 <= index.row() < len(rows) else {}

    def _abs_path(self, row: Dict[str, Any]) -> str:
        """那行产物的**绝对路径**（显示与打开共用；没有路径才给空串）。"""
        return _abs_artifact_path(str(row.get(self.ARTIFACT_KEY, "") or ""),
                                  run_dir=self.run_dir,
                                  work_dir=str(row.get("work_dir", "") or ""))

    def _artifact_path(self, row: Dict[str, Any]) -> str:
        """能打开的那份绝对路径 —— **不存在的给空串**（调用方据此说"没有"）。

        与 `_abs_path` 分开：那一份是"它本该在哪"（即便还没生成也要显示给人看），
        这一份是"现在真的能打开"（不存在的路径喂给桌面服务只会静默失败）。
        """
        path = self._abs_path(row)
        return path if path and Path(path).exists() else ""

    def _on_cell_clicked(self, index: QModelIndex) -> None:
        """点哪一行都开那一行 —— 这一页只有一件事可做。"""
        self._open(self._row_at(index))

    def _on_activated(self, index: QModelIndex) -> None:
        self._open(self._row_at(index))

    def _extra_menu_actions(self, menu, row: Dict[str, Any], path: str) -> None:
        """子类可往右键菜单里再加动作（默认不加）。"""
        return None

    def _on_menu(self, pos) -> None:
        row = self._row_at(self.table.indexAt(pos))
        if not row:
            return
        path = self._artifact_path(row)
        menu = QMenu(self.table)
        action = menu.addAction(self.OPEN_LABEL, lambda: self._open(row))
        # 没产物也**照挂**（置灰说明原因）—— 菜单里凭空少一项，人会怀疑是这页坏了
        action.setEnabled(bool(path))
        if not path:
            action.setToolTip(f"这轮回归的仿真业务里没有开 `{self.ARTIFACT_KEY}`")
        self._extra_menu_actions(menu, row, path)
        menu.addSeparator()
        reveal = menu.addAction("在文件管理器里显示", lambda: self._reveal(row))
        reveal.setEnabled(bool(path))
        copy = menu.addAction("复制路径", lambda: self._copy(row, path))
        copy.setEnabled(bool(path))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _reveal(self, row: Dict[str, Any]) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        path = self._artifact_path(row)
        if not path:
            self.set_status(f"这条用例没有{self.ARTIFACT_NOUN}")
            return
        target = str(Path(path).parent if Path(path).is_file() else path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))
        self.set_status(f"已打开目录：{target}")

    def _copy(self, row: Dict[str, Any], path: str = "") -> None:
        from PySide6.QtWidgets import QApplication

        path = path or self._artifact_path(row)
        if not path:
            self.set_status(f"这条用例没有{self.ARTIFACT_NOUN}")
            return
        QApplication.clipboard().setText(path)
        self.set_status(f"已复制：{path[:80]}")

    def _clear(self) -> None:
        self._rows = []
        self.model.set_rows([])
        if getattr(self, "summary_label", None):
            self.summary_label.setText("")
        if getattr(self, "notes_label", None):
            self.notes_label.setText("")


class RegressionWaveModule(_ArtifactPage):
    """回归波形 —— 一个用例一行，点一行开那条用例的波形。"""

    ARTIFACT_KEY = "wave"
    ARTIFACT_NOUN = "波形"
    OPEN_LABEL = "打开波形"
    HINT = ("一条用例一行。**点一行就直接用 Questa Visualizer 打开那条用例的波形**"
            "（波形业务产的 `qwave.db`，走 `visualizer -wavefile`；老产物 `.wlf` 则用 "
            "`vsim -view`，按扩展名自动选）。缺波形的也列出来 —— 那多半是没跑到底的"
            "用例，少了波形本身就是要看的东西。总覆盖率的入口在「回归状态」页。")

    def _open(self, row: Dict[str, Any]) -> None:
        if not row:
            return
        cov_actions.open_wave(self, self._artifact_path(row),
                              what=f"{row.get('name', '这条用例')} 的波形")


class RegressionCoverageModule(_ArtifactPage):
    """回归覆盖率 —— 逐条用例的覆盖率库 + 页头的总覆盖率。"""

    ARTIFACT_KEY = "cov"
    ARTIFACT_NOUN = "覆盖率库"
    OPEN_LABEL = "在 Visualizer 看覆盖率"
    HINT = ("一条用例一行。**点一行直接用 Questa Visualizer 打开那条用例的覆盖率库**"
            "（`visualizer -ucdbfile`，可下钻：点 0 覆盖的 bin 跳源码，看得到"
            "「这条用例到底漏了哪个 bin」）。右键另有**「打开覆盖率报告（HTML）」**"
            "—— 库里是二进制，人看不了，报告是拿它现生成/复用的，适合整份结论。"
            "页头两个按钮同理，开的是**整个环境**的总覆盖率。"
            "「每条都挺高、总的就是上不去」和「某一条特别低」是两种完全不同的结论，"
            "两边都要看得见。")

    def header_buttons(self, parent) -> List[QWidget]:
        self.btn_total = QPushButton("打开总覆盖率报告", parent)
        self.btn_total.setToolTip(
            "整个环境合并后的覆盖率报告。优先打开覆盖率阶段已经生成的那一份"
            "（`sim/coverage/reports/index.html`）；没有再拿合并库现生成。")
        self.btn_total.clicked.connect(self.open_total_coverage)
        self.btn_total_vis = QPushButton("Visualizer 看总覆盖率", parent)
        self.btn_total_vis.setToolTip(
            "把合并覆盖率库（merged.ucdb）交给 Questa Visualizer —— 可下钻，"
            "点 0 覆盖的 bin 跳源码。与 HTML 报告互补：报告看「整份结论」，"
            "这里看「缺口在哪」。")
        self.btn_total_vis.clicked.connect(self.open_total_coverage_visualizer)
        return [self.btn_total, self.btn_total_vis]

    def load(self, run_id: str) -> None:
        super().load(run_id)
        self._refresh_total()

    def _refresh_total(self) -> None:
        """页头把总覆盖率的数字也摆出来 —— 不然还得跳到别的页去对账。"""
        if not getattr(self, "run_dir", ""):
            return
        info = self.run_tool("flow.run_coverage", quiet=True, run_dir=self.run_dir)
        if not isinstance(info, dict) or info.get("error"):
            return
        overall = info.get("overall")
        if overall is None:
            return
        bits = [f"总覆盖率 {overall}%"]
        if info.get("functional") is not None:
            bits.append(f"功能 {info['functional']}%")
        # 从**摘要正文**重算，不在当前文本上追加 —— 见 `_fill` 里 `_base_summary`
        self.summary_label.setText(
            getattr(self, "_base_summary", "") + "　·　" + "　".join(bits))

        # ── 运行级覆盖率产物的**绝对路径** ──
        #
        # 逐条用例的库**可能一个都没有**（那一轮回归没开 `cov` 业务），但整个环境
        # 的合并库 / 报告往往在（覆盖率阶段产出的）。只显示逐条的列时，这页会是
        # 一整片空白 —— 人只会以为"绝对路径没加上"或"这页坏了"，而不是"这轮没开
        # 那门业务"。把运行级那份的绝对路径摆出来，这页就始终有一个**具体、可打开**
        # 的东西；它也是页头那个按钮真正会打开的那一份。
        db = info.get("db") or {}
        report = info.get("report") or {}
        extra = ""
        if db.get("exists"):
            extra = f"运行级覆盖率库：{db.get('path')}"
        elif report.get("exists"):
            extra = f"运行级覆盖率报告：{report.get('path')}"
        notes = getattr(self, "_base_notes", "")
        if extra:
            self.notes_label.setText("　·　".join(x for x in (notes, extra) if x))
        btn = getattr(self, "btn_total", None)
        if btn is not None:
            target = report.get("path") or db.get("path") or ""
            btn.setToolTip(
                "整个环境合并后的覆盖率报告。优先打开覆盖率阶段已经生成的那一份"
                "（`sim/coverage/reports/index.html`）；没有再拿合并库现生成。"
                + (f"\n\n当前目标：{target}" if target else ""))

    def open_total_coverage(self) -> None:
        cov_actions.open_total_coverage(self, self.run_dir)

    def open_total_coverage_visualizer(self) -> None:
        cov_actions.open_total_coverage_visualizer(self, self.run_dir)

    def _extra_menu_actions(self, menu, row: Dict[str, Any], path: str) -> None:
        action = menu.addAction("打开覆盖率报告（HTML）",
                                lambda: self._open_report(row))
        action.setEnabled(bool(path))
        if not path:
            action.setToolTip("这轮回归的仿真业务里没有开 `cov`")

    def _open_report(self, row: Dict[str, Any]) -> None:
        if not row:
            return
        cov_actions.open_case_coverage(self, self._artifact_path(row))

    def _open(self, row: Dict[str, Any]) -> None:
        if not row:
            return
        cov_actions.open_case_coverage_visualizer(self, self._artifact_path(row))
