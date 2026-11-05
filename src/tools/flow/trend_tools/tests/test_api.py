"""`run_trend` 的契约。

钉四件事：
  · 三类阶段（build / loop / test）各自算对进度值，并按量纲分到两组序列；
  · 某阶段某轮没数据 → **那条线从有数据的轮次才起笔**（不拿 0 冒充）；
  · 失败（没路径 / 文件不在 / YAML 坏 / 顶层非映射）→ `{"error"}`，不抛；
  · 没声明的阶段 id → `unresolved` 记账，不丢其它轮。
"""
from __future__ import annotations

from pathlib import Path

from src.tools.flow.trend_tools import run_trend

GOOD = """\
project: demo
stages:
  - {id: compile_agent, title: "编译 agent", kind: build}
  - {id: sim_loop, title: "sim_loop 循环", kind: loop}
  - {id: p0, title: "P0 test", kind: test}
  - {id: p3, title: "P3 test", kind: test}
rounds:
  - round: 1
    compile_agent: {build: 3}
    sim_loop: {coverage: 62.0}
    p0: {passed: 2, total: 6}
  - round: 2
    compile_agent: {build: 5}
    sim_loop: {coverage: 74.0}
    p0: {passed: 5, total: 6}
    p3: {passed: 1, total: 3}
"""


def _write(tmp_path: Path, text: str) -> str:
    target = tmp_path / "trend.yaml"
    target.write_text(text, encoding="utf-8")
    return str(target)


class TestShape:
    def test_top_level_keys(self, tmp_path):
        result = run_trend(_write(tmp_path, GOOD))
        assert set(result) == {"project", "stages", "rounds", "build_series",
                               "test_series", "summary", "unresolved", "counts"}
        assert result["project"] == "demo"
        assert result["rounds"] == [1, 2]

    def test_series_split_by_kind(self, tmp_path):
        result = run_trend(_write(tmp_path, GOOD))
        # 横坐标 = 阶段，一条线 = 一个量
        assert [s["id"] for s in result["build_series"]] == ["builds", "cases"]
        # sim_loop 只有 coverage（没有 iterations）→ 次数面板里没有它；
        # 各档通过率才是百分比面板
        assert [s["id"] for s in result["test_series"]] == ["p0", "p3"]

    def test_build_points_are_raw_counts(self, tmp_path):
        """x = 阶段序号（compile_agent 是第 1 个），y = 累计 build 数。"""
        result = run_trend(_write(tmp_path, GOOD))
        assert result["build_series"][0]["points"] == [[1, 5]]

    def test_loop_without_iterations_is_not_plotted(self, tmp_path):
        """次数面板画的是 loop 的**迭代数**；GOOD 里 sim_loop 只给了 coverage
        （百分比），所以它既不在次数面板、也不再进百分比面板。"""
        result = run_trend(_write(tmp_path, GOOD))
        assert "loop" not in [s["id"] for s in result["build_series"]]
        assert "sim_loop" not in [s["id"] for s in result["test_series"]]

    def test_test_points_are_pass_rate(self, tmp_path):
        """x = 该档在 stages 里的次序（p0 是第 3 个），y = 通过率 %。"""
        result = run_trend(_write(tmp_path, GOOD))
        p0 = next(s for s in result["test_series"] if s["id"] == "p0")
        assert p0["points"] == [[3, 83.3]]


class TestLateStart:
    def test_stage_without_early_data_starts_later(self, tmp_path):
        """p3 第 1 轮没数据 —— 它的线只有第 2 轮那一个点，不是从 0 起。"""
        result = run_trend(_write(tmp_path, GOOD))
        p3 = next(s for s in result["test_series"] if s["id"] == "p3")
        assert p3["points"] == [[4, 33.3]]

    def test_summary_keeps_stageless_rows(self, tmp_path):
        """汇总表按 stages 顺序出行，没数据的阶段也在（value 空）。"""
        result = run_trend(_write(tmp_path, GOOD))
        assert [r["stage"] for r in result["summary"]] == \
            ["compile_agent", "sim_loop", "p0", "p3"]


class TestSummaryAndCounts:
    def test_latest_values(self, tmp_path):
        result = run_trend(_write(tmp_path, GOOD))
        by_id = {r["stage"]: r for r in result["summary"]}
        assert by_id["compile_agent"]["value"] == "5"          # 最新 build 数
        assert by_id["sim_loop"]["value"] == "74.0%"           # 最新覆盖率
        assert by_id["p0"]["passed"] == "5" and by_id["p0"]["total"] == "6"
        assert by_id["p0"]["value"] == "83.3%"                 # 最新值 = 图上那条线

    def test_counts(self, tmp_path):
        result = run_trend(_write(tmp_path, GOOD))
        assert result["counts"] == {"rounds": 2, "builds_total": 5}


class TestDanglingStage:
    def test_unknown_stage_is_recorded_not_dropped(self, tmp_path):
        text = GOOD + "  - round: 3\n    p0: {passed: 6, total: 6}\n    typo_stage: {build: 9}\n"
        result = run_trend(_write(tmp_path, text))
        assert {"round": 3, "stage": "typo_stage"} in result["unresolved"]
        # 同一轮里声明过的阶段照常入账
        assert result["rounds"] == [1, 2, 3]
        p0 = next(s for s in result["test_series"] if s["id"] == "p0")
        assert p0["points"][-1] == [3, 100.0]


class TestFailureIsLoud:
    def test_empty_path(self):
        assert "error" in run_trend("")

    def test_missing_file(self):
        result = run_trend("does/not/exist.yaml")
        assert "error" in result and "找不到" in result["error"]

    def test_directory_instead_of_file(self, tmp_path):
        assert "error" in run_trend(str(tmp_path))

    def test_broken_yaml(self, tmp_path):
        assert "error" in run_trend(_write(tmp_path, "stages: [unclosed\n"))

    def test_top_level_not_a_mapping(self, tmp_path):
        result = run_trend(_write(tmp_path, "- a\n- b\n"))
        assert "error" in result and "映射" in result["error"]

    def test_no_stages(self, tmp_path):
        result = run_trend(_write(tmp_path, "project: p\nrounds: []\n"))
        assert "error" in result and "stages" in result["error"]

    def test_never_raises(self):
        for bad in ("", "nope.yaml", "\x00"):
            assert isinstance(run_trend(bad), dict)


def test_shipped_example_loads():
    """仓库里那份示例要能读进来 —— 它是清单默认指向的数据源。"""
    from src.tools.flow.trend_tools.tests import __file__ as pkg_file
    example = Path(pkg_file).resolve().parents[5] / "config" / "trend" / "trend.yaml"
    result = run_trend(str(example))
    assert "error" not in result, result
    assert result["counts"]["rounds"] == 4
    assert result["counts"]["builds_total"] > 0
    # 次数面板（build/case/loop）+ 百分比面板（各档通过率）
    assert [s["id"] for s in result["build_series"]] == ["builds", "cases", "loop"]
    assert [s["id"] for s in result["test_series"]] == ["base", "p0", "p1", "p2", "p3"]
