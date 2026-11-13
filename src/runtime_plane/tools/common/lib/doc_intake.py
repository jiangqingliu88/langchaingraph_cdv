"""文档入口 —— 把各种格式的输入统一读成文本，喂给前置分析。

## 为什么要有这一层

上游（CLI / GUI）原来直接 `Path(spec_file).read_text()` —— 那等于**只认纯文本**。
而规格的实际形态是多样的：`.md`、`.txt`、测试点 `.xlsx`、别人的 `.docx` 规格书、
`.pdf` 数据手册。**读不进来不等于"不支持"，但使用者不会知道** ——
所以这里对认不出的扩展名**明确报错并说清装什么**，不静默返回空串。

## 能力的边界要如实说

本环境只装了 `openpyxl`（xlsx）。`docx` / `pdf` 需要额外依赖 ——
报错信息里直接给可执行的 `pip install` 命令（本环境默认走清华源）。

**读进来的是文本，不是结构**：docx/pdf 转出来的文本仍然要靠前置分析
（LLM 或工具）去抽 design_name / interfaces / registers。这一层只负责
"把字节变成字符"，不负责"把字符变成结构"。
"""
from __future__ import annotations

from pathlib import Path

#: 纯文本类：stdlib 直接读
_TEXT_EXT = {".md", ".markdown", ".txt", ".rst", ".yaml", ".yml", ".json",
             ".csv", ".sv", ".v", ".svh", ".vh", ".tcl", ".log", ""}

#: 需要额外依赖的格式 → (包, 装它的命令)
_NEEDS_DEP = {
    ".xlsx": ("openpyxl", "pip install openpyxl"),
    ".xls": ("openpyxl", "pip install openpyxl"),
    ".docx": ("python-docx", "pip install python-docx"),
    ".doc": ("python-docx", "pip install python-docx"),
    ".pdf": ("pypdf", "pip install pypdf"),
}


class UnsupportedDocument(Exception):
    """读不进来的输入 —— 带上"装什么才能读"，别让人对着空串猜。"""


def read_document(path: str | Path) -> str:
    """任意支持的文档 → 文本。读不了就抛 `UnsupportedDocument`（**不返回空串**）。

    返回空串是更坏的选择：前置分析会把它当成"没有输入"，一路走到
    `design_name: dut` —— 一个不存在的设计，然后在很后面报一堆看不懂的错。
    """
    p = Path(path)
    if not p.exists():
        raise UnsupportedDocument(f"输入不存在：{p}")

    ext = p.suffix.lower()
    if ext in _TEXT_EXT:
        return p.read_text(encoding="utf-8", errors="replace")

    if ext in (".xlsx", ".xls"):
        try:
            import openpyxl
        except ImportError as e:
            raise UnsupportedDocument(
                f"读 {ext} 需要 openpyxl：{_NEEDS_DEP['.xlsx'][1]}（{e}）") from e
        wb = openpyxl.load_workbook(str(p), data_only=True, read_only=True)
        rows = []
        for ws in wb.worksheets:
            rows.append(f"## sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c) for c in row]
                if any(c.strip() for c in cells):
                    rows.append("\t".join(cells))
        wb.close()
        return "\n".join(rows)

    if ext in (".docx", ".doc"):
        try:
            import docx
        except ImportError as e:
            raise UnsupportedDocument(
                f"读 {ext} 需要 python-docx：{_NEEDS_DEP['.docx'][1]}"
                f"（本环境默认走清华源，见 memory: pip-use-tsinghua-mirror）"
                f"；原始错误：{e}") from e
        d = docx.Document(str(p))
        return "\n".join(par.text for par in d.paragraphs)

    if ext == ".pdf":
        try:
            import pypdf
        except ImportError as e:
            raise UnsupportedDocument(
                f"读 .pdf 需要 pypdf：{_NEEDS_DEP['.pdf'][1]}"
                f"（本环境默认走清华源）；原始错误：{e}") from e
        r = pypdf.PdfReader(str(p))
        return "\n".join((pg.extract_text() or "") for pg in r.pages)

    raise UnsupportedDocument(
        f"不认识的输入格式 {ext or '(无扩展名)'}：{p}\n"
        f"支持的纯文本类：{' '.join(sorted(e for e in _TEXT_EXT if e))}\n"
        f"需要依赖的：.xlsx(openpyxl，已装) / .docx(python-docx) / .pdf(pypdf)")


def supported_formats() -> dict:
    """给 CLI / GUI 列"能吃什么" —— 别让使用者靠试。"""
    return {"text": sorted(e for e in _TEXT_EXT if e),
            "with_deps": {e: cmd for e, (_pkg, cmd) in _NEEDS_DEP.items()}}
