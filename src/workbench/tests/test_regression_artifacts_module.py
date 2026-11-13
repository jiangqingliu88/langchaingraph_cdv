"""回归波形页 / 回归覆盖率页 —— **逐条用例校对**那两条路。

这两页和「回归状态」吃同一份数据（`flow.regression_status`），但问的是另一个问题：
不是"哪条挂了"，而是"这条的波形/覆盖率在哪，打开它"。所以这里钉的是：

  · 缺产物的用例**照样列出来**（挂死被看门狗掐掉的那条，往往正是一分覆盖率都
    没采到的那条 —— 少了产物本身就是校对要找的东西）；
  · 点一行打开的是**那一行**的产物（排序之后也一样，见 `_row_at` 的代理映射）；
  · 覆盖率页的「打开总覆盖率」走的是 `cov_actions`（与状态页同一个实现），
    优先用覆盖率阶段已经生成的那份报告。

页面按「真清单 + 真数据层」建，只把"取哪次运行"这一步换成直接喂目录 ——
`load(run_id)` 前半段是跑 `pipeline.detail` 查目录，那段路由运行服务的测试盯着。
"""
from __future__ import annotations

import json

import pytest
from PySide6.QtCore import Qt

WAVE_MODULE = "ops.regression_wave"
COV_MODULE = "ops.regression_coverage"


def _make_run(root):
    """造一个最小但形状正确的运行目录：三条用例，两条有产物、一条没有。"""
    run = root / "run_x"
    build = run / "regression_run" / "build_b1"

    def case(name, *, status="pass"):
        d = build / f"test_{name}"
        d.mkdir(parents=True)
        (d / "status.env").write_text(f"EMAN_BASE_STATUS={status}\n", encoding="utf-8")
        (d / "sim_vsim.log").write_text("# UVM_INFO x @ 0: y [T] ok\n", encoding="utf-8")
        return d

    both = case("t_both")
    (both / "waves").mkdir()
    (both / "waves" / "t_both.wlf").write_bytes(b"w" * 2048)
    (both / "cov" / "t_both").mkdir(parents=True)
    (both / "cov" / "t_both" / "questa.db").write_bytes(b"d" * 4096)

    wave_only = case("t_wave")
    (wave_only / "waves").mkdir()
    (wave_only / "waves" / "t_wave.wlf").write_bytes(b"w")

    case("t_plain")            # 没跑到底的那种：两样都没有
    return run


@pytest.fixture
def run_dir(tmp_path):
    return _make_run(tmp_path)


@pytest.fixture
def payload(run_dir):
    from src.workbench.api.flow.api import run_regression_status

    return run_regression_status(str(run_dir))


#: 模块 id → 类。用真清单里的 spec（标题/绑定/分组都来自于它），但类直接引 ——
#: 清单里 `factory` 是**字符串路径**，那是给注册表解析用的（见 conftest 里各页的写法）。
_FACTORIES = {
    WAVE_MODULE: "RegressionWaveModule",
    COV_MODULE: "RegressionCoverageModule",
}


def _page(module_id, qt_app, settings, run_dir, payload):
    """按真清单建一个页面，把数据直接喂进去（见模块文档）。"""
    from .conftest import make_ctx, shipped_manifest

    from ..modules.ops import regression_artifacts

    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == module_id)
    cls = getattr(regression_artifacts, _FACTORIES[module_id])
    module = cls(make_ctx(manifest, manifest_path, settings), spec)
    module.create_widget()
    module.run_dir = str(run_dir)          # 点开产物要用它拼相对路径
    module._fill(payload)
    return module


@pytest.fixture
def wave_page(qt_app, settings, run_dir, payload):
    module = _page(WAVE_MODULE, qt_app, settings, run_dir, payload)
    yield module
    module.content.deleteLater()
    qt_app.processEvents()


@pytest.fixture
def cov_page(qt_app, settings, run_dir, payload):
    module = _page(COV_MODULE, qt_app, settings, run_dir, payload)
    yield module
    module.content.deleteLater()
    qt_app.processEvents()


@pytest.fixture(params=[WAVE_MODULE, COV_MODULE])
def any_page(request, qt_app, settings, run_dir, payload):
    module = _page(request.param, qt_app, settings, run_dir, payload)
    yield module
    module.content.deleteLater()
    qt_app.processEvents()


# ── 数据与形状 ───────────────────────────────────────────────

def _column(key: str) -> int:
    from ..modules.ops.regression_artifacts import COLUMN_OF

    return COLUMN_OF[key]


def _row_of(module, name):
    for i in range(module.model.rowCount()):
        if str(module.model.data(module.model.index(i, 0))) == name:
            return module.model.index(i, 0)
    raise AssertionError(f"{name} 不在表里")


