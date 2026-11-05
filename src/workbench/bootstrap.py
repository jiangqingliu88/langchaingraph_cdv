"""启动前的前置检查 —— 目前只有一条：PySide6 在不在。

PySide6 是**可选依赖**（`pip install -e .[gui]`）：纯 CLI 用法不需要它，
没必要让每次安装都拖上 Qt。所以缺失时要给一段能照着做的提示，而不是
甩一串 ImportError traceback。这与 `casemodel_tools/cli.py::cmd_gui`
的既有约定一致：**消息进 stderr，退出码 2**。
"""
from __future__ import annotations

import sys
from typing import Optional

INSTALL_HINT = (
    "GUI 需要 PySide6，当前环境没有装：\n"
    "  {exc}\n\n"
    "装法：pip install -e .[gui]　　或　　pip install PySide6\n"
    "（纯 CLI 用法 check / analyze / generate 不需要它）"
)


def require_pyside6() -> Optional[int]:
    """能 import PySide6 就返回 None，否则打印提示并返回退出码 2。

    返回 None 而不是 0：调用方写 `if (code := require_pyside6()): return code`
    时不会把「可用」误判成「失败」—— 0 是假值，None 也是假值，两者都表示
    「继续」，但 None 更清楚地表达「没有退出码」。用 0 会让人以为它是个码。
    """
    try:
        import PySide6  # noqa: F401
    except ImportError as exc:
        print(INSTALL_HINT.format(exc=exc), file=sys.stderr)
        return 2
    return None
