"""`AppContext` —— 模块能碰到的**全部**平台能力，就这一张清单。

为什么要这个对象：模块需要「调工具、发事件、写控制台、读配置、跑后台任务」
五件事。如果让它自己 `import` 这些单例，模块就没法单独测，也没法知道
「我到底能用什么」。把它们收进一个显式传进来的对象，边界就看得见了。

**窗口是弱引用式的**：`ctx.window` 在建窗口的过程中回填（窗口要先有
`AppContext` 才能建模块，模块又要拿窗口加 dock —— 这是个循环）。模块不该
在构造期用 `ctx.window`，`on_activated()` 之后才有意义。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .bus import EventBus
from .config import resolve_input
from .manifest import WorkbenchManifest
from .settings_store import SettingsStore
from .spec import ModuleSpec
from .tasks import TaskRunner


@dataclass
class AppContext:
    """一次运行的全部共享状态。"""

    manifest: WorkbenchManifest
    manifest_path: Path
    tools: Any                                    # ToolRegistry
    bus: EventBus
    tasks: TaskRunner
    settings: SettingsStore
    #: 窗口 —— 建好之后由 `WorkbenchWindow.__init__` 回填
    window: Any = None
    #: 控制台面板 —— 建好之后回填；没有时日志静默丢弃（测试里不建控制台）
    console: Any = None
    #: 模块 id → 模块实例，由 ModuleManager 回填（模块之间要互相找时用）
    modules: dict = field(default_factory=dict)
    #: 业务模式：all / soc / ip（只影响导航可见性，不影响模块实例）
    business_mode: str = "all"

    # ── 路径 ──

    def data_path(self, spec: ModuleSpec) -> Optional[Path]:
        """`ModuleSpec.input` → 绝对路径。清单里没写就返回 None。"""
        return resolve_input(self.manifest_path, spec.input)

    def existing_data_path(self, spec: ModuleSpec) -> Optional[Path]:
        """同上，但文件不存在时返回 None —— 让调用方安静降级而不是报错。"""
        path = self.data_path(spec)
        return path if path is not None and path.exists() else None

    # ── 消息 ──

    def log(self, text: str, level: str = "info") -> None:
        if self.console is not None:
            self.console.append(text, level)

    def status(self, text: str) -> None:
        if self.window is not None and hasattr(self.window, "set_status"):
            self.window.set_status(text)

    # ── 工具 ──

    def call_tool(self, name: str, *, force: bool = False,
                  actor: str = "user", approval: bool = False, **kwargs):
        """调一个登记过的工具 —— 失败时抛 `bridge.binding.ToolError`。

        模块通常用 `ModuleBase.run_tool()`（它会把异常变成横幅），直接调这个
        是为了在已经自己处理错误的地方少绕一层。

        `force=True` 才能调 `pure=False` 的绑定（启动/取消运行这类长任务）——
        那是**用户按了按钮**才算数的显式触发，不是"切个标签页顺手跑一遍"。
        `actor` / `approval` 对应绑定的触发权限（见 `bridge/binding.py` 的
        `TRIGGERS`）：写发布包这类对外动作要求 `approval=True`。
        """
        return self.tools.call(name, force=force, actor=actor,
                               approval=approval, **kwargs)
