"""通用控件 —— 行表模型、表格助手、横幅、控制台。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from ..ui.banner import Banner, PermanentNote
from ..ui.models import CENTER, LEFT, RIGHT, RowsModel, SortProxy
from ..ui import table_helpers

COLUMNS = (("name", "名字", 100, LEFT), ("count", "数量", 60, RIGHT))


class TestRowsModel:
    def test_reads_dicts_objects_and_tuples(self, qt_app):
        model = RowsModel(COLUMNS)

        class Row:
            name, count = "obj", 3

        model.set_rows([{"name": "dict", "count": 1}, Row(), ("tuple", 2)])
        texts = [model.data(model.index(r, 0)) for r in range(3)]
        assert texts == ["dict", "obj", "tuple"]
        assert model.data(model.index(0, 1)) == "1"

    def test_headers_use_the_second_column_field(self, qt_app):
        model = RowsModel(COLUMNS)
        assert model.headerData(1, Qt.Orientation.Horizontal) == "数量"

    def test_missing_key_is_empty_not_an_error(self, qt_app):
        model = RowsModel(COLUMNS)
        model.set_rows([{"name": "only-name"}])
        assert model.data(model.index(0, 1)) == ""

    def test_foreground_comes_from_row_and_cell_colors(self, qt_app):
        model = RowsModel(COLUMNS)
        red, blue = QColor("red"), QColor("blue")
        model.set_rows([{"name": "a", "count": 1}, {"name": "b", "count": 2}],
                       row_colors={0: red}, cell_colors={(1, 1): blue})
        assert model.data(model.index(0, 0), Qt.ItemDataRole.ForegroundRole) == red
        assert model.data(model.index(1, 1), Qt.ItemDataRole.ForegroundRole) == blue
        assert model.data(model.index(1, 0), Qt.ItemDataRole.ForegroundRole) is None

    def test_rows_property_returns_a_copy(self, qt_app):
        model = RowsModel(COLUMNS)
        model.set_rows([{"name": "a"}])
        model.rows.clear()
        assert model.rowCount() == 1

    def test_row_at_out_of_range_is_none(self, qt_app):
        model = RowsModel(COLUMNS)
        assert model.row_at(5) is None


class TestSortProxy:
    def test_numeric_columns_sort_by_value_not_text(self, qt_app):
        """'10' 排在 '9' 后面 —— 按字符串比会反过来。"""
        model = RowsModel(COLUMNS)
        model.set_rows([{"name": "b", "count": 9}, {"name": "a", "count": 10}])
        proxy = SortProxy()
        proxy.setSourceModel(model)
        proxy.sort(1, Qt.SortOrder.AscendingOrder)
        assert proxy.data(proxy.index(0, 1)) == "9"

    def test_non_scalar_userrole_falls_back_to_display(self, qt_app):
        """case 表把整个对象塞在 UserRole 里 —— 拿对象比 size 是没意义的。"""

        class WeirdModel(RowsModel):
            def data(self, index, role=Qt.ItemDataRole.DisplayRole):
                if role == Qt.ItemDataRole.UserRole:
                    return object()          # 非标量，代理该忽略它
                return super().data(index, role)

        model = WeirdModel((("k", "键", 50, CENTER),))
        model.set_rows([{"k": "b"}, {"k": "a"}])
        proxy = SortProxy()
        proxy.setSourceModel(model)
        proxy.sort(0, Qt.SortOrder.AscendingOrder)
        assert proxy.data(proxy.index(0, 0)) == "a"


class TestTableHelpers:
    @staticmethod
    def _table(qt_app):
        model = RowsModel(COLUMNS)
        view = table_helpers.configure_table(None, model)
        return model, view

    def test_model_is_wrapped_in_a_proxy(self, qt_app):
        model, view = self._table(qt_app)
        assert isinstance(view.model(), SortProxy)
        assert table_helpers.source_model(view) is model

    def test_fresh_table_is_in_original_order(self, qt_app):
        """打开就是「按第一列排好的」会盖掉原始行序（严重度、生成顺序）。"""
        model, view = self._table(qt_app)
        model.set_rows([{"name": "z", "count": 1}, {"name": "a", "count": 2}])
        assert view.model().data(view.model().index(0, 0)) == "z"
        assert view.horizontalHeader().sortIndicatorSection() == -1

    def test_source_index_maps_through_the_proxy(self, qt_app):
        """排序之后 view 的行号 ≠ 源模型的行号 —— 取原始对象必须先映射。"""
        model, view = self._table(qt_app)
        model.set_rows([{"name": "z", "count": 1}, {"name": "a", "count": 2}])
        view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        view_index = view.model().index(0, 0)
        assert view.model().data(view_index) == "a"
        source_row = table_helpers.source_index(view, view_index).row()
        assert model.row_at(source_row) == {"name": "a", "count": 2}

    def test_clear_table_empties_the_source_model(self, qt_app):
        model, view = self._table(qt_app)
        model.set_rows([{"name": "a", "count": 1}])
        table_helpers.clear_table(view)
        assert model.rowCount() == 0

    def test_row_text_joins_with_tabs(self, qt_app):
        model, view = self._table(qt_app)
        model.set_rows([{"name": "a", "count": 7}])
        assert table_helpers.row_text(view, 0) == "a\t7"


class TestBanner:
    def test_show_then_clear_also_clears_the_text(self, qt_app):
        """只隐藏不清文本，下次会读到陈旧内容 —— 出现过「修好了还显示旧错误」。"""
        banner = Banner()
        banner.show_message("出错了", "error")
        assert banner.is_showing and banner.kind == "error"
        banner.clear_message()
        assert not banner.is_showing
        assert banner.text() == ""

    def test_empty_message_is_equivalent_to_clear(self, qt_app):
        banner = Banner()
        banner.show_message("x", "warning")
        banner.show_message("")
        assert banner.text() == "" and not banner.is_showing

    def test_unknown_kind_falls_back_to_info(self, qt_app):
        banner = Banner()
        banner.show_message("x", "purple")
        assert banner.kind == "info"

    def test_permanent_note_cannot_be_cleared(self, qt_app):
        note = PermanentNote("演示数据", "warning")
        note.clear_message()
        assert note.is_showing


class TestConsole:
    def test_level_filter_replays_existing_lines(self, qt_app):
        """切到「只看 error」时要能回看刚才那屏里的红行，而不是只对以后生效。"""
        from ..ui.console import ConsolePanel

        console = ConsolePanel()
        console.append("普通信息", "info")
        console.append("出问题了", "error")
        console.set_min_level("error")
        visible = console.view.toPlainText()
        assert "出问题了" in visible
        assert "普通信息" not in visible

    def test_clear_drops_the_kept_lines(self, qt_app):
        from ..ui.console import ConsolePanel

        console = ConsolePanel()
        console.append("x", "info")
        console.clear_log()
        assert console.lines() == []
        assert console.view.toPlainText() == ""

    def test_appending_a_multiline_block_keeps_every_line(self, qt_app):
        from ..ui.console import ConsolePanel

        console = ConsolePanel()
        console.append("第一行\n第二行", "error")
        assert len(console.lines()) == 2
