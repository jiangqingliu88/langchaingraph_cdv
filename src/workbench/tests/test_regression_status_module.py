"""回归状态页 —— 用例状态表 + 状态徽章。

用**真清单 + 临时目录里真形状的回归产物**，不打桩：这条路径同时固定了三件事
—— 绑定 `flow.regression_status` 通、`run_regression_status` 的返回形状是界面
真正吃得下的那种、状态的**来源分级**（记录 vs 推断）没被搞混。

**刻意不依赖 `output_jiang_*`**：那是被 gitignore 的用户产物，不是稳定夹具。
测试自己造一个最小但形状正确的回归目录。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

MODULE_ID = "ops.regression_status"

#: 一条 UVM_INFO 的实测形状（QuestaSim）：消息行带 `@ <时间>`，
#: 而结尾的汇总行是 `UVM_ERROR :    4`（没有 `@`）—— 数据层就靠这个区分。
_UVM_INFO = "# UVM_INFO f:/q/uvm_root.svh(392) @ 0: reporter [RELNOTES] blah"


def _make_regression_dir(root):
    """造一个最小但形状正确的回归产物目录。"""
    reg = root / "regression_run"
    build = reg / "build_b1"

    def case(name, *, status=None, log_lines=None, sim_time=None):
        d = build / f"test_{name}"
        d.mkdir(parents=True)
        (d / "sim.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        if status is not None:
            (d / "status.env").write_text(f"EMAN_BASE_STATUS={status}\n", encoding="utf-8")
        if log_lines is not None:
            (d / "sim_vsim.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        if sim_time is not None:
            (d / "sim_time.log").write_text(f"SIM_TIME={sim_time}\n", encoding="utf-8")
        return d

    # t_pass 这轮开着波形 + 覆盖率两门业务（点开要用的那种产物）
    passed = case("t_pass", status="pass", sim_time=3,
                  log_lines=[_UVM_INFO, _UVM_INFO])
    (passed / "waves").mkdir()
    (passed / "waves" / "t_pass.wlf").write_bytes(b"wlf")
    cov = passed / "cov" / "t_pass"
    cov.mkdir(parents=True)
    (cov / "questa.db").write_bytes(b"db")
    (cov / "t_pass.data").write_bytes(b"data")      # 副产品，不是库

    case("t_fail_uvm", status="fail", sim_time=5,
         log_lines=[_UVM_INFO, "# UVM_ERROR f.svh(1) @ 10: uvm_test_top [E] boom"])
    case("t_fail_assert", status="fail", sim_time=2,
         log_lines=["# ** Error: tb.sv(9): Assertion a_check failed"])
    # 既没有 status.env 也没有日志 —— 没证据，**不等于通过**
    case("t_noev")
    return reg


@pytest.fixture
def payload(tmp_path):
    from src.workbench.api.flow.api import run_regression_status

    return run_regression_status(str(_make_regression_dir(tmp_path)))


@pytest.fixture
def module(qt_app, settings, payload):
    from .conftest import make_ctx, shipped_manifest
    from ..modules.ops.regression_status import RegressionStatusModule

    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == MODULE_ID)
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = RegressionStatusModule(ctx, spec)
    widget = mod.create_widget()
    mod._fill(payload)
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


# ════════════════════════════════════════════════════════════
# 数据层
# ════════════════════════════════════════════════════════════

class TestData:
    def test_rows_and_stats(self, payload):
        assert payload["stats"] == {"total": 4, "pass": 1, "fail": 2, "unknown": 1}

    def test_status_comes_from_status_env(self, payload):
        """框架判完落盘的 status.env 是**一手来源**，优先于其它。"""
        row = next(r for r in payload["rows"] if r["name"] == "t_pass")
        assert row["status"] == "pass"
        assert row["status_source"] == "status_env"

    def test_failure_is_classified_by_log_evidence(self, payload):
        """failed 再分类 —— ExecMan 的 Status 列就是这个语义，且只依据数出来的事实。"""
        uvm = next(r for r in payload["rows"] if r["name"] == "t_fail_uvm")
        asrt = next(r for r in payload["rows"] if r["name"] == "t_fail_assert")
        assert uvm["detail"] == "uvm_error" and uvm["uvm_error"] == 1
        assert asrt["detail"] == "assertion_error" and asrt["assert_error"] == 1

    def test_uvm_tally_line_is_not_counted_as_a_message(self, payload):
        """汇总行 `UVM_ERROR :    4` 没有 `@`，不能被当成一条消息。"""
        row = next(r for r in payload["rows"] if r["name"] == "t_pass")
        assert row["uvm_info"] == 2          # 只有那两条真消息
        assert row["uvm_error"] == "-"       # 汇总行不算

    def test_no_evidence_is_unknown_not_pass(self, payload):
        """没有日志 = 没证据。**不能算通过** —— 这是本页最容易出错的地方。"""
        row = next(r for r in payload["rows"] if r["name"] == "t_noev")
        assert row["status"] == "unknown"
        assert row["status_source"] == "none"

    def test_sim_time_is_read(self, payload):
        assert next(r for r in payload["rows"] if r["name"] == "t_pass")["sim_time"] == 3


class TestDerivedStatus:
    """没有 status.env / report.json 时退回「从日志推断」—— 必须**标出来**。"""

    def test_derived_is_labelled(self, tmp_path):
        from src.workbench.api.flow.api import run_regression_status

        reg = _make_regression_dir(tmp_path)
        d = reg / "build_b1" / "test_t_old"
        d.mkdir(parents=True)
        (d / "sim_vsim.log").write_text(_UVM_INFO + "\n", encoding="utf-8")

        payload = run_regression_status(str(tmp_path))
        row = next(r for r in payload["rows"] if r["name"] == "t_old")
        assert row["status"] == "pass"
        assert row["status_source"] == "derived_from_log"
        assert payload["sources"]["derived_rows"] >= 1

    def test_nonzero_tally_counts_as_failure(self, tmp_path):
        """配置里那条判定规则同源：日志出现非零 UVM_ERROR 计数 → fail。"""
        from src.workbench.api.flow.api import run_regression_status

        reg = _make_regression_dir(tmp_path)
        d = reg / "build_b1" / "test_t_tally"
        d.mkdir(parents=True)
        (d / "sim_vsim.log").write_text("UVM_ERROR :    4\n", encoding="utf-8")

        row = next(r for r in run_regression_status(str(tmp_path))["rows"]
                   if r["name"] == "t_tally")
        assert row["status"] == "fail"


# ════════════════════════════════════════════════════════════
# 界面
# ════════════════════════════════════════════════════════════

class TestModule:
    def test_renders_all_rows(self, module):
        assert module.model.rowCount() == 4
        assert module.model.columnCount() == len(
            __import__("src.workbench.modules.ops.regression_status",
                       fromlist=["COLUMNS"]).COLUMNS)

    def test_summary_counts(self, module):
        text = module.summary_label.text()
        assert "共 4 个用例" in text and "通过 1" in text
        assert "失败 2" in text and "无结论 1" in text

    def test_status_column_holds_detail_not_raw_status(self, module):
        """状态列存的是 `detail`（分类后），不是粗粒度的 pass/fail。

        徽章**文案**由 delegate 画（`assert_err` 那种短标签），模型里存的是 detail ——
        两件事，别混。这里查模型；标签映射单独查。
        """
        shown = {str(module.model.data(module.model.index(r, 1)))
                 for r in range(module.model.rowCount())}
        assert shown == {"pass", "assertion_error", "uvm_error", "unknown"}

    def test_badge_labels_cover_every_detail(self, module):
        """每个可能出现的 detail 都有徽章文案与底色 —— 否则会掉进兜底色。"""
        from ..modules.ops.regression_status import BADGE_COLORS, BADGE_LABELS

        shown = {str(module.model.data(module.model.index(r, 1)))
                 for r in range(module.model.rowCount())}
        assert shown <= set(BADGE_LABELS), "有 detail 没有徽章文案"
        assert shown <= set(BADGE_COLORS), "有 detail 没有徽章底色"

    def test_sources_are_surfaced(self, module):
        """**数据的来源情况必须显示出来** —— 「这页凭什么可信」是它的全部价值。

        这组夹具里每条都有 status.env，所以没有「推断」；但缺 report.json 这件事
        照样要写在页面上（否则用户会把「没有报告」误当成「一切正常」）。
        """
        text = module.notes_label.text()
        assert "report.json" in text

    def test_empty_payload_clears(self, module):
        module._fill({"rows": [], "stats": {}, "sources": {}, "notes": []})
        assert module.model.rowCount() == 0
        assert module.summary_label.text() == "没有回归用例"

    def test_wave_and_coverage_columns_are_shown_short(self, module):
        """两列显示的是**短路径**（相对用例目录）—— 完整路径撑满列、尾部反被截。"""
        assert str(module.model.data(_row_of(module, "t_pass", "wave"))) == \
            "waves/t_pass.wlf"
        assert str(module.model.data(_row_of(module, "t_pass", "cov"))) == \
            "cov/t_pass/questa.db"
        # 而 `_rows` 里留的是**完整路径**（点开要用，见 `_case_wave_path`）
        raw = _raw_row_of(module, "t_pass")["wave"]
        assert raw != "waves/t_pass.wlf" and raw.endswith("t_pass.wlf")

    def test_missing_wave_and_coverage_cells_explain_instead_of_blank(self, module):
        """没有产物的那两格**不留空** —— 填一句说明，不是空串。

        空列会被读成"路径没加上 / 这页坏了"；真实原因是这轮没开那门仿真业务。
        列窄会截断，悬停看全句（`RowsModel` 的 tooltip 就是完整文本）。
        """
        wave = str(module.model.data(_row_of(module, "t_fail_uvm", "wave")))
        cov = str(module.model.data(_row_of(module, "t_fail_uvm", "cov")))
        assert "没开" in wave and "波形" in wave
        assert "没开" in cov and "覆盖率" in cov


def _column(key: str) -> int:
    from ..modules.ops.regression_status import COLUMN_INDEX

    return COLUMN_INDEX[key]


def _row_of(module, name: str, column: str = "name"):
    """按用例名取一个视图坐标 —— 行的顺序来自目录名排序，不写死下标。"""
    for i in range(module.model.rowCount()):
        if str(module.model.data(module.model.index(i, 0))) == name:
            return module.model.index(i, _column(column))
    raise AssertionError(f"{name} 不在表里")


def _raw_row_of(module, name: str) -> dict:
    return next(r for r in module._rows if r["name"] == name)


class TestTotalCoverageButton:
    """页头那个「打开总覆盖率报告」—— 逐条结论在这张表里，**整个环境**的在那边。

    看这张表的人下一个问题往往就是"那总的覆盖了多少"。给个按钮，别让他去翻左树。
    """

    def test_button_exists(self, module):
        assert module.btn_total_coverage.text() == "打开总覆盖率报告"

    def test_button_goes_through_the_shared_action(self, module, monkeypatch):
        """与「回归覆盖率」页走的是**同一个实现**（`cov_actions`）—— 不能各写一套。"""
        from ..modules.ops import cov_actions

        seen = []
        monkeypatch.setattr(cov_actions, "open_total_coverage",
                            lambda m, run_dir: seen.append(run_dir))
        module.run_dir = "D:/run/x"
        module.btn_total_coverage.click()
        assert seen == ["D:/run/x"]


class TestClickOpensTheArtifacts:
    """点一下就打开 —— 人工校对那条路。

    这一页的价值不止"告诉我哪条挂了"，还有"让我自己看一眼"。所以：

        点 波形列   → 直接开波形
        点 覆盖率列 → 直接开覆盖率**报告**（库是二进制，人看不了）
        点 用例名   → 这轮**实际产出的**那门业务（一个就开，两个让你选）

    判断依据是**磁盘上有没有产物**，不是工具栏下拉当前选什么 —— 那次运行用的是
    当时的选择，之后下拉可能早换了。
    """

    def _wire(self, module, monkeypatch):
        """把三条"打开"的动作换成记录器 —— 测的是**分发**，不是真的弹窗口。"""
        opened = {"wave": [], "cov": [], "log": []}
        monkeypatch.setattr(module, "_open_case_wave",
                            lambda row: opened["wave"].append(row.get("name")))
        monkeypatch.setattr(module, "_open_case_coverage",
                            lambda row: opened["cov"].append(row.get("name")))
        monkeypatch.setattr(module, "_open_case_log",
                            lambda row: opened["log"].append(row.get("name")))
        return opened

    def test_clicking_a_wave_cell_opens_that_wave(self, module, monkeypatch):
        opened = self._wire(module, monkeypatch)
        module._on_cell_clicked(_row_of(module, "t_pass", "wave"))
        assert opened["wave"] == ["t_pass"]

    def test_clicking_a_coverage_cell_opens_the_report(self, module, monkeypatch):
        opened = self._wire(module, monkeypatch)
        module._on_cell_clicked(_row_of(module, "t_pass", "cov"))
        assert opened["cov"] == ["t_pass"]

    def test_clicking_a_middle_column_does_nothing(self, module, monkeypatch):
        """只有那三格是入口 —— 点"耗时"弹窗口会让人措手不及。"""
        opened = self._wire(module, monkeypatch)
        module._on_cell_clicked(_row_of(module, "t_pass", "sim_time"))
        assert opened == {"wave": [], "cov": [], "log": []}

    def test_case_name_opens_the_only_artifact_produced(self, module, monkeypatch):
        opened = self._wire(module, monkeypatch)
        row = dict(_raw_row_of(module, "t_pass"))
        row["cov"] = ""                    # 这轮只开了波形
        module._open_case_artifact(row)
        assert opened["wave"] == ["t_pass"] and opened["cov"] == []

    def test_case_name_explains_when_nothing_was_produced(self, module, monkeypatch):
        """两门业务都没产物时要说清原因 —— 不能点了没反应。"""
        opened = self._wire(module, monkeypatch)
        said = []
        monkeypatch.setattr(module.ctx, "status", said.append)

        module._open_case_artifact({"name": "t_x", "wave": "", "cov": ""})

        assert opened == {"wave": [], "cov": [], "log": []}
        assert said and "没产出" in said[0]

    def test_double_click_cancels_the_pending_single_click(self, module, monkeypatch):
        """双击看日志**不该**顺带把业务窗口也开了（双击必然先送一次单击）。"""
        opened = self._wire(module, monkeypatch)
        row = dict(_raw_row_of(module, "t_pass"))
        row["cov"] = ""
        module._defer_click(lambda: module._open_case_artifact(row))
        module._on_row_activated(_row_of(module, "t_pass"))

        assert opened["log"] == ["t_pass"]
        assert opened["wave"] == [], "双击之后挂起的单击动作还执行了"


class TestRowLookupSurvivesSorting:
    """表头排序之后，点开必须还是**那一行**。

    视图挂的是 `SortProxy`，排序后视图行号与数据行号不再一一对应。直接拿
    `index.row()` 去索引 `_rows`，会稳定地打开**另一条**用例的日志/波形 ——
    点开的是别人的数据，比点不开坏得多。这条原来藏着，因为只有双击一条路。
    """

    def test_row_at_maps_through_the_sort_proxy(self, module):
        from PySide6.QtCore import Qt

        module.table.sortByColumn(_column("name"), Qt.SortOrder.DescendingOrder)
        view = module.table.model()                 # SortProxy
        index = view.index(0, _column("name"))
        name = str(view.data(index))
        assert module._row_at(index)["name"] == name

    def test_display_rows_stay_aligned_with_raw_rows(self, module):
        """显示那份和原始那份顺序必须一致 —— `_row_at` 靠这个对应关系取数据。"""
        assert [r["name"] for r in module._rows] == [
            str(module.model.data(module.model.index(i, 0)))
            for i in range(module.model.rowCount())]


# ════════════════════════════════════════════════════════════
# 清单与绑定
# ════════════════════════════════════════════════════════════

class TestManifest:
    def test_bound_in_shipped_manifest(self):
        from .conftest import shipped_manifest

        manifest, _ = shipped_manifest()
        spec = next((s for s in manifest.modules if s.id == MODULE_ID), None)
        assert spec is not None, "清单里没有 ops.regression_status"
        assert spec.group == "ops"            # 挂在「编译与回归」下
        assert spec.tool.name == "flow.regression_status"

    def test_binding_is_pure(self):
        """纯读绑定 —— 切标签页不该弹确认。"""
        from ..bridge.catalog import by_name

        binding = by_name("flow.regression_status")
        assert binding is not None
        assert binding.kind == "json"
        assert binding.pure is True
