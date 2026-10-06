"""产物审查台 —— 一次运行的中间产物：看清楚、改对、记上账。

**为什么单独一页。** 产物在此之前只以**原始文件树**的形式存在（`证据 / 产物`
那页）：看得见文件名，看不出哪份有问题、哪份是谁写的、改了会怎样。而卡住运行的
恰恰是这些中间 YAML —— 实测一次，`bench.yaml` 的 schema 不符让整次运行挂在
verify，从运行日志一路挖到生成器才定位到。**有这一页，那是 30 秒的事。**

**审什么、不审什么。**
  · 审：`spec.json`（AI 把规格理解成了什么）、`inputs/yaml/uvm/*.yaml`（UVM 配置）、
    `inputs/yaml/regression.yaml`。这些是"中间产物"——**人该看、也该能改**。
  · 不审：`docs/*.json` 与 `report.json`。那几份是**证据**（机器写下的结论与
    哈希链），改了等于篡改结论，所以不给编辑入口，也不在这里列。

**改完会怎样（界面必须说清楚，不然人会以为改完就生效）。**
  · 会：写回文件、记进**证据链**（带 `run_id` 锚点 —— 这次编辑属于这次运行）。
  · 不会：**不会自动重跑**。改的是那次运行目录里的文件，要让改动生效得重新起一次。

**为什么是文本编辑器而不是表单**（同 case 建模页的理由）：从解析结果反向生成
YAML 是有损的（注释、键顺序都会丢），那等于悄悄改掉人写的东西。这里编辑的是
**原文**，保存原样写回 —— 文本是唯一真相，诊断只是它的视图。
"""
from __future__ import annotations

import re
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QBrush, QColor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSplitter, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from src.workbench.modules.base import ModuleBase
from src.workbench.ui import theme
from src.workbench.ui.editors.yaml import YamlEditor
from src.workbench.ui.widgets.panels import IssuePanel

#: 打字停下来多久重数一次诊断 —— 与人工节点页同一个手感
REVALIDATE_MS = 500

_PATH_SPLIT = re.compile(r"[\.\[\]]+")

#: 产物在树上的状态标记 → 颜色字段。找不到的用弱色，别假装它是好的。
_STATUS_FIELD = {"error": "error", "warning": "warning", "ok": "ok", "missing": "muted"}


