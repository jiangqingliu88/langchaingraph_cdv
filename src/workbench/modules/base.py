"""模块插件接口。

设计模式：**Template Method**。`IModule` 定下平台会调用的那几个钩子，
`ModuleBase` 把「顶部横幅 + 错误落点 + 工具调用」这三件每个模块都要做的事
实现掉，子类只需要写 `build_content()`（搭控件）与 `on_refresh()`（填数据）。

模块**只拿 `AnalysisResult` 式的只读结果与 `AppContext`，不自己读文件、
不自己算结论** —— 判定逻辑都在 `src/tools/` 里那层。这样模块能脱离主窗口
单独测，也是「工具与界面分开」这条线在界面侧的落点。

`placeholder: true` 的模块**自动**得到一条关不掉的琥珀横幅：不能靠模块
作者记得加。清单里标了它是占位，平台就得保证它看起来像占位。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..bridge.binding import ToolError, payload_error
from ..context import AppContext
from ..spec import ModuleSpec
from ..ui.widgets.banner import Banner, PermanentNote

#: 占位模块的常驻说明 —— 文案统一在这里，改口径只改一处
PLACEHOLDER_NOTE = ("演示占位 —— 本视图没有接真实数据源，画面上的内容是示意，"
                    "不代表任何实际设计。")


class IModule(ABC):
    """一个业务模块。平台只认这个接口，不认识任何具体模块。"""

    #: 子类可以覆盖：给菜单项用的简短标题（默认用 spec.title）
    def __init__(self, ctx: AppContext, spec: ModuleSpec) -> None:
        self.ctx = ctx
        self.spec = spec

    # ── 身份 ──

    @property
    def module_id(self) -> str:
        return self.spec.id

    @property
    def title(self) -> str:
        return self.spec.title

    @property
    def group(self) -> str:
        return self.spec.group

    # ── 生命周期：平台会调的钩子。除 create_widget 外都可选 ──

    @abstractmethod
    def create_widget(self) -> QWidget:
        """构造本模块的主控件。**只调一次**，返回的控件由平台接管所有权。"""

    def create_actions(self) -> List[QAction]:
        """本模块自有动作（带快捷键），会进所属业务线菜单与工具栏。默认没有。"""
        return []

    def on_activated(self) -> None:
        """标签页被选中 / dock 被抬升。默认什么都不做。

        注意：构造期**不要**依赖 `ctx.window` —— 那时候窗口还没建完。
        需要窗口的东西放这里。
        """

    def on_input_changed(self, path) -> None:
        """`spec.input` 指向的文件被换了。默认什么都不做。"""

    def can_close(self) -> bool:
        """有未保存改动就返回 False —— 平台据此弹「保存 / 放弃 / 取消」。"""
        return True

    def mark_clean(self) -> None:
        """把脏状态清掉。测试与关窗口流程用；默认无状态，空实现。"""

    def on_theme_changed(self) -> None:
        """主题切了 —— 需要重挂图标 / 重画自绘控件的模块在这里做。默认什么都不做。

        图标是按主题色渲染成位图的，`setIcon` 之后位图就固定了；不重挂的话，
        浅色换上深色时会留下一排黑色线描图标。
        """

    def on_refresh(self, payload: Any = None) -> None:
        """收到订阅的事件后被调用。默认什么都不做。"""


class ModuleBase(IModule):
    """常态模块的公共壳。

    子类实现两件事：
        build_content() -> QWidget   搭控件（只调一次）
        on_refresh(payload)          填数据（可多次）
    """

    #: 顶部额外提示（子类可覆盖，会显示在横幅下方）
    HINT: str = ""

    def __init__(self, ctx: AppContext, spec: ModuleSpec) -> None:
        super().__init__(ctx, spec)
        self._widget: Optional[QWidget] = None
        self.banner: Optional[Banner] = None
        #: 子类在 build_content() 里搭出来的内容控件，壳建好之后才有值
        self.content: Optional[QWidget] = None

    # ── 平台接口 ──

    def create_widget(self) -> QWidget:
        if self._widget is None:
            self._widget = self._build_shell()
        return self._widget

    def _build_shell(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # 占位模块的说明放在**最上面**且关不掉：它能被忽略的代价太大
        if self.spec.placeholder:
            layout.addWidget(PermanentNote(f"{self.title}：{PLACEHOLDER_NOTE}", "warning", root))

        self.banner = Banner(root)
        layout.addWidget(self.banner)

        self.content = self.build_content()
        layout.addWidget(self.content, 1)
        return root

    # ── 子类实现 ──

    @abstractmethod
    def build_content(self) -> QWidget:
        """搭本模块的内容控件。只调一次。"""

    def on_refresh(self, payload: Any = None) -> None:
        """填数据。默认什么都不做。"""

    # ── 给子类的工具 ──

    def run_tool(self, name: Optional[str] = None, *, quiet: bool = False,
                 force: bool = False, **kwargs) -> Any:
        """调一个登记过的工具。

        失败时**不抛**：把话说清楚（横幅 + 控制台 + 状态栏）然后返回 None。
        界面里的按钮回调不该让异常穿出去 —— 穿出去的结果是「点了没反应」，
        比报错更难查。

        `quiet=True` 用于「这个失败是预期的」（比如扫描一个用户还没选的
        目录），只进控制台，不弹横幅。

        `force=True` 用于 `pure=False` 的绑定（启动/取消运行）。绑定表把
        「长任务」标出来是防"切个标签页就顺手跑一遍"，而按钮点击正是那个
        **显式触发**——所以由按钮的处理器显式传 force。
        """
        tool_name = name or (self.spec.tool.name if self.spec.tool else None)
        if not tool_name:
            self.show_error(f"模块 {self.module_id} 没有绑定工具，也没有指定名字")
            return None
        merged = dict(self.spec.tool.args) if self.spec.tool else {}
        merged.update(kwargs)
        try:
            return self.ctx.call_tool(tool_name, force=force, **merged)
        except ToolError as exc:
            self.ctx.log(f"[{self.module_id}] {tool_name} 失败：{exc.cause}", "error")
            if not quiet:
                self.show_error(f"工具调用失败：{exc.cause}")
            self.ctx.status(f"{self.title}：工具调用失败")
            return None

    def record_human_edit(self, path, reason: str = "",
                          run_id: str = "") -> Optional[Dict[str, Any]]:
        """人在这个模块里改了一个文件 —— 记进证据链。

        这是**每个能写盘的模块的共同义务**，不是某个模块的偏好：写盘之后不调它，
        那次编辑在哈希链、运行日志、五层证据里一条痕迹都没有 —— 而"可审计、可
        追溯"是这个产品的第一承诺。放在基类里，是想漏也漏不掉。

        `run_id` 可选：**改的是某次运行的产物时传它**，那次运行的日志里会多一条
        `human.edit` 锚点（时间线上看得出"这轮回归之前人改了什么"）。改静态配置
        （如 `manual_nodes.yaml`）时没有运行可挂，留空即可 —— 链照样记。

        返回记账自陈（含 seq / author / hash），失败返回 None。

        **记账失败要说出来。** 文件已经落地，回滚只会更乱，所以不回滚；但"改了没
        痕迹"正是这一刀要堵的洞，静默失败等于洞还在。所以走警告横幅，不走控制台。
        """
        result = self.run_tool("evidence.record_human_edit", force=True,
                               path=str(path), reason=reason, run_id=run_id)
        if isinstance(result, dict) and result.get("recorded"):
            self.log(f"人工编辑已记账：{path}（第 {result['seq']} 条，"
                     f"{result['author']}）")
            return result
        detail = result.get("error") if isinstance(result, dict) else "工具调用失败"
        self.show_warning(f"已保存 {path}，但**没有记进证据链**（{detail}）"
                          f"—— 这次编辑在审计上没有痕迹。")
        return None

    def show_error(self, text: str) -> None:
        if self.banner is not None:
            self.banner.show_message(text, "error")
        self.ctx.log(f"[{self.module_id}] {text}", "error")
        self.ctx.status(text.splitlines()[0] if text else "")

    def show_warning(self, text: str) -> None:
        if self.banner is not None:
            self.banner.show_message(text, "warning")
        self.ctx.log(f"[{self.module_id}] {text}", "warning")

    def show_info(self, text: str) -> None:
        if self.banner is not None:
            self.banner.show_message(text, "info")
        self.ctx.log(f"[{self.module_id}] {text}", "info")

    def clear_banner(self) -> None:
        if self.banner is not None:
            self.banner.clear_message()

    def report_payload_error(self, payload: Any) -> bool:
        """工具返回的是「一条错误」时，把它变成横幅并返回 True。

        `debug_tools` 在目录不存在时返回 `{"error": "output_dir not found"}`，
        原样铺进表格会显示成一行莫名其妙的文本。认出来才叫「把话说清楚」。
        """
        message = payload_error(payload)
        if message:
            self.show_warning(f"{self.title}：{message}")
            return True
        return False

    def log(self, text: str, level: str = "info") -> None:
        self.ctx.log(f"[{self.module_id}] {text}", level)

    def set_status(self, text: str) -> None:
        self.ctx.status(text)

    def set_tab_suffix(self, suffix: str) -> None:
        """给本模块的标签页标题挂个后缀（如「 — model.yaml ●」）。

        模块不自己找标签页下标 —— 那是平台的事（它才知道模块被放在哪儿）。
        有未保存改动的模块靠这个把 ● 标出来：同时开着几个模块时，得看得出
        是**哪一个**没存。
        """
        window = self.ctx.window
        if window is not None and hasattr(window, "set_tab_suffix"):
            window.set_tab_suffix(self.module_id, suffix)