class TestBothPages:

    def test_every_case_is_listed(self, any_page):
        """三条都在 —— 缺产物的**不隐藏**（那恰恰是校对要找的）。"""
        names = {str(any_page.model.data(any_page.model.index(i, 0)))
                 for i in range(any_page.model.rowCount())}
        assert names == {"t_both", "t_wave", "t_plain"}

    def test_summary_counts_what_is_missing(self, any_page):
        """有几条有、几条没有 —— **缺的那几条是重点**，摘要里必须有。"""
        key = any_page.ARTIFACT_KEY
        total = len(any_page._rows)
        have = sum(1 for r in any_page._rows if r.get(key))
        text = any_page.summary_label.text()
        assert f"{total} 条用例" in text
        assert f"{have} 条有" in text
        assert f"{total - have} 条没有" in text

    def test_missing_artifact_cell_is_muted(self, any_page):
        """缺的那一格标灰 —— 它是"少了东西"，不是"这里没内容"。"""
        cells = any_page.model._cell_colors
        assert (_row_of(any_page, "t_plain").row(), _column("artifact")) in cells
        assert (_row_of(any_page, "t_both").row(), _column("artifact")) not in cells

    def test_missing_artifact_cell_explains_instead_of_blank(self, any_page):
        """没有产物时那一格**不留空** —— 空列会被读成"路径没加上/这页坏了"。

        填一句指向该动的那个开关（本轮没开这门业务 → 工具栏「仿真业务」）。
        """
        index = _row_of(any_page, "t_plain")
        cell = str(any_page.model.data(
            any_page.model.index(index.row(), _column("artifact"))))
        assert cell                                   # 不是空串
        assert "没开" in cell and "仿真业务" in cell
        assert any_page.ARTIFACT_NOUN in cell         # 覆盖率库 / 波形库

    def test_size_and_time_are_shown(self, any_page):
        index = _row_of(any_page, "t_both")
        size = str(any_page.model.data(
            any_page.model.index(index.row(), _column("size"))))
        time = str(any_page.model.data(
            any_page.model.index(index.row(), _column("time"))))
        assert size.endswith("KB") and time.count(":") == 2

    def test_path_is_shown_absolute(self, any_page):
        """「文件」列显示**绝对路径**，而且就是点开会用的那一个。

        这两件事必须一起成立：路径相对的时候，`QUrl.fromLocalFile()` 会**静默**
        什么都不打开 —— 显示得再好看，点下去没反应也没用。所以列里给的就是
        绝对路径本身，不是它的缩写。
        """
        from pathlib import Path

        row = _row_of(any_page, "t_both")
        shown = str(any_page.model.data(
            any_page.model.index(row.row(), _column("artifact"))))
        assert Path(shown).is_absolute(), shown
        assert shown.endswith("t_both.wlf" if any_page.ARTIFACT_KEY == "wave"
                              else "questa.db")
        # 显示 == 打开：`_artifact_path` 返回同一个字符串（不存在的才给空）
        assert any_page._artifact_path(any_page._rows[row.row()]) == shown

    def test_a_path_that_is_not_on_disk_is_still_shown_absolute(self, any_page):
        """数据层给了路径、文件却没落盘 —— 显示绝对路径，但**不**假装能打开。

        `_abs_path`（显示"它本该在哪"）与 `_artifact_path`（"现在真能打开"）
        必须分开：合成一个的话，要么把不存在的路径喂给桌面服务（点了没反应），
        要么把线索也一起吞掉（人不知道去哪找）。
        """
        from pathlib import Path

        mod = any_page
        row = dict(next(r for r in mod._rows if r["name"] == "t_both"))
        rel = "build_b1/test_ghost/waves/ghost.wlf"
        row[mod.ARTIFACT_KEY] = rel

        shown = mod._abs_path(row)
        assert shown and Path(shown).is_absolute()
        assert shown.endswith(rel.replace("/", "\\")) or shown.endswith(rel)
        # 文件不在 → 不能打开（这一份给空串）
        assert mod._artifact_path(row) == ""

    def test_raw_rows_keep_the_full_path(self, any_page):
        """`_rows` 里留的必须是原始完整路径 —— 点开要用。"""
        row = next(r for r in any_page._rows if r["name"] == "t_both")
        assert str(row[any_page.ARTIFACT_KEY]).endswith(
            "t_both.wlf" if any_page.ARTIFACT_KEY == "wave" else "questa.db")

    def test_row_lookup_survives_sorting(self, any_page):
        """表头排序之后点开必须还是那一行（视图挂的是排序代理）。"""
        any_page.table.sortByColumn(_column("name"), Qt.SortOrder.DescendingOrder)
        view = any_page.table.model()
        index = view.index(0, 0)
        assert any_page._row_at(index)["name"] == str(view.data(index))

    def test_notes_explain_when_nothing_has_the_artifact(self, any_page, tmp_path):
        """一条都没有时要说清是"没开这门业务"，不是"这页坏了"。"""
        from src.workbench.api.flow.api import run_regression_status

        empty = tmp_path / "no_artifacts"
        case = empty / "regression_run" / "build_b1" / "test_t1"
        case.mkdir(parents=True)
        (case / "status.env").write_text("EMAN_BASE_STATUS=pass\n", encoding="utf-8")

        any_page.run_dir = str(empty)
        any_page._fill(run_regression_status(str(empty)))

        assert any_page.summary_label.text().startswith("1 条用例，0 条有")
        assert "没开" in any_page.notes_label.text()


