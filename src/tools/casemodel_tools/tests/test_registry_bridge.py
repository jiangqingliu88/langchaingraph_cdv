"""casemodel → 用例库 —— 属性空间落成可跑用例的那道桥。

钉三件事：
  1. **粒度**：一个属性取值点 = 一条用例，与 `run_uvm_tests` 严格 1:1；
  2. **优先级来自专题**（不是按名字猜的表），同一取值点取覆盖它的最高优先级；
  3. **名字不会静默撞车** —— 中文取值退化成下标而不是被抹成空串。
"""
from __future__ import annotations

from src.tools.casemodel_tools.api import run_uvm_tests
from src.tools.casemodel_tools.registry_bridge import (DEFAULT_PRIORITY, case_rows,
                                                       register_cases)

from .conftest import CPU, FC

CPU_TEXT = CPU.read_text(encoding="utf-8")
FC_TEXT = FC.read_text(encoding="utf-8")


class TestGranularity:
    def test_one_row_per_attribute_value(self):
        """**条数与 UVM_TEST 条数必须一致** —— 对不上就说明有覆盖点没落地。

        两处都是"一条 = 一个属性取值"。这条断言是那个 1:1 的守卫：任何一边
        改了粒度（比如这里按维度合并、那边按取值摊开），这里就红。
        """
        rows = case_rows(FC_TEXT, "fc")["cases"]
        assert len(rows) == run_uvm_tests(FC_TEXT)["count"]

    def test_one_row_per_attribute_value_for_the_themed_model(self):
        rows = case_rows(CPU_TEXT, "cpu")["cases"]
        assert len(rows) == run_uvm_tests(CPU_TEXT)["count"]

    def test_constraints_carry_the_attribute_combination(self):
        """`constraints` 这一列以前**永远是空的**（全仓库没人写过）—— 现在带上组合。"""
        rows = case_rows(FC_TEXT, "fc")["cases"]
        for r in rows:
            assert len(r["constraints"]) == 1
            c = r["constraints"][0]
            assert set(c) == {"dimension", "field", "value"}
            assert c["value"] is not None

    def test_coverage_bin_mirrors_the_existing_shape(self):
        """与用例库既有的 `rd_burst_len[16]` 同形 —— 别自创第三种写法。"""
        bins = {r["coverage_bin"] for r in case_rows(FC_TEXT, "fc")["cases"]}
        assert "D_ratio.反压比例[50]" in bins


class TestPriorityComesFromThemes:
    def test_dimension_takes_the_highest_priority_theme_covering_it(self):
        """`D_length` 被 P0 专题点名 → 它就是 P0，不是按名字猜出来的 P1。"""
        rows = {r["constraints"][0]["dimension"]: r
                for r in case_rows(CPU_TEXT, "cpu")["cases"]}
        assert rows["D_length"]["priority"] == "P0"
        assert rows["D_length"]["scenario"] == "TH-P0-CFG"      # 谁把它排进来的

    def test_higher_priority_wins_when_several_themes_cover_it(self):
        """`D_ratio` 同时被 P1（反压）和 P2（边界）覆盖 → 取 P1，更早该跑。"""
        rows = {r["constraints"][0]["dimension"]: r
                for r in case_rows(CPU_TEXT, "cpu")["cases"]}
        assert rows["D_ratio"]["priority"] == "P1"

    def test_every_priority_is_a_real_tier(self):
        """落到用例库的优先级必须是分级回归认得的 tier（P0..P3）。"""
        prio = {r["priority"] for r in case_rows(CPU_TEXT, "cpu")["cases"]}
        assert prio <= {"P0", "P1", "P2", "P3"}, prio

    def test_a_declared_tier_that_gets_no_cases_is_announced(self):
        """**声明的分级 ≠ 落地的分级。**

        一个取值点只归覆盖它的**最高**优先级专题，所以低优先级专题可能一条都
        拿不到 —— 模型里声明了 P2，落库却一条 P2 都没有。后果是**分级回归跑到
        那一级是空的，而 `EMPTY` 在门控里是拦下**。这条断言让它在建模阶段就吭声，
        而不是等到跑回归时对着"每级都空"反过来查模型。
        """
        out = case_rows(CPU_TEXT, "cpu")
        assert "P2" not in out["priority_counts"]
        assert any("P2" in n and "空" in n for n in out["notes"]), out["notes"]

    def test_priority_counts_are_reported(self):
        """落地的分级分布要能一眼看见 —— 全是 P0 就是个信号。"""
        counts = case_rows(CPU_TEXT, "cpu")["priority_counts"]
        assert counts and sum(counts.values()) == case_rows(CPU_TEXT, "cpu")["count"]
        assert counts.get("P0", 0) > 0