class ArtifactsModule(ModuleBase):
    """一次运行的中间产物：清单 + 编辑 + schema 诊断 + 记账。"""

    HINT = ("左边是这次运行的中间产物（按阶段分组，✗=schema 不符、●=改过未保存）。\n"
            "选中一份就在右边编辑，保存会写回文件并**记进证据链**。\n"
            "注意：改完**不会自动重跑** —— 要让改动生效，得重新起一次运行。")

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.run_id: str = ""
        #: 运行目录 —— 由 `pipeline.detail` 给出（与签核判定页同一套反解），
        #: 产物路径一律相对它
        self.run_dir: str = ""
        self.path: Optional[Path] = None
        self.items: List[Dict[str, Any]] = []
        #: 树节点按产物 path 索引 —— 刷新之后要能按路径找回同一个节点
        self._nodes: Dict[str, QTreeWidgetItem] = {}
        self._timer: Optional[QTimer] = None

    # ════════════════════════════════════════════════════════
    # 搭界面
    # ════════════════════════════════════════════════════════

    def build_content(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addLayout(self._build_bar(root))

        splitter = QSplitter(Qt.Orientation.Horizontal, root)
        splitter.addWidget(self._build_tree(root))
        splitter.addWidget(self._build_editor(root))
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([260, 720])
        layout.addWidget(splitter, 1)

        # 打字停下再算诊断 —— 每敲一个字都算会闪
        self._timer = QTimer(root)
        self._timer.setInterval(REVALIDATE_MS)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._revalidate)
        return root

    def _build_bar(self, parent: QWidget) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新", parent)
        self.refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(self.refresh_btn)

        self.summary = QLabel("（还没选中运行）", parent)
        self.summary.setStyleSheet(f"color: {theme.current().muted};")
        bar.addWidget(self.summary, 1)
        return bar

    def _build_tree(self, parent: QWidget) -> QWidget:
        self.tree = QTreeWidget(parent)
        self.tree.setHeaderLabels(["产物", "状态"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 180)
        self.tree.itemSelectionChanged.connect(self._on_selected)
        return self.tree

    def _build_editor(self, parent: QWidget) -> QWidget:
        pane = QWidget(parent)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 这一行是"这份是谁写的、现在什么哈希" —— 审查时最先要知道的两件事
        self.head = QLabel("（从左边选一份产物）", pane)
        self.head.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.head)

        self.editor = YamlEditor(pane)
        self.editor.setReadOnly(True)
        self.editor.setPlaceholderText("从左边选一份产物")
        layout.addWidget(self.editor, 3)

        self.panel = IssuePanel(pane)
        self.panel.issueActivated.connect(self.goto_issue)
        layout.addWidget(self.panel, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("理由：", pane))
        self.reason_edit = QLineEdit(pane)
        # 理由会随这次编辑进证据链 —— 链上"谁在什么时候改了什么"diff 答得了，
        # "为什么改"只有人填得出来。留空不阻断，链里如实写「（未填理由）」。
        self.reason_edit.setPlaceholderText("为什么改（会记进证据链）")
        row.addWidget(self.reason_edit, 1)
        self.save_btn = QPushButton("保存", pane)
        self.save_btn.clicked.connect(self.save_artifact)
        self.save_btn.setEnabled(False)
        row.addWidget(self.save_btn)
        self.reload_btn = QPushButton("重载", pane)
        self.reload_btn.clicked.connect(self.reload)
        self.reload_btn.setEnabled(False)
        row.addWidget(self.reload_btn)
        layout.addLayout(row)

        self.status = QLabel("", pane)
        self.status.setStyleSheet(f"color: {theme.current().muted};")
        layout.addWidget(self.status)

        self.editor.contentChanged.connect(self._on_content_changed)
        return pane

    def create_actions(self) -> List[QAction]:
        save = QAction("保存产物", self.content)
        save.triggered.connect(self.save_artifact)
        reload_action = QAction("重载产物", self.content)
        reload_action.triggered.connect(self.reload)
        refresh_action = QAction("刷新产物清单", self.content)
        refresh_action.triggered.connect(self.refresh)
        return [save, reload_action, refresh_action]

    # ════════════════════════════════════════════════════════
    # 平台钩子
    # ════════════════════════════════════════════════════════

    def on_activated(self) -> None:
        self.refresh()

    def on_refresh(self, payload: Any = None) -> None:
        """`run.selected` 的订阅者 —— 换一次运行就重新列产物。"""
        run_id = str(payload or "")
        if run_id and run_id != self.run_id:
            self.run_id = run_id
            self.refresh()

    def can_close(self) -> bool:
        return not self.editor.dirty

    def mark_clean(self) -> None:
        self.editor.mark_clean()
        self._sync_dirty()

    def on_theme_changed(self) -> None:
        self.editor.rehighlight()

    # ════════════════════════════════════════════════════════
    # 数据
    # ════════════════════════════════════════════════════════

    def refresh(self) -> None:
        if not self.run_id:
            self.items = []
            self.tree.clear()
            self.summary.setText("（还没选中运行 —— 在「运行历史」里选一次）")
            self._clear_editor()
            return

        # run_id → 运行目录：走 `pipeline.detail` 那一条（与签核判定页同一套），
        # 不自己再写一遍反解 —— 两份"哪儿找运行"的逻辑迟早会不一致。
        detail = self.run_tool("pipeline.detail", quiet=True, run_id=self.run_id)
        if not isinstance(detail, dict) or self.report_payload_error(detail):
            return
        self.run_dir = str(detail.get("dir", "") or "")
        if not self.run_dir:
            self.show_warning(f"找不到运行 {self.run_id} 的目录")
            return

        payload = self.run_tool("flow.artifacts", run_dir=self.run_dir)
        if not isinstance(payload, dict) or self.report_payload_error(payload):
            return
        self.items = payload.get("artifacts") or []
        self.summary.setText(f"{self.run_id}：{payload.get('summary', '')}")
        self._fill_tree()

    def _fill_tree(self) -> None:
        """按阶段分组铺开。**保留当前选中的那一份** —— 刷新一下就把人正在看的
        文件弹掉的界面是没法用的。"""
        keep = self.path
        self.tree.blockSignals(True)
        self.tree.clear()
        self._nodes.clear()

        groups: Dict[str, QTreeWidgetItem] = {}
        for item in self.items:
            group = str(item.get("group") or "其它")
            parent = groups.get(group)
            if parent is None:
                parent = QTreeWidgetItem(self.tree, [group, ""])
                parent.setFirstColumnSpanned(True)
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                parent.setExpanded(True)
                groups[group] = parent

            node = QTreeWidgetItem(parent, [str(item.get("name", "")), self._status_text(item)])
            node.setData(0, Qt.ItemDataRole.UserRole, item)
            node.setToolTip(0, self._tooltip(item))
            brush = QBrush(QColor(self._status_color(item)))
            node.setForeground(1, brush)
            if not item.get("exists"):
                node.setForeground(0, QBrush(QColor(theme.current().muted)))
            self._nodes[str(item.get("path", ""))] = node

        self.tree.blockSignals(False)
        self._reselect(keep)

    def _reselect(self, path: Optional[Path]) -> None:
        if path is None:
            self._on_selected()
            return
        rel = self._rel_of(path)
        node = self._nodes.get(rel)
        if node is None:
            self._on_selected()
            return
        node.setSelected(True)
        self.tree.scrollToItem(node)

    def _status_text(self, item: Dict[str, Any]) -> str:
        if not item.get("exists"):
            return "还没生成"
        if item.get("errors"):
            return f"✗ {item['errors']} 处错误"
        if item.get("warnings"):
            return f"! {item['warnings']} 处告警"
        if item.get("schema"):
            return "✓"
        return "（无 schema）"

    @staticmethod
    def _status_color(item: Dict[str, Any]) -> str:
        palette = theme.current()
        if not item.get("exists"):
            return palette.muted
        if item.get("errors"):
            return palette.error
        if item.get("warnings"):
            return palette.warning
        return palette.ok if item.get("schema") else palette.muted

    def _tooltip(self, item: Dict[str, Any]) -> str:
        lines = [str(item.get("path", "")),
                 f"大小：{item.get('size_kb', 0)} KB"]
        if item.get("sha256"):
            lines.append(f"sha256：{item['sha256'][:16]}…")
        lines.append(f"schema：{item.get('schema') or '（没有 schema，只做文本编辑）'}")
        for message in item.get("messages") or []:
            lines.append(f"  [{message.get('severity')}] {message.get('text')}")
        if not item.get("exists"):
            lines.append("这一份还没生成 —— 说明那次运行没跑到产出它的阶段")
        return "\n".join(lines)

    # ════════════════════════════════════════════════════════
    # 选中 / 编辑
    # ════════════════════════════════════════════════════════

    def _selected(self) -> Optional[Dict[str, Any]]:
        nodes = self.tree.selectedItems()
        if not nodes:
            return None
        return nodes[0].data(0, Qt.ItemDataRole.UserRole)

    def _on_selected(self) -> None:
        item = self._selected()
        if item is None:
            self._clear_editor()
            return
        if self.editor.dirty and not self._confirm_discard():
            # 不放弃的话把选中退回去 —— 让人回到他正在改的那一份
            self._reselect(self.path)
            return
        self.load(str(item.get("path", "")))

    def _clear_editor(self) -> None:
        self.path = None
        self.editor.setReadOnly(True)
        self.editor.set_text("")
        self.head.setText("（从左边选一份产物）")
        self.panel.set_issues([])
        self.save_btn.setEnabled(False)
        self.reload_btn.setEnabled(False)
        self.status.setText("")

    def load(self, rel_path: str) -> bool:
        if not self.run_id or not rel_path:
            self._clear_editor()
            return False
        target = self._abs_of(rel_path)
        if not target.is_file():
            self._clear_editor()
            self.head.setText(f"{rel_path}　还没生成（那次运行没跑到这一步）")
            return False
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.show_error(f"读不了 {rel_path}：{exc}")
            return False

        self.path = target
        self.editor.setReadOnly(False)
        self.editor.set_text(text)
        self.save_btn.setEnabled(True)
        self.reload_btn.setEnabled(True)
        self._sync_head()
        self._revalidate()
        return True

    def reload(self) -> None:
        """把盘上那一份重新读回来 —— 丢掉未保存的改动。"""
        if self.path is None:
            return
        if self.editor.dirty and not self._confirm_discard():
            return
        self.load(self._rel_of(self.path))

    def _on_content_changed(self, _first: bool) -> None:
        self._sync_dirty()
        self._timer.start()

    def _sync_dirty(self) -> None:
        if self.path is None:
            return
        self.save_btn.setText("保存 ●" if self.editor.dirty else "保存")
        self._sync_head()
        self._mark_dirty_node()

    def _mark_dirty_node(self) -> None:
        """把"改过没保存"标到树上 —— 几份都打开着时得看得出是**哪一份**。"""
        if self.path is None:
            return
        node = self._nodes.get(self._rel_of(self.path))
        if node is None:
            return
        item = self._selected() or {}
        text = self._status_text(item)
        node.setText(0, f"● {item.get('name', '')}" if self.editor.dirty
                     else str(item.get("name", "")))
        node.setText(1, text)

    def goto_issue(self, issue: Any) -> None:
        needle = _needle_of(getattr(issue, "target", ""))
        line = getattr(issue, "line", None)
        if line:
            self.editor.goto_line(int(line))
        elif needle:
            self.editor.find_line(needle)

    def _revalidate(self) -> None:
        """拿编辑器当前文本重算诊断 —— 走的是**文本**，不落盘。

        用的是与产物清单**同一个** schema 校验器（`flow.artifacts` 背后的
        `SchemaChecker`），所以清单上那个 ✗ 和这里列出来的诊断必然一致；
        两处各算一遍迟早会不一致。
        """
        if self._timer.isActive():
            self._timer.stop()
        if self.path is None:
            return
        issues = self._check_text(self.editor.text())
        self.panel.set_issues(issues)
        errors = [i for i in issues if getattr(i, "severity", "") == "error"]
        if errors:
            self.status.setText(f"{len(errors)} 处 schema 错误 —— 保存前会再问一次")
        else:
            self.status.setText("schema 校验通过")
        self._sync_head()

    def _check_text(self, text: str) -> List["_Issue"]:
        """拿编辑器当前文本跑 schema，转成诊断面板认的形状。

        用的是与产物清单**同一个**校验器（`flow.artifacts` 背后那份
        `SchemaChecker`），所以清单上那个 ✗ 和这里列出来的诊断必然一致 ——
        两处各算一遍迟早会不一致。
        """
        from src.tools.uvm_tools.tool_uvm.schema_check import get_checker

        item = self._selected() or {}
        if not item.get("schema"):
            return []                     # 没有 schema 的产物只做文本编辑

        import tempfile

        # 校验器吃的是文件 —— 写一份临时副本，不动盘上那份
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                             encoding="utf-8") as handle:
                handle.write(text)
                temp = Path(handle.name)
            try:
                raw = list(get_checker().check([temp]))
            finally:
                temp.unlink(missing_ok=True)
        except Exception as exc:
            self.log(f"schema 校验没能跑起来：{exc}", "warning")
            return []

        # 校验器吃的是文件，所以它把**临时文件的名字**写进了 target 和消息里。
        # 不换回来的话，人会在诊断里看到一个 `tmpab12cd.yaml` —— 一个盘上根本
        # 不存在的文件。换成本来那份产物的名字，行号对得上、文件名也对得上。
        return [_Issue.of(issue, text, temp_name=temp.name,
                          real_name=self.path.name if self.path else "") for issue in raw]

    def _sync_head(self) -> None:
        if self.path is None:
            return
        item = self._selected() or {}
        bits = [self._rel_of(self.path)]
        if item.get("group"):
            bits.append(str(item["group"]))
        if item.get("sha256"):
            bits.append(f"sha256 {item['sha256'][:12]}")
        bits.append("改过未保存" if self.editor.dirty else "与盘上一致")
        self.head.setText("　·　".join(bits))

    # ════════════════════════════════════════════════════════
    # 保存
    # ════════════════════════════════════════════════════════

    def save_artifact(self) -> bool:
        if self.path is None:
            return False
        if not self._confirm_scope():
            return False

        text = self.editor.text()
        errors = [i for i in self._check_text(text)
                  if getattr(i, "severity", "") == "error"]
        if errors:
            from PySide6.QtWidgets import QMessageBox

            detail = "\n".join(f"· {i}" for i in errors[:8])
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
            self.show_error(f"保存失败：{exc}")
            return False

        self.editor.mark_clean()
        # 写盘之后立刻记账 —— 带 run_id：这次编辑**属于这次运行**，日志里会有锚点
        recorded = self.record_human_edit(self.path, self.reason_edit.text(),
                                          run_id=self.run_id)
        self.reason_edit.clear()
        self.refresh()                    # 重列一遍：哈希与诊断都变了
        tail = f"　已记账 #{recorded['seq']}（{recorded['author']}）" if recorded else ""
        self.set_status(f"已保存 {self._rel_of(self.path)}{tail}　—— 要让改动生效需重跑")
        return True

    def _confirm_scope(self) -> bool:
        """第一次保存时提醒一次"改的是运行产物、不会自动重跑"。

        只问一次，不每次都弹 —— 一个人连着改五份产物，弹五个框只会让他学会
        无脑点"是"，那还不如不弹。
        """
        if getattr(self, "_scope_ack", False):
            return True
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self.content, "改的是这次运行的产物",
            f"这份文件在**这次运行**的目录里：\n\n{self._rel_of(self.path)}\n\n"
            "保存会写回文件、并记进证据链。但**不会自动重跑** —— 要让改动生效，"
            "得重新起一次运行。\n\n继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self._scope_ack = True
        return True

    def _confirm_discard(self) -> bool:
        if not self.editor.dirty:
            return True
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self.content)
        box.setWindowTitle("有未保存的改动")
        box.setText(f"{self._rel_of(self.path) if self.path else ''} 改过还没保存。")
        save = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("放弃", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            return self.save_artifact()
        return clicked is discard

    # ════════════════════════════════════════════════════════
    # 路径 —— 产物一律相对**运行目录**
    # ════════════════════════════════════════════════════════

    def _abs_of(self, rel_path: str) -> Path:
        return (Path(self.run_dir) / rel_path) if self.run_dir else Path(rel_path)

    def _rel_of(self, path: Path) -> str:
        if not self.run_dir:
            return str(path)
        try:
            return str(path.relative_to(self.run_dir)).replace("\\", "/")
        except ValueError:
            return str(path)


#: 严重度 → 中文。面板的"严重度"一栏靠它 —— 那一栏正是用来一眼扫出
#: "有没有 error"的，留空等于把最要紧的信息抹了。
_SEVERITY_CN = {"error": "错误", "warning": "警告", "info": "提示"}


@dataclass
class _Issue:
    """把 UVM 的 `Issue` 适配成诊断面板认的形状。

    面板认一个协议：`severity / category / rule / target / message` 加上两个中文列
    `severity_cn / category_cn`。UVM 那个 `Issue` 只有前四个的英文版，直接塞进去
    "严重度"会是空白。

    `line` 是自己算的（UVM 的 Issue 不带行号）：拿 target 的最后一段键名去文本里
    找 `键:` 那一行。**找不到就留空**，宁可点不过去，也不要跳到一个错的行号上 ——
    那会让人以为问题在别处。
    """

    severity: str
    rule: str
    target: str
    message: str
    line: Optional[int] = None

    @classmethod
    def of(cls, issue: Any, text: str, *, temp_name: str = "",
           real_name: str = "") -> "_Issue":
        target = str(getattr(issue, "target", "") or "")
        message = str(issue)
        if temp_name and real_name:
            # 把"临时文件的名字"换回"真正那份产物的名字"（见调用点的说明）
            target = target.replace(temp_name, real_name)
            message = message.replace(temp_name, real_name)
        return cls(
            severity=str(getattr(issue, "severity", "error") or "error"),
            rule=str(getattr(issue, "rule", "") or ""),
            target=target,
            message=message,
            line=_line_in(text, _needle_of(target)),
        )

    @property
    def category(self) -> str:
        return self.rule

    @property
    def category_cn(self) -> str:
        return self.rule

    @property
    def severity_cn(self) -> str:
        return _SEVERITY_CN.get(self.severity, self.severity)


def _line_in(text: str, needle: str) -> Optional[int]:
    """在文本里找 `needle:` 那一行（1 基）。找不到返回 None。"""
    if not needle:
        return None
    for index, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith(f"{needle}:"):
            return index
    return None


def _needle_of(target: str) -> str:
    """诊断 target → 去 YAML 里找行的线索（最后一段有意义的键名）。

    `bench.yaml::bench.agents` → `agents`。与人工节点页同一套口径。
    """
    if not target:
        return ""
    segments = [s for s in _PATH_SPLIT.split(str(target).split("::")[-1])
                if s and not s.isdigit()]
    return segments[-1] if segments else ""