# ── 波形页 ──────────────────────────────────────────────────

class TestWavePage:

    def test_click_opens_that_cases_wave(self, wave_page, monkeypatch):
        from ..modules.ops import cov_actions

        opened = []
        monkeypatch.setattr(cov_actions, "open_wave",
                            lambda module, path, what="": opened.append(path))
        wave_page._on_cell_clicked(_row_of(wave_page, "t_wave"))
        assert opened and opened[0].endswith("t_wave.wlf")

    def test_missing_wave_is_explained_not_silent(self, wave_page, monkeypatch):
        said = []
        monkeypatch.setattr(wave_page.ctx, "status", said.append)
        wave_page._on_cell_clicked(_row_of(wave_page, "t_plain"))
        assert said and "没开" in said[0]

    def test_clicking_an_empty_area_does_nothing(self, wave_page, monkeypatch):
        from ..modules.ops import cov_actions

        opened = []
        monkeypatch.setattr(cov_actions, "open_wave",
                            lambda module, path, what="": opened.append(path))
        wave_page._on_cell_clicked(wave_page.model.index(-1, 0))
        assert opened == []


# ── 覆盖率页 ────────────────────────────────────────────────

class TestCoveragePage:

    def test_has_the_total_coverage_button(self, cov_page):
        assert cov_page.btn_total.text() == "打开总覆盖率报告"
        assert cov_page.btn_total.isEnabled()

    def test_click_opens_that_cases_coverage_in_visualizer(self, cov_page, monkeypatch):
        """点一行 → Visualizer（`-ucdbfile`），**不是**先摊成 HTML。

        覆盖率库是二进制，HTML 报告是拿它现生成的；而"这条用例到底漏了哪个 bin"
        要的是可下钻的交互视图，所以左键这条主路直接进 Visualizer。
        """
        from ..modules.ops import cov_actions

        opened = []
        monkeypatch.setattr(cov_actions, "open_case_coverage_visualizer",
                            lambda module, db: opened.append(db))
        cov_page._on_cell_clicked(_row_of(cov_page, "t_both"))
        assert opened and opened[0].endswith("questa.db")

    def test_the_report_is_still_one_menu_click_away(self, cov_page, monkeypatch):
        """HTML 报告没被拿掉，只是挪到右键 —— 整份结论那条路还得在。"""
        from ..modules.ops import cov_actions

        opened = []
        monkeypatch.setattr(cov_actions, "open_case_coverage",
                            lambda module, db: opened.append(db))
        cov_page._open_report(cov_page._row_at(_row_of(cov_page, "t_both")))
        assert opened and opened[0].endswith("questa.db")

    def test_total_button_goes_through_the_shared_action(self, cov_page, monkeypatch):
        """总覆盖率走 `cov_actions`（与状态页同一个实现）—— 不能各写一套。"""
        from ..modules.ops import cov_actions

        seen = []
        monkeypatch.setattr(cov_actions, "open_total_coverage",
                            lambda module, run_dir: seen.append(run_dir))
        cov_page.btn_total.click()
        assert seen and seen[0] == cov_page.run_dir

    def test_header_shows_the_total_numbers(self, cov_page, run_dir, payload):
        """页头要把总数摆出来 —— 不然还得跳到别的页去对账。"""
        cov = run_dir / "sim" / "coverage"
        cov.mkdir(parents=True)
        (cov / "coverage_result.json").write_text(
            json.dumps({"coverage": {"overall_pct": 89.2, "functional_pct": 51.7}}),
            encoding="utf-8")

        cov_page._fill(payload)             # 复位摘要
        cov_page._refresh_total()

        text = cov_page.summary_label.text()
        assert "总覆盖率 89.2%" in text and "功能 51.7%" in text

    def test_header_is_not_appended_twice(self, cov_page, run_dir, payload):
        """`_refresh_total` 反复调不该把数字叠起来（切来切去会调很多次）。"""
        cov = run_dir / "sim" / "coverage"
        cov.mkdir(parents=True)
        (cov / "coverage_result.json").write_text(
            json.dumps({"coverage": {"overall_pct": 89.2}}), encoding="utf-8")
        cov_page._fill(payload)

        cov_page._refresh_total()
        cov_page._refresh_total()

        assert cov_page.summary_label.text().count("总覆盖率") == 1


