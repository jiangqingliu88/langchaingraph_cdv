"""生成层共享常量：模板根目录 / 文件头元数据 / 工具版本。

模板随工具走（仍在 `tool_uvm/templates`），不随分层移动；这里只是把
「路径从哪个文件算」收敛到一处，避免搬到 `generators/` 之后所有相对路径一起错。
"""
from __future__ import annotations

from pathlib import Path

from .render.jinja_renderer import COMPANY_TRADEMARK, COPYRIGHT_YEAR
from .render.region_injector import TOOL_VERSION

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "tool_uvm" / "templates"

__version__ = TOOL_VERSION

# ── 文件头元数据（base_templates/base_template.sv.j2 渲染用）──
DEFAULT_META = {
    "company": COMPANY_TRADEMARK,
    "rights": (f"Copyright (c) {COPYRIGHT_YEAR} {COMPANY_TRADEMARK}. All rights reserved. "
               "未经书面许可，禁止复制、修改、分发或用于商业用途。"),
    "author": "-",
    "email": "-",
}
