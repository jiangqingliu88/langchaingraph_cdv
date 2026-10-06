"""YAML 语法高亮 —— 工程工具那味儿的一半靠它。

用 QSyntaxHighlighter（Qt 自带的增量高亮器）：它只重画改动的块，不用整篇重解析，
所以几千行的模型文件敲字也不卡。

**这是启发式的，不是 YAML 解析器**：正则认不出多行标量（`|` / `>`）、
也分不清引号里的冒号。刻意不引 YAML 依赖 —— 高亮是「看着舒服」的辅助，
不该因此让编辑器对畸形输入变脆。

**词表是参数**（`skeleton_keys` / `enum_values`）：哪些键算「骨架」、哪些值算
「枚举」是**领域知识**，不该写死在通用控件里。case 模型把它的六层结构传进来；
别的模块传自己的（不传就是不认任何词表，只有基础 YAML 高亮）。

配色从 `theme` 取，所以换主题时高亮跟着变（调用 `rebuild()` + `rehighlight()`）。
"""
from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from ..theme import palette as theme

#: 键名的形态 —— 允许中文（模型的键名有中文注释式的写法）
_KEY = r"(?<![&*])([A-Za-z_一-鿿][\w一-鿿.\-]*)\s*:"


class YamlHighlighter(QSyntaxHighlighter):
    """给 YAML 上色。

    `skeleton_keys` 会被加粗（让人一眼看出文档结构），`enum_values` 用枚举色
    （写错时颜色不对，顺手就是提示）。两个都留空时只做基础 YAML 高亮。
    """

    def __init__(self, document, *, skeleton_keys: Sequence[str] = (),
                 enum_values: Sequence[str] = ()) -> None:
        super().__init__(document)
        self._skeleton = tuple(skeleton_keys)
        self._enums = tuple(enum_values)
        self._rules: List[Tuple[QRegularExpression, QTextCharFormat]] = []
        self.pair_fmt = QTextCharFormat()
        self.rebuild()

    # ── 规则 ──

    def rebuild(self) -> None:
        """按当前主题重建规则集 —— 切主题后调用。"""
        p = theme.current()
        self._rules = []

        def fmt(color: str, *, bold=False, italic=False) -> QTextCharFormat:
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            if italic:
                f.setFontItalic(True)
            return f

        self.pair_fmt = fmt(p.muted)                    # 引号/冒号等成对符号
        enum_fmt = fmt(p.syn_enum)
        meta_fmt = fmt(p.syn_meta, bold=True)
        key_fmt = fmt(p.syn_key)

        # 顺序有讲究：后加的会覆盖先加的（Qt 把格式叠加上去），
        # 所以「注释」必须放最后 —— 注释里的 `key: value` 不该被当成键值高亮。
        self._rules += [
            # 字符串（单/双引号各一条；贪婪匹配到行尾，够用）
            (QRegularExpression(r'"[^"\\]*(?:\\.[^"\\]*)*"'), fmt(p.syn_string)),
            (QRegularExpression(r"'[^']*'"), fmt(p.syn_string)),
            # 锚点 / 别名
            (QRegularExpression(r"[&*][A-Za-z_][\w-]*"), fmt(p.syn_anchor)),
            # 数字（含负数与小数）
            (QRegularExpression(r"(?<![\w.-])-?\d+(?:\.\d+)?(?![\w.])"),
             fmt(p.syn_number)),
            # 布尔 / 空
            (QRegularExpression(r"\b(?:true|false|null|yes|no|on|off|~)\b",
                                QRegularExpression.PatternOption.CaseInsensitiveOption),
             fmt(p.syn_bool)),
            (QRegularExpression(r"\bCHECK-[A-Z][A-Z0-9_]*\b"), enum_fmt),
            (QRegularExpression(r"[★✓✗]"), enum_fmt),
            # 列表项 / 文档分隔符
            (QRegularExpression(r"^\s*-\s"), fmt(p.syn_marker)),
            (QRegularExpression(r"^---\s*$|^\.\.\.\s*$"), fmt(p.syn_marker)),
            (QRegularExpression(_KEY), key_fmt),
            # 注释放最后，覆盖上面所有规则
            (QRegularExpression(r"#[^\n]*"), fmt(p.syn_comment, italic=True)),
        ]

        # 词表相关的两条**只在词表非空时**加：空词表会拼出 `(?:)` 这种
        # 匹配空串的正则，在每个位置都命中一次 —— 白费工夫且可能干扰相邻格式。
        if self._enums:
            # 从长到短排，免得 `linkage` 被更短的某个词先吃掉
            pattern = "|".join(re.escape(v) for v in
                               sorted(self._enums, key=len, reverse=True))
            self._rules.insert(-2, (QRegularExpression(r"\b(?:" + pattern + r")\b"),
                                    enum_fmt))
        if self._skeleton:
            pattern = "|".join(re.escape(k) for k in self._skeleton)
            # 骨架键在普通键之后、注释之前 —— 加粗要盖过普通键色
            self._rules.insert(-1, (QRegularExpression(
                r"(?m)^\s*(?:" + pattern + r")\s*:"), meta_fmt))

    # ── Qt 回调 ──

    def highlightBlock(self, text: str) -> None:
        for pattern, char_format in self._rules:
            iterator = pattern.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(),
                               char_format)