# ── cov_actions：三个页面共用的那两个动作 ──────────────────────

class _FakeModule:
    """只带 `cov_actions` 用得到的那几个钩子（测的是**分发**，不是真弹窗口）。"""

    def __init__(self, tools=None):
        self.said = []
        self.opened = []
        self.tools = tools or []
        self.calls = []

    def set_status(self, text):
        self.said.append(text)

    def run_tool(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return self.tools.pop(0) if self.tools else None

    def report_payload_error(self, payload):
        return bool((payload or {}).get("error"))


def _patch_open(monkeypatch, module):
    from ..modules.ops import cov_actions

    monkeypatch.setattr(cov_actions, "_open_path",
                        lambda m, path: module.opened.append(str(path)))


class TestCovActions:

    def test_prefers_the_report_the_agent_already_made(self, monkeypatch, tmp_path):
        """优先用覆盖率阶段留下的那份 —— 它已经在了、就是当时 agent 看的那一份。"""
        from ..modules.ops import cov_actions

        run = tmp_path / "run"
        (run / "sim" / "coverage" / "reports").mkdir(parents=True)
        report = run / "sim" / "coverage" / "reports" / "index.html"
        report.write_text("<html></html>", encoding="utf-8")

        module = _FakeModule(tools=[{"report": {"exists": True, "path": str(report)},
                                     "db": {"exists": True, "path": "x"}}])
        _patch_open(monkeypatch, module)
        cov_actions.open_total_coverage(module, str(run))

        assert module.opened == [str(report)]
        # 一份报告都不用现生成
        assert [c[0] for c in module.calls] == ["flow.run_coverage"]

    def test_builds_from_the_merged_db_when_there_is_no_report(self, monkeypatch,
                                                              tmp_path):
        from ..modules.ops import cov_actions

        db = tmp_path / "merged.ucdb"
        db.write_bytes(b"m")
        html = tmp_path / "out" / "index.html"
        module = _FakeModule(tools=[
            {"report": {"exists": False}, "db": {"exists": True, "path": str(db)}},
            {"status": "PASS", "html": str(html), "cached": False}])
        _patch_open(monkeypatch, module)

        cov_actions.open_total_coverage(module, str(tmp_path))

        names = [c[0] for c in module.calls]
        assert names == ["flow.run_coverage", "flow.coverage_report"]
        assert module.opened == [str(html)]

    def test_says_why_when_there_is_nothing(self, monkeypatch, tmp_path):
        from ..modules.ops import cov_actions

        module = _FakeModule(tools=[{"report": {"exists": False},
                                     "db": {"exists": False}}])
        _patch_open(monkeypatch, module)
        cov_actions.open_total_coverage(module, str(tmp_path))

        assert module.opened == []
        assert module.said and "没有总覆盖率产物" in module.said[0]

    def test_no_run_selected(self, monkeypatch):
        from ..modules.ops import cov_actions

        module = _FakeModule()
        _patch_open(monkeypatch, module)
        cov_actions.open_total_coverage(module, "")

        assert module.calls == []
        assert module.said and "先选一次运行" in module.said[0]

    def test_failed_report_falls_back_to_revealing_the_db(self, monkeypatch,
                                                          tmp_path):
        """报告生成不了（vcover 缺席之类）也要让人摸到库本身 —— 别让这一下白点。"""
        from ..modules.ops import cov_actions

        db = tmp_path / "case" / "questa.db"
        db.parent.mkdir()
        db.write_bytes(b"d")
        module = _FakeModule(tools=[{"status": "FAIL", "error": "找不到 vcover"}])
        _patch_open(monkeypatch, module)

        cov_actions.open_case_coverage(module, str(db))

        assert module.opened == [str(db.parent)]      # 退到目录
        assert any("找不到 vcover" in s for s in module.said)

    def test_case_coverage_without_a_db_explains_the_mode_switch(self, monkeypatch):
        from ..modules.ops import cov_actions

        module = _FakeModule()
        _patch_open(monkeypatch, module)
        cov_actions.open_case_coverage(module, "")

        assert module.calls == []
        assert module.said and "没开 `cov`" in module.said[0]
