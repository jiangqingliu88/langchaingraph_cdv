"""Case 建模模块 —— case 属性完备性建模的全部界面能力。

它做四件事：开文件、**从编辑器文本分析**、保存、把结果发给 11 个页面。

关于「真相在哪」：**编辑器的文本是唯一真相**，其它页面都是它的只读视图。所以
  · 分析走 `analyze_text(编辑器文本)` 而不是重读文件 —— 未保存的改动也能立刻看到效果
  · 保存写的就是编辑器的文本，原样落盘，注释格式都保留
  · 文本构不出模型时，保留上一次成功的结果并挂红条说明，而不是清空表格
（不这么做的话，你改到一半就会看到一片空白，还以为是工具坏了。）

这四件事原来长在 `CaseModelApp(QMainWindow)` 上；工作台第二轮把它剥出来做成
模块 —— 窗口该管的事（菜单、Dock、状态栏、主题）交给平台，这里只剩建模。

启动:
    vagent gui run -m verify.casemodel
    python -m src.workbench -m verify.casemodel
    vagent case-model gui [模型.yaml]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QFileDialog, QLineEdit, QMessageBox, QTabWidget,
                               QVBoxLayout, QWidget)

from src.tools.casemodel_tools.analysis import AnalysisResult, analyze_text
from src.tools.casemodel_tools.analysis.schema_check import SchemaChecker
from src.tools.casemodel_tools.domain import CaseModelError
from src.tools.casemodel_tools.domain.errors import CaseListError
# 跨层引用一律绝对路径：本模块比 `modules/` 深两层，`..base` 会解析成
# `modules.verify.base`（不存在），而报错信息只说「模块 import 不了」，
# 从堆栈里看不出是少点了一个点。
from src.workbench.modules.base import ModuleBase
from src.workbench.ui.theme import icons

from .pages import EDITOR_TITLE, PAGES

#: 状态栏里那行摘要的格式 —— 与 CLI 的措辞保持一致
_STATUS = ("{where}{dirty} —— 组织树 {leaves} 叶子，专题 {themes} 个，"
           "生成 {cases} 个 case{cases_tail}，完备性 {score}/100，"
           "错误 {errors} / 警告 {warnings} / 提示 {infos}")


class CasemodelModule(ModuleBase):
    """一个 center 模块，内部再套一层标签页。"""

    HINT = "编辑模型原文，其余页面是它的只读视图。"

    # ════════════════════════════════════════════════════════
    # 构造
    # ════════════════════════════════════════════════════════

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.result: Optional[AnalysisResult] = None
        self.path: Optional[Path] = None
        self.cases_path: Optional[Path] = None      # 外部真实 case 列表
        self.schema_issues: List = []
        self.checker = SchemaChecker()
        #: 当前跟着哪次运行 —— `run.selected` 的订阅用（见 `on_refresh`）
        self._run_id: str = ""

    # ════════════════════════════════════════════════════════
    # 跟着选中的运行走
    # ════════════════════════════════════════════════════════

    def on_refresh(self, payload: Any = None) -> None:
        """`run.selected` 的订阅者：切运行就切到这个运行自己的 case 模型。

        **为什么要这一步**：页面的默认输入是清单里写死的那份
        `config/casemodel/examples/*.yaml` —— 那是**示例**，属于另一个设计
        （cpu_pipeline）。而闭环每次运行都会在自己目录里产出一份 case 模型
        （`<运行目录>/inputs/casemodel.yaml`，由 spec 合成或人工放置），那才是
        "这次 apb_uart 的 case 模型"。

        两边接不上的表现就是：界面对着 CPU 流水的示例，而本次运行那份躺在运行
        目录里没人看 —— 用户会直接问"gui 里 case 建模不是 apb_uart 的呢"。
        """
        run_id = str(payload or "")
        if not run_id or run_id == self._run_id:
            return
        detail = self.run_tool("pipeline.detail", quiet=True, run_id=run_id)
        # 键名是 `dir`（`flow_tools/api.py` 那边定义的），不是 `run_dir` ——
        # 取空了就会静默什么都不做（第一次就是这么写的，测试才看出来）
        run_dir = ""
        if isinstance(detail, dict):
            run_dir = str(detail.get("dir") or detail.get("run_dir") or "")
        if not run_dir:
            return
        target = Path(run_dir) / "inputs" / "casemodel.yaml"
        if not target.exists():
            # 这次运行没产过（老的运行 / 没走 spec 桥）—— 如实说一句，别装作切了
            self.set_status(f"运行 {run_id} 里没有 case 模型 —— 仍显示当前这份")
            return
        self._run_id = run_id
        self.load(str(target))
        self.set_status(f"已切到本次运行的 case 模型：{target}")

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 「修改理由」—— 随这次编辑进证据链（见 `ModuleBase.record_human_edit`）。
        # 在这里建、由编辑页摆到工具条上：**一个 owner（模块）**，页面只负责放。
        # 页面在下面那个循环里构造，所以必须建在循环之前。
        self.reason_edit = QLineEdit(root)
        self.reason_edit.setPlaceholderText("为什么改（会记进证据链）")
        self.reason_edit.setMaximumWidth(260)

        # 内层标签页：这 11 页是同一份文本的视图，不该被摊成平台的中央标签页
        # （摊开就能把「概览」脱离「编辑 YAML」，而点诊断跳源码靠的正是这个关系）
        self.tabs = QTabWidget(root)
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)

        self.pages = {}
        for page_cls in PAGES:
            page = page_cls(self)
            self.tabs.addTab(page, page_cls.TITLE)
            self.pages[page_cls.TITLE] = page
        self.editor = self.pages[EDITOR_TITLE]

        # 诊断双击 → 跳到 YAML 对应行（Verdi 式的「点错误跳源码」）
        for page in self.pages.values():
            panel = getattr(page, "panel", None)
            if panel is not None and hasattr(panel, "issueActivated"):
                panel.issueActivated.connect(self.editor.goto_issue)
        return root

    # ════════════════════════════════════════════════════════
    # 平台接口
    # ════════════════════════════════════════════════════════

    #: 动作 → 图标名。模块的图标跟着平台主题走，`on_theme_changed` 靠这张表重挂
    #: （图标是按主题色渲染成位图的，`setIcon` 之后就固定了）。
    ACTION_ICONS = {
        "act_open": "folder-open",
        "act_save": "save",
        "act_save_as": "save",
        "act_reanalyze": "analyze",
        "act_load_cases": "folder",
        "act_clear_cases": "clear",
        "act_export": "export",
    }

    def create_actions(self) -> List[QAction]:
        """模块自有动作 —— 进菜单与平台工具栏。

        快捷键绑在这里而不是页面的按钮上：QAction 的快捷键无论焦点在哪个控件
        都生效，按钮不行。平台把 Ctrl+O / Ctrl+S / Ctrl+R 留给了业务模块
        （清单那条链用的是 Ctrl+Shift+O / F5）。
        """
        def act(name, text, slot, shortcut=None, tip=""):
            action = QAction(text, self.content)
            if shortcut:
                action.setShortcut(shortcut)
            if tip:
                action.setStatusTip(tip)
            action.triggered.connect(slot)
            setattr(self, name, action)
            return action

        act("act_open", "打开模型…", self.on_open,
            QKeySequence.StandardKey.Open, "打开一份 case 模型 YAML")
        act("act_save", "保存模型", self.save_model,
            QKeySequence.StandardKey.Save, "保存当前模型（保存前跑 schema 校验）")
        act("act_save_as", "模型另存为…", self.save_model_as,
            QKeySequence.StandardKey.SaveAs)
        act("act_reanalyze", "重新分析", self.reanalyze, "Ctrl+R",
            "用编辑器里的文本重跑分析（不必先保存）")
        act("act_load_cases", "载入真实 case…", self.on_load_cases, None,
            "载入真实 case 列表做反向核对")
        act("act_clear_cases", "清除真实 case", self.on_clear_cases)
        act("act_export", "导出完备性报告…", self.on_export)

        self._apply_icons()
        return [self.act_open, self.act_save, self.act_save_as, self.act_reanalyze,
                self.act_load_cases, self.act_clear_cases, self.act_export]

    def _apply_icons(self) -> None:
        for attr, icon_name in self.ACTION_ICONS.items():
            action = getattr(self, attr, None)
            if action is not None:
                action.setIcon(icons.icon(icon_name))

    def on_theme_changed(self) -> None:
        self._apply_icons()

    def on_activated(self) -> None:
        self.editor.focus_editor()

    def on_input_changed(self, path) -> None:
        """清单的 `input` 或 `--input` 指过来时：载入这份模型。"""
        target = Path(path)
        if target.is_dir():
            # 指到目录就找它下面的模型 —— 免得用户还得自己写文件名
            candidates = sorted(target.glob("*.yaml")) + sorted(target.glob("*.yml"))
            if not candidates:
                self.show_warning(f"{target} 下没有 .yaml 模型文件。")
                return
            target = candidates[0]
        self.load(str(target))

    def can_close(self) -> bool:
        """有未保存的改动就拦一道 —— 关窗口/换清单之前问一句。"""
        if not self.editor.dirty:
            return True
        return self._confirm_discard()

    def mark_clean(self) -> None:
        self.editor.mark_clean()
        self._sync_title()

    # ════════════════════════════════════════════════════════
    # 打开
    # ════════════════════════════════════════════════════════

    def on_open(self) -> None:
        if not self._confirm_discard():
            return
        path, _filter = QFileDialog.getOpenFileName(
            self.content, "选择 case 模型 YAML", "",
            "YAML 文件 (*.yaml *.yml);;所有文件 (*)")
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        """读文件 → 编辑器 → 分析。"""
        target = Path(path)
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            self.result = None
            QMessageBox.critical(self.content, "打开失败", str(exc))
            self.set_status(f"打开失败：{exc}")
            return

        self.path = target
        self.editor.set_text(text)
        self.editor.mark_clean()
        self._sync_title()
        self.reanalyze()

    # ════════════════════════════════════════════════════════
    # 分析
    # ════════════════════════════════════════════════════════

    def reanalyze(self) -> None:
        """从**编辑器当前文本**重跑分析。

        不重读文件 —— 这样未保存的改动也能立刻看到效果，这正是「改一行、
        马上知道它坏了哪条规则」的工作方式。
        """
        text = self.editor.get_text()
        name = self.path.name if self.path else "<编辑器>"
        self.schema_issues = self.checker.check_text(text, name=name)
        # 立刻同步到编辑器那行 —— 下面有几条提前 return 的路径，不在这里同步的话，
        # schema 结果会停在上一轮，看着像「校验通过」实则没跑
        self.editor.refresh_status()
        self._sync_title()

        if not text.strip():
            self.result = None
            self._clear_pages()
            self.show_warning("编辑器是空的 —— 没有可分析的模型。")
            self._update_status()
            return

        try:
            self.result = analyze_text(
                text, source=str(self.path or "<编辑器>"),
                cases=str(self.cases_path) if self.cases_path else None)
        except CaseListError as exc:
            self.result = None
            self._clear_pages()
            self.show_error(f"真实 case 列表读不进来：{exc}")
            self._update_status()
            return
        except CaseModelError as exc:
            # 保留上一次成功的结果 —— 改到一半看到一片空白会让人以为工具坏了
            self.show_error(
                f"当前文本构不出模型：{exc}\n"
                f"（下面是上一次成功分析的结果，改好之后按 Ctrl+R 重新分析）")
            self._update_status()
            return
        except Exception as exc:                      # noqa: BLE001
            self.show_error(f"分析失败：{exc}\n（下面是上一次成功分析的结果）")
            self._update_status()
            return

        self.clear_banner()
        self.refresh()
        self._update_status()

    def refresh(self) -> None:
        if self.result is None:
            return
        for page in self.pages.values():
            page.refresh(self.result)

    def _clear_pages(self) -> None:
        """没有结果时清空各页 —— 留着上次的行会误导。

        编辑器页的 `clear()` 是空实现（`Page.clear` 的默认行为），所以用户
        正在编的文本不会被清掉。
        """
        for page in self.pages.values():
            page.clear()

    def _update_status(self) -> None:
        if self.result is None:
            self.set_status("未分析出结果 —— 看上面的提示条。")
            return
        s = self.result.summary()
        counts = self.result.counts()
        where = self.path.name if self.path else "（未命名）"
        dirty = "　● 未保存" if self.editor.dirty else ""
        cases_tail = (f"（截断丢弃 {s['dropped']}）" if s["truncated"] else "")
        self.set_status(_STATUS.format(
            where=where, dirty=dirty, leaves=s["org_leaf_count"],
            themes=s["theme_count"], cases=s["case_count"], cases_tail=cases_tail,
            score=s["score"], errors=s["error_count"],
            warnings=s["warning_count"], infos=s["info_count"]))

    def _sync_title(self) -> None:
        """把「未保存」标到标签页标题上。

        比原来把 ● 挂在窗口标题上更合适：窗口标题归平台（它是整个工作台的），
        而脏状态是**这个模块**的属性 —— 用户同时开着好几个模块时，得能看出是
        哪一个没存。
        """
        name = self.path.name if self.path else "（未命名）"
        mark = " ●" if self.editor.dirty else ""
        self.set_tab_suffix(f" — {name}{mark}")

    def notify_editor_changed(self) -> None:
        """编辑器内容变了 —— 标题的「未保存」标记与状态栏要跟上。

        不重新分析（太贵），只更新标记：分析的时机由用户决定（Ctrl+R），
        这样改到一半不会一直闪。
        """
        self._sync_title()
        self._update_status()

    # ════════════════════════════════════════════════════════
    # 保存
    # ════════════════════════════════════════════════════════

    def save_model(self) -> bool:
        if self.path is None:
            return self.save_model_as()
        text = self.editor.get_text()
        issues = self.checker.check_text(text, name=self.path.name)
        errors = [i for i in issues if i.is_error]
        if errors:
            detail = "\n".join(f"· {i.message}" for i in errors[:8])
            if len(errors) > 8:
                detail += f"\n…共 {len(errors)} 条"
            answer = QMessageBox.question(
                self.content, f"schema 有 {len(errors)} 处错误",
                f"保存前校验没通过：\n\n{detail}\n\n仍然保存吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self.set_status("保存已取消 —— 先按提示修好 schema 错误。")
                return False
        try:
            self.path.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self.content, "保存失败", str(exc))
            self.set_status(f"保存失败：{exc}")
            return False

        self.editor.mark_clean()
        self._sync_title()
        # 写盘之后立刻记账 —— 这一步漏了，这次编辑就等于没发生过（见基类的说明）
        recorded = self.record_human_edit(self.path, self.reason_edit.text())
        self.reason_edit.clear()          # 理由跟着这次保存走，不留给下一次
        self.reanalyze()                 # 保存即生效：重新分析并刷新全部页面
        tail = f"schema {len(errors)} 处错误仍在。" if errors else ""
        if recorded:
            tail += f"　已记账 #{recorded['seq']}（{recorded['author']}）"
        self.set_status(f"已保存 {self.path}　—— 并已重新分析。{tail}")
        return True

    def save_model_as(self) -> bool:
        path, _filter = QFileDialog.getSaveFileName(
            self.content, "保存 case 模型 YAML",
            self.path.name if self.path else "case_model.yaml",
            "YAML 文件 (*.yaml *.yml);;所有文件 (*)")
        if not path:
            return False
        self.path = Path(path)
        self._sync_title()
        self.editor.mark_clean()         # 先清脏，避免 save_model 里再问一次
        return self.save_model()

    def _confirm_discard(self) -> bool:
        """有未保存改动时问一句 —— 返回 True 表示可以继续。"""
        if not self.editor.dirty:
            return True
        box = QMessageBox(self.content)
        box.setWindowTitle("有未保存的改动")
        box.setText("当前模型有未保存的改动。\n\n要保存吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Save
                               | QMessageBox.StandardButton.Discard
                               | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        answer = box.exec()
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_model()
        return True                      # 不保存，继续

    # ════════════════════════════════════════════════════════
    # 外部 case / 导出
    # ════════════════════════════════════════════════════════

    def on_load_cases(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self.content, "选择真实 case 列表", "",
            "case 列表 (*.yaml *.yml *.json *.csv);;所有文件 (*)")
        if not path:
            return
        self.cases_path = Path(path)
        self.reanalyze()

    def on_clear_cases(self) -> None:
        self.cases_path = None
        self.reanalyze()

    def on_export(self) -> None:
        if self.result is None:
            QMessageBox.information(self.content, "导出报告", "还没有可导出的分析结果。")
            return
        default = f"{self.path.stem if self.path else 'case_model'}_report.txt"
        path, _filter = QFileDialog.getSaveFileName(
            self.content, "导出完备性报告", default,
            "文本报告 (*.txt);;所有文件 (*)")
        if not path:
            return
        try:
            Path(path).write_text(self.render_report(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self.content, "导出失败", str(exc))
            return
        self.set_status(f"报告已导出：{path}")

    def render_report(self) -> str:
        """导出文本报告 —— 复用 CLI 的渲染器，两处输出保持一致。"""
        from src.tools.casemodel_tools.text import report as text_report

        parts = [text_report(self.result)]
        if not self.schema_issues:
            parts.append("\n【Schema 校验】\n  通过")
        else:
            parts.append("\n【Schema 校验】\n"
                         + "\n".join(f"  {i}" for i in self.schema_issues))
        return "\n".join(parts)


__all__ = ["CasemodelModule"]
