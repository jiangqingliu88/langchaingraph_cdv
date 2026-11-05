"""`python -m src.workbench [清单.yaml]` 的入口。

真正的参数解析在 `app.build_parser()` —— 放在那边是为了让
`python -m src.workbench --help` 与 `vagent gui run --help` 描述同一套参数。
"""
from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
