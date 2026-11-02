"""模块导航树 —— 左窗格里的那棵树。

Verdi 左边是层次浏览树（Hierarchy）：按设计层级摊开，双击进到某一层。我们
没有「设计层级」这个概念，对应的东西是**模块清单**，按验证体的业务分层摊开：

    **业务域** → **业务线** → **模块**
    设计时 / 构建与执行 / 流程与证据
        └─ 编译与回归（ops）
              └─ 回归产出

三层为什么这么分：一条业务线（"谁负责"）之上还有"这一步在哪一段" ——
七个 agent 线是**执行**、`ide` 是**设计时**、`flow` 是横切的**流程与证据**。
域这一层就是把这三段分开，切换时才有"进到某个业务段"的感觉。

清单里不写 `section` 的业务线直接挂树根 —— 于是退化成两级（老清单照旧能用）。

平台自带，不是模块（没有 `ModuleSpec`）：它读的是清单与 manager，那两个都是
平台概念。它作为左窗格的 0 号页签常驻，所以左窗格通常是「有内容」的 ——
真要收起左窗格是用户显式选「视图 → 模块导航树」。

**它也是业务线唯一可见的地方**：菜单栏改成了 Verdi 的七项（文件/编辑/视图/
调试/工具/窗口/帮助），业务线不再占顶层菜单，靠这棵树 + 窗口菜单的子菜单承载。
"""
from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import (QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ..theme import icons, palette as theme

#: 模块 id 存在这个角色里 —— 取的时候不必再解析树节点文字
MODULE_ROLE = Qt.ItemDataRole.UserRole
#: 业务线 id 存在孩子身上，切换时用来提示「这是哪条线的模块」
GROUP_ROLE = Qt.ItemDataRole.UserRole + 1


class NavPane(QWidget):
    """按业务线分组的模块导航树。"""

    def __init__(self, on_activate: Callable[[str], bool],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._on_activate = on_activate
        self._items: Dict[str, QTreeWidgetItem] = {}
        self._groups: Dict[str, QTreeWidgetItem] = {}
        self._sections: Dict[str, QTreeWidgetItem] = {}
        self._active: Optional[QTreeWidgetItem] = None
        self.business_mode = "all"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._build_tree())

    def _build_tree(self) -> QTreeWidget:
        tree = QTreeWidget(self)
        self.tree = tree
        tree.setObjectName("navTree")
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(False)
        tree.setExpandsOnDoubleClick(False)     # 双击留给「切换模块」
        tree.itemActivated.connect(self._activated)   # 双击 或 回车
        return tree

    # ════════════════════════════════════════════════════════
    # 建树
    # ════════════════════════════════════════════════════════

    def populate(self, manifest) -> None:
        """按清单建树：**业务域 → 业务线 → 模块**。

        三级不是硬性的 —— 清单里没写 `section` 的业务线直接挂在树根，
        于是退化成"业务线 → 模块"两级（老清单/测试夹具走的还是这条路）。

        顺序完全由清单决定：`sections()` 给出域与线，`modules_of()` 给出模块。
        """
        self.tree.clear()
        self._items.clear()
        self._groups.clear()
        self._sections.clear()
        self._active = None

        group_items = []                      # 所有业务线节点，稍后统一补占位
        for section, groups in manifest.sections():
            parent = None
            if section:
                parent = QTreeWidgetItem(self.tree, [section])
                parent.setIcon(0, icons.icon("tree"))
                parent.setFlags(parent.flags()
                                & ~Qt.ItemFlag.ItemIsSelectable
                                & ~Qt.ItemFlag.ItemIsEditable)
                parent.setExpanded(True)
                _mark_as_domain(parent)
                self._sections[section] = parent
            for group in groups:
                top = self._add_group(parent, group, manifest)
                self._groups[group.id] = top
                group_items.append(top)

        # 业务线为空时留一个占位孩子，免得一条线看起来像「坏了」
        for top in group_items:
            if top.childCount() == 0:
                placeholder = QTreeWidgetItem(top, ["（本业务线还没有模块）"])
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                placeholder.setForeground(0, QBrush(theme.MUTED))

    def _add_group(self, parent: Optional[QTreeWidgetItem], group, manifest):
        """一条业务线节点（含它的模块孩子）。`parent=None` 表示挂在树根。"""
        top = (QTreeWidgetItem(parent, [group.title]) if parent is not None
               else QTreeWidgetItem(self.tree, [group.title]))
        top.setIcon(0, icons.standard("folder"))
        top.setData(0, GROUP_ROLE, group.id)
        top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        top.setExpanded(True)
        for spec in manifest.modules_of(group.id):    # 全部区域，不只 center
            child = QTreeWidgetItem(top, [spec.title])
            child.setIcon(0, icons.icon("module"))
            child.setData(0, MODULE_ROLE, spec.id)
            child.setData(0, GROUP_ROLE, group.id)
            child.setToolTip(0, f"{spec.title}\n{spec.id}　区域：{spec.area}")
            self._items[spec.id] = child
        return top

    def set_business_mode(self, mode: str) -> None:
        """业务模式：`all` / `soc` / `ip`。

        只隐藏“另一条团队线”，共享的流程/证据/专业工具始终可见 ——
        切 SoC 模式不是把 IP 数据删掉，只是把 IP 团队入口收起。
        """
        mode = mode if mode in ("all", "soc", "ip") else "all"
        self.business_mode = mode
        for gid, item in self._groups.items():
            hidden = ((mode == "soc" and gid == "ip")
                      or (mode == "ip" and gid == "soc"))
            item.setHidden(hidden)
        for section, item in self._sections.items():
            visible = any(not item.child(i).isHidden()
                          for i in range(item.childCount()))
            item.setHidden(not visible)

    # ════════════════════════════════════════════════════════
    # 状态
    # ════════════════════════════════════════════════════════

    def set_active(self, module_id: str) -> None:
        """把当前模块加粗。同一时刻只有一个 —— 否则看不出「现在在哪」。"""
        previous, self._active = self._active, self._items.get(module_id)
        if previous is not None and previous is not self._active:
            previous.setFont(0, _font(bold=False))
        if self._active is not None:
            self._active.setFont(0, _font(bold=True))
            self.tree.scrollToItem(self._active)

    def set_failed(self, failures: Dict[str, str]) -> None:
        """加载失败的模块标红加警告图标 —— 界面上它是个 traceback 页签，
        树上也得看得出来，否则用户会一直点它。"""
        for module_id, reason in failures.items():
            item = self._items.get(module_id)
            if item is None:
                continue
            item.setIcon(0, icons.standard("warning"))
            item.setForeground(0, QBrush(theme.SEVERITY["error"]))
            item.setToolTip(0, f"{item.text(0)}\n加载失败：{reason}")

    def module_at(self, item: Optional[QTreeWidgetItem]) -> str:
        return str(item.data(0, MODULE_ROLE) or "") if item is not None else ""

    def item_ids(self) -> Dict[str, QTreeWidgetItem]:
        """module_id → 树节点。测试与自查用。"""
        return dict(self._items)

    # ════════════════════════════════════════════════════════
    # 交互
    # ════════════════════════════════════════════════════════

    def _activated(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        """双击/回车才切换。单击只选中 —— 与 Verdi 的层次树一致：

        在树里点一下只是想看看，双击才是「进到这儿」。
        """
        module_id = self.module_at(item)
        if module_id:
            self._on_activate(module_id)


def _font(bold: bool) -> QFont:
    font = theme.ui_font()
    font.setBold(bold)
    return font


def _mark_as_domain(item: QTreeWidgetItem) -> None:
    """把业务域节点画成「标题级」——加粗 + 次要色。

    三种节点的观感要一眼分得开：**域**（这一步在哪一段）> **线**（谁负责）
    > **模块**（具体看什么）。域节点借 `set_active` 那套加粗字重，但用弱色，
    免得它比"当前在哪"还抢眼。
    """
    font = theme.ui_font()
    font.setBold(True)
    item.setFont(0, font)
    item.setForeground(0, QBrush(theme.MUTED))
