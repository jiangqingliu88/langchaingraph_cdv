"""编辑器与高亮 —— `QPlainTextEdit` 及其 `QSyntaxHighlighter`。

两者是配套的：编辑器管文本与行号，高亮器管着色，词表由调用方传进来
（通用控件不该认识任何具体模型的键名）。
"""
from .highlighter import YamlHighlighter
from .yaml import LineNumberArea, YamlEditor

__all__ = ["YamlEditor", "LineNumberArea", "YamlHighlighter"]
