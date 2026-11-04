"""工作台主窗口 —— 命令行界面之外的那个「界面」。

窗口自己几乎不做业务，只做四件事：
  1. 读清单 → 交给 `ModuleManager` 建界面
  2. 摆好中央标签页 + 三面 Dock + 状态栏 + 控制台
  3. 提供模块要用的那几个钩子（`set_tab_suffix` / `set_status` / 窗格开关）
  4. 关窗口时逐个问模块「能关吗」，存/取布局

**中央标签页不可关闭**（Dock 可以）。理由：中央区是「工作区」，标签页对应
一个能干活的模块，关掉它没有语义（不像文档）；Dock 关掉之后菜单里能再打开，
所以给它开关是安全的。两边区别对待是刻意的。

启动：
    python -m src.workbench [清单.yaml] [--module ID] [--input 路径]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .bootstrap import require_pyside6
from .bus import EventBus
from .config import resolve_manifest_path
from .constants import APP_TITLE, CONSOLE_TITLE
from .context import AppContext
from .manifest import ManifestError, builtin_manifest, describe, load_manifest
from .registry import ModuleManager
from .settings_store import SettingsStore
from .topics import (
    TOPIC_TASK_COMPLETED, TOPIC_TASK_STARTED, TaskCompleted, TaskStarted,
)
from .ui import theme
from .ui.widgets.banner import Banner
from .ui.widgets.console import ConsolePanel


def _publish_task_started(ctx: AppContext, task_id: str, label: str) -> None:
    """任务开始 → `task.started`（带上模块归属与所属 run）。"""
    rec = ctx.tasks.record(task_id)
    ctx.bus.publish(TOPIC_TASK_STARTED, TaskStarted(
        task_id=task_id,
        module_id=rec.module_id if rec else "",
        operation=rec.operation if rec else label,
        run_id=rec.run_id if rec else "").to_payload())


def _publish_task_done(ctx: AppContext, task_id: str) -> None:
    """任务结束（成功或失败）→ `task.completed`。"""
    rec = ctx.tasks.record(task_id)
    ctx.bus.publish(TOPIC_TASK_COMPLETED, TaskCompleted(
        task_id=task_id,
        status=rec.status if rec else "",
        run_id=rec.run_id if rec else "",
        error=rec.error if rec else "").to_payload())

#: 平台自带页签的 id。双下划线打头是刻意的 —— 它们不是清单里的模块，
#: 不能跟模块 id 撞车。
CONSOLE_PIN = "__console__"
NAV_PIN = "__nav__"

#: 项目下拉里那条"就地登记"的哨兵值（不是项目 id）
REGISTER_ACTION = "__register__"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.workbench",
        description="验证工作台 —— 界面由 YAML 清单驱动（默认 config/workbench.yaml）")
    parser.add_argument("manifest", nargs="?", default=None,
                        help="界面清单路径；不给就用 config/workbench.yaml")
    parser.add_argument("--module", "-m", default=None,
                        help="启动后聚焦到这个模块 id（清单里的 id）")
    parser.add_argument("--input", "-i", default=None,
                        help="覆盖指定模块的业务输入路径")
    parser.add_argument("--theme", default=None,
                        help=f"主题名（可选：{'、'.join(theme.PALETTES)}）")
    parser.add_argument("--reset-layout", action="store_true",
                        help="忽略上次保存的窗口布局")
    parser.add_argument("--project", default=None,
                        help="项目 id（登记表 ~/.signoffai/projects.yaml）—— "
                             "切到那个项目的工作目录与清单")
    return parser


def apply_project(args) -> None:
    """`--project` → 换工作目录 + 换清单。**必须在建窗口之前调**。

    为什么是"换目录"就等于"换项目"：产物（`output/`）与记忆
    （`database/*.db`）都是相对工作目录解析的，换了目录，两者天然互不可见
    —— 隔离不用新造机制（见 `projects.py` 的说明）。

    清单没显式给就用项目根下那份；项目目录不存在 → **报错退出**，不静默退化成
    "在当前目录跑另一个项目"（那会往错的目录里写产物）。
    """
    from . import projects as projects_mod

    project = projects_mod.find(str(args.project))
    if project is None:
        raise SystemExit(f"登记表里没有项目 {args.project!r}"
                         f"（找过 {projects_mod.registry_path()}）")
    if not project.exists:
        raise SystemExit(f"项目 {project.id} 的工作目录不存在：{project.root}")
    import os

    os.chdir(project.root)
    if not args.manifest:
        manifest = project.manifest_path
        if manifest is None:
            raise SystemExit(
                f"项目 {project.id} 下找不到界面清单"
                f"（{project.root}/config/workbench.yaml）—— 在登记表里写 manifest: 指一份")
        args.manifest = str(manifest)


def _build_window_class():
    """延迟加载：Qt 与主窗口类只在真正建窗口时才 import。"""
    from .main_window import build_window_class
    return build_window_class()


def _refresh_fonts(module) -> None:
    """换主题后把自设字体的控件重设一遍 —— 应用级字体对它们无效。"""
    for value in vars(module).values():
        if hasattr(value, "setFont") and hasattr(value, "document"):
            value.setFont(theme.mono_font())
    content = getattr(module, "content", None)
    if content is not None:
        content.update()


# ════════════════════════════════════════════════════════════
# 入口
# ════════════════════════════════════════════════════════════

def build_workbench(argv: Optional[Sequence[str]] = None):
    """建 QApplication 与主窗口，**不跑事件循环** —— 测试与 `main` 共用。

    清单坏了不阻断启动：用内置的空清单兜底 + 顶上一句红条。让人看到「清单
    写错了」远比让他看到闪退有用。
    """
    code = require_pyside6()
    if code is not None:
        raise SystemExit(code)

    from PySide6.QtWidgets import QApplication

    from .bridge.catalog import default_registry
    from .tasks import TaskRunner

    args = build_parser().parse_args(list(argv) if argv is not None else None)
    # `--project` 要**在解析清单路径之前**落地：它换的是工作目录 + 清单
    # （见 `apply_project`）。chdir 也必须早于建窗口 —— 之后起的 agent、记忆库、
    # 运行目录全都按当时的工作目录解析。
    if args.project:
        apply_project(args)
    app = QApplication.instance() or QApplication(list(sys.argv[:1]))

    manifest_path = resolve_manifest_path(args.manifest)
    manifest, error = _load_or_fallback(manifest_path)

    settings = SettingsStore()
    if args.reset_layout:
        settings.reset()

    # 主题的优先级：命令行 > 清单里写死的 > **上次用的** > 平台默认。
    # 中间那一档要有：清单明确写了主题就该听清单的（它是作者意图）；
    # 清单留空时才轮到用户的最后一次选择 —— 不然在视图里切了主题、
    # 下次开又回去了（`saved_theme()` 写进去却从来没人读，就是这么来的）。
    theme.apply(app, args.theme or manifest.window.theme
                or settings.saved_theme() or theme.DEFAULT_THEME)

    ctx = AppContext(
        manifest=manifest,
        manifest_path=manifest_path,
        tools=default_registry(),
        bus=EventBus(),
        # 任务运行器要先于窗口建好：模块在构造期就可能提交后台任务
        tasks=TaskRunner(),
        settings=settings,
    )

    window = _build_window_class()(app, ctx)

    if error is not None:
        window.show_banner(
            f"清单读不进来，先用一个空的界面顶着：\n{error}", "error")
        window.ctx.log(str(error), "error")

    if args.input and args.module:
        _push_input(ctx, args.module, args.input)
    if args.module:
        window.manager.focus(args.module)
    return app, window, ctx


def _load_or_fallback(manifest_path: Path):
    try:
        return load_manifest(manifest_path), None
    except ManifestError as exc:
        return builtin_manifest(), exc


def _push_input(ctx: AppContext, module_id: str, path: str) -> None:
    module = ctx.modules.get(module_id)
    if module is None:
        ctx.log(f"--input 指定的模块不存在：{module_id}", "warning")
        return
    module.on_input_changed(Path(path))


def main(argv: Optional[Sequence[str]] = None) -> int:
    app, window, _ctx = build_workbench(argv)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
