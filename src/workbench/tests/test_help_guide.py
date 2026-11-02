"""帮助 → 使用指南：内容必须覆盖"输入 / 怎么跑 / 输出 / 怎么看"。

指南不是装饰 —— 它和产品走散时（比如命令改了名、目录改了位置）测试要红。
"""
from __future__ import annotations

import pytest


class TestGuideContent:
    def test_covers_the_four_questions(self):
        from ..help_guide import GUIDE_HTML, REQUIRED_TOPICS

        for topic in REQUIRED_TOPICS:
            assert topic in GUIDE_HTML, f"指南缺少：{topic}"

    def test_mentions_both_business_lines(self):
        from ..help_guide import GUIDE_HTML

        assert "IP 团队" in GUIDE_HTML and "SoC 团队" in GUIDE_HTML
        assert "ip_release_v1" in GUIDE_HTML
        # 覆盖率分账是两条业务线的核心纪律，别在指南里漏掉
        assert "分账" in GUIDE_HTML

    def test_states_the_honest_boundaries(self):
        from ..help_guide import GUIDE_HTML

        assert "BLOCKED_EDA_MISSING" in GUIDE_HTML
        assert "None ≠ False" in GUIDE_HTML
        assert "measured: false" in GUIDE_HTML


class TestGuideDialog:
    def test_builds_and_renders_the_guide(self, qt_app):
        from ..help_guide import GUIDE_TITLE, UserGuideDialog

        dialog = UserGuideDialog()
        try:
            assert dialog.windowTitle() == GUIDE_TITLE
            text = dialog.view.toPlainText()
            for piece in ("输入材料", "怎么跑", "输出在哪", "怎么看"):
                assert piece in text, piece
        finally:
            dialog.deleteLater()
            qt_app.processEvents()

    def test_help_menu_exposes_it(self, window):
        from .conftest import menu_by_title

        help_menu = menu_by_title(window, "帮助")
        texts = [a.text() for a in help_menu.actions()]
        assert any("使用指南" in t for t in texts), texts
        assert any("关于本工作台" in t for t in texts), texts
