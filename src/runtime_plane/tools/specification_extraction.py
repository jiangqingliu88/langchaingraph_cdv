"""Runtime 读取 RTL，只做有限事实提取；不推测设计意图。

这是 Runtime 工具适配点，不调用 Agent。内置轻量端口扫描仅支持常见单行
端口声明；复杂 SystemVerilog 应通过 parser callable 注入现有完整解析器。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

_PORT = re.compile(
    r"^\s*(input|output|inout)\b\s*(?:wire|logic|reg)?\s*"
    r"(?:signed|unsigned)?\s*(\[[^\]]+\])?\s*([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)


def read_rtl(source: str | Path) -> str:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8", errors="strict")
    if not isinstance(source, str):
        raise TypeError("source 必须是 RTL 文本或路径")
    if "\n" not in source:
        try:
            if Path(source).is_file():
                return Path(source).read_text(encoding="utf-8", errors="strict")
        except OSError:
            pass
    return source


def extract_rtl_facts(source: str | Path, parser: Callable[[str], dict[str, Any]] | None = None) -> dict[str, Any]:
    text = read_rtl(source)
    if parser is not None:
        return parser(text)
    # 轻量回退只扫声明，不把块注释/行注释里的示例端口当成真实绑定。
    clean_text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    clean_text = re.sub(r"//[^\n]*", "", clean_text)
    ports = [
        {"direction": match.group(1), "range": match.group(2) or "", "name": match.group(3)}
        for match in _PORT.finditer(clean_text)
    ]
    return {
        "schema": "rtl_surface_facts_v1",
        "ports": ports,
        "capabilities": "single_line_port_subset",
        "semantic_validation": False,
    }


__all__ = ["extract_rtl_facts", "read_rtl"]
