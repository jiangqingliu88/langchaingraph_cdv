"""测试夹具。

三条约定（与 `casemodel_tools/tests/conftest.py` 一致，那边踩过的坑这边不
再踩一遍）：

  · Qt 在**夹具里** import，不在模块顶层 —— 顶层 import 会让「没装 PySide6」
    变成收集期错误，而不是一条清楚的 skip。
  · 强制 `QT_QPA_PLATFORM=offscreen`：无需显示器、CI 上也不弹窗。
  · window 夹具的 teardown **先 mark_all_clean() 再 close()** —— 否则
    `closeEvent` 会弹「有未保存的改动」模态框，offscreen 下没人点它，
    测试会永久挂住。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ..manifest import load_manifest_text

#: 示例模型 —— 与 CLI 共用同一份（`config/casemodel/examples/`）。
#: 它们不放在 `casemodel_tools` 包里，是因为工具与工作台都要用，
#: 而两边谁都不该依赖对方。
EXAMPLES = Path(__file__).resolve().parents[3] / "config" / "casemodel" / "examples"
CPU = EXAMPLES / "cpu_pipeline.yaml"                 # 组织树 + 专题，写对了
CPU_FLAWED = EXAMPLES / "cpu_pipeline_flawed.yaml"   # 组织树 / 专题的坑
FC = EXAMPLES / "fc_flowcontrol.yaml"                # 扁平子对象 + 交叉组（老写法）
FC_FLAWED = EXAMPLES / "fc_flawed.yaml"              # 维度层的坑
FC_REAL = EXAMPLES / "fc_real_cases.yaml"            # 外部真实 case 列表

#: 干净的桩清单 —— 两个中央页（故意让 vms 那页的 order 更小，验证
#: 「业务线 order 优先于模块 order」）+ 两个底部模块（验证同窗格成页签）。
STUB_MANIFEST = """
version: 1
window:
  title: 测试工作台
  size: [900, 620]
  restore_layout: false
groups:
  - {id: debug, title: 调试技术, order: 10}
  - {id: vms, title: 验证管理系统, order: 30}
modules:
  - id: stub.center
    title: 中央页
    group: debug
    factory: src.workbench.tests.stub_modules:StubModule
    area: center
    order: 10
  - id: stub.center2
    title: 第二个中央页
    group: vms
    factory: src.workbench.tests.stub_modules:StubModuleWithAction
    area: center
    order: 5
  - id: stub.dock_a
    title: 底部甲
    group: debug
    factory: src.workbench.tests.stub_modules:StubModule
    area: bottom
    order: 10
  - id: stub.dock_b
    title: 底部乙
    group: debug
    factory: src.workbench.tests.stub_modules:StubModule
    area: bottom
    order: 20
"""

#: 含两个指向不存在类的模块（一个中央页、一个 dock）—— 验证失败隔离。
BROKEN_MANIFEST = STUB_MANIFEST + """
  - id: stub.broken
    title: 坏模块
    group: debug
    factory: src.workbench.tests.stub_modules:NoSuchModuleAnywhere
    area: center
    order: 90
  - id: stub.broken_dock
    title: 坏的底部
    group: debug
    factory: src.workbench.tests.stub_modules:NoSuchModuleAnywhere
    area: bottom
    order: 90
"""

#: 含一个「有未保存改动」的模块 —— 验证关窗口时的整体询问。
DIRTY_MANIFEST = STUB_MANIFEST + """
  - id: stub.dirty
    title: 脏模块
    group: debug
    factory: src.workbench.tests.stub_modules:StubDirtyModule
    area: bottom
    order: 90
"""

#: 订阅了总线话题的模块 —— 验证 params.subscribe 真的接线。
SUBSCRIBER_MANIFEST = STUB_MANIFEST + """
  - id: stub.subscriber
    title: 订阅者
    group: debug
    factory: src.workbench.tests.stub_modules:StubSubscriber
    area: right
    order: 90
    params:
      subscribe: [demo.refreshed]
"""


@pytest.fixture(scope="session")
def qt_app():
    """整个测试会话共用一个 QApplication（Qt 不允许建第二个）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def manifest():
    return load_manifest_text(STUB_MANIFEST, source="<conftest>")


@pytest.fixture
def settings(tmp_path):
    """落临时文件的 QSettings —— 测试不去碰开发机上的真实配置。"""
    from PySide6.QtCore import QSettings

    from ..settings_store import SettingsStore

    return SettingsStore(QSettings(str(tmp_path / "workbench.ini"),
                                   QSettings.Format.IniFormat))


def make_ctx(manifest, manifest_path, settings):
    """建一份 AppContext —— 夹具与测试自己造上下文时共用。"""
    from ..bridge.catalog import default_registry
    from ..bus import EventBus
    from ..context import AppContext
    from ..tasks import TaskRunner

    return AppContext(
        manifest=manifest,
        manifest_path=manifest_path,
        tools=default_registry(),
        bus=EventBus(),
        tasks=TaskRunner(),
        settings=settings,
    )