class TestNoThemesIsSaidOutLoud:
    """模型没声明专题时（示例 fc 就是）—— 不许假装有分层。"""

    def test_falls_back_to_the_default_and_records_it(self):
        out = case_rows(FC_TEXT, "fc")
        assert {r["priority"] for r in out["cases"]} == {DEFAULT_PRIORITY}
        assert any("themes" in n for n in out["notes"]), out["notes"]

    def test_uncovered_dimensions_are_listed_not_hidden(self):
        out = case_rows(FC_TEXT, "fc")
        assert out["uncovered_dimensions"], "没专题覆盖却一条都没报出来"


class TestNamesAreSafeAndUnique:
    def test_non_ascii_values_do_not_collapse(self):
        """`无/首拍/尾拍/持续` 四个中文取值 —— 名字必须四个，且都不是 `case`。

        用 `_safe_name` 直接抹的话这四个全会变成空串→`case`，四条撞成一个名字
        （静默丢三条）。所以非 ASCII 走下标 `v0/v1/...`。
        """
        names = [r["name"] for r in case_rows(FC_TEXT, "fc")["cases"]
                 if r["constraints"][0]["dimension"] == "D_mode"]
        assert len(names) == 4
        assert len(set(names)) == 4
        assert "case" not in names

    def test_multi_field_dimension_gets_a_field_discriminator(self):
        """`D_res` 有两个字段（并发数 / 总元素数）—— 同名取值必须能区分开。

        `并发数 1` 与 `总元素数 1` 不区分就是撞名，后写的覆盖先写的。
        """
        rows = [r for r in case_rows(FC_TEXT, "fc")["cases"]
                if r["constraints"][0]["dimension"] == "D_res"]
        assert len(rows) == len({r["name"] for r in rows}), "同维度内撞名了"

    def test_names_are_unique_across_the_whole_model(self):
        names = [r["name"] for r in case_rows(CPU_TEXT, "cpu")["cases"]]
        assert len(names) == len(set(names))

    def test_names_are_ascii_and_filesystem_safe(self):
        for r in case_rows(FC_TEXT, "fc")["cases"]:
            assert r["name"].isascii(), r["name"]
            assert r["name"] == r["name"].replace(" ", "")


class TestCap:
    def test_no_cap_by_default(self):
        out = case_rows(FC_TEXT, "fc")
        assert out["truncated"] is False and out["dropped"] == 0
        assert out["count"] == out["total_before_cap"]

    def test_cap_accounts_for_everything_it_drops(self):
        out = case_rows(CPU_TEXT, "cpu", max_cases=3)
        assert out["count"] == 3
        assert out["truncated"] is True
        assert out["dropped"] == out["total_before_cap"] - 3
        assert out["notes"], "截断了却没有任何说明"

    def test_cap_keeps_the_high_priorities_first(self):
        out = case_rows(CPU_TEXT, "cpu", max_cases=5)
        assert {r["priority"] for r in out["cases"]} == {"P0"}, \
            "截断没有先保住 P0"


def test_broken_model_returns_error_not_exception():
    out = case_rows("object: [1, 2]\ndimensions: []\n")
    assert "error" in out and out["cases"] == []


class TestRegistering:
    """落库 —— 写进去的必须能被读出来，且 `constraints` 不是空列。"""

    def test_rows_land_in_the_registry_with_constraints(self, tmp_path):
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry

        db = tmp_path / "tc.db"
        out = register_cases(FC_TEXT, "fc", db_path=str(db))
        assert out["registered"] == out["count"] > 0

        reg = TestcaseRegistry(db)
        try:
            rows = {r["name"]: r for r in reg.get_all()}
        finally:
            reg.close()
        assert rows, "一条都没写进去"
        for r in rows.values():
            assert r["constraints"], f"{r['name']} 的 constraints 还是空的"

    def test_the_reader_that_feeds_regression_yaml_sees_constraints(self, tmp_path):
        """**这条是这座桥的意义所在**：喂 `regression.yaml` 的那条读路径
        （`get_priority_order`）以前连 `constraints` 都不 SELECT。"""
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry

        db = tmp_path / "tc.db"
        register_cases(CPU_TEXT, "cpu", db_path=str(db))
        reg = TestcaseRegistry(db)
        try:
            order = reg.get_priority_order(stage=0, limit=50)
        finally:
            reg.close()
        assert order, "排序结果为空"
        assert all("constraints" in r for r in order)
        assert any(r["constraints"] for r in order)

    def test_priority_survives_the_round_trip(self, tmp_path):
        """P0 写进去、读出来还是 P0 —— 分级回归全靠这个 tag 分流。"""
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry

        db = tmp_path / "tc.db"
        register_cases(CPU_TEXT, "cpu", db_path=str(db))
        reg = TestcaseRegistry(db)
        try:
            rows = {r["name"]: r for r in reg.get_all()}
        finally:
            reg.close()
        p0 = [r for r in rows.values() if r["priority"] == "P0"]
        assert p0, "一条 P0 都没有 —— 专题的优先级没传到库里"