@pytest.fixture
def ctx(qt_app, manifest, settings, tmp_path):
    return make_ctx(manifest, tmp_path / "workbench.yaml", settings)


# ════════════════════════════════════════════════════════════
# case 建模模块（真清单、真示例模型）
# ════════════════════════════════════════════════════════════

def shipped_manifest():
    """仓库里那份真清单 —— 连同它的真实路径（`input` 相对它解析）。"""
    from ..config import default_manifest_path

    path = default_manifest_path()
    return load_manifest_text(path.read_text(encoding="utf-8"), source=str(path)), path


def _casemodel_window(qt_app, settings, *, with_input: bool):
    manifest, manifest_path = shipped_manifest()
    if not with_input:
        # 把 casemodel 的 input 抹掉 —— 得到「模型没打开」的初始状态，
        # 而不是伪造一份清单（那份清单会跟真清单漂移）。
        manifest = manifest.model_copy(deep=True)
        for spec in manifest.modules:
            if spec.id == "vms.casemodel":
                spec.input = ""
    window = make_window(qt_app, make_ctx(manifest, manifest_path, settings))
    return window, window.manager.module("vms.casemodel")


@pytest.fixture
def casemodel_window(qt_app, settings):
    """装着 case 建模模块的真窗口（清单里的 input 已载入）。"""
    window, _module = _casemodel_window(qt_app, settings, with_input=True)
    yield window
    window.manager.mark_all_clean()
    window.close()
    window.deleteLater()
    qt_app.processEvents()


@pytest.fixture
def casemodel(casemodel_window):
    """case 建模模块本身 —— 旧测试里的 `gui` 就是它。

    旧界面的窗口职责（菜单、状态栏、标题）现在一半归平台、一半归模块：
    `save_model` / `reanalyze` / `load` / `pages` / `editor` 都在模块上，
    状态栏与标签页标题要经 `casemodel_window` 看。
    """
    return casemodel_window.manager.module("vms.casemodel")


@pytest.fixture
def casemodel_empty(qt_app, settings):
    """没打开任何模型的 case 建模模块。"""
    window, module = _casemodel_window(qt_app, settings, with_input=False)
    yield module
    window.manager.mark_all_clean()
    window.close()
    window.deleteLater()
    qt_app.processEvents()


def type_into(editor_page, text: str) -> None:
    """模拟用户打字。

    别用 `editor_page.set_text()` —— 那是「载入文件」的语义（会标成与磁盘一致），
    用它测不出「用户改了东西」。
    """
    cursor = editor_page.editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.Start)
    cursor.insertText(text)


def load_into(module, target) -> None:
    """打开一份模型，且不带上一次的真实 case 列表。"""
    module.cases_path = None
    module.load(str(target))


def make_window(qt_app, ctx):
    """按 ctx 建主窗口（不 show）。测试与夹具共用。"""
    from ..app import _build_window_class

    return _build_window_class()(qt_app, ctx)


def menu_titles(window):
    """菜单栏上的一级标题 —— 去掉 & 助记符。"""
    return [action.text().replace("&", "").split("(")[0]
            for action in window.menuBar().actions()]


def menu_by_title(window, prefix: str):
    """按标题前缀取一个一级菜单。

    走窗口自己存的那份引用（`window.menu(title)`），而不是从菜单栏的 action
    反查 —— `QMenuBar.addMenu()` 返回的 QMenu 若没人持有，PySide 会连 C++ 对象
    一起回收，反查回来就是个死对象。
    """
    for title in window._menus:                       # noqa: SLF001
        if title.startswith(prefix):
            return window.menu(title)
    raise AssertionError(f"菜单栏上没有「{prefix}」：{menu_titles(window)}")


def entries(menu):
    """一个菜单（含其子菜单）里的全部动作。"""
    found = []
    for action in menu.actions():
        found.append(action)
        if action.menu() is not None:
            found.extend(entries(action.menu()))
    return found


def window_menu_entry(window, label: str):
    """在「窗口」菜单里找一条动作。

    模块清单现在平铺在窗口菜单下 —— 业务线不再占顶层菜单（否则每加一条线
    菜单栏就长一节），所以测试也得改到这儿来找。
    """
    for action in menu_by_title(window, "窗口").actions():
        if label in action.text():
            return action
    raise AssertionError(f"窗口菜单里没有「{label}」")


@pytest.fixture
def window(qt_app, ctx):
    win = make_window(qt_app, ctx)
    yield win
    win.manager.mark_all_clean()      # 否则 closeEvent 的确认框会挂住测试
    win.close()
    win.deleteLater()
    qt_app.processEvents()
