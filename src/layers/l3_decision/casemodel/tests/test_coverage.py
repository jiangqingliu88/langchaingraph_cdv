"""**功能覆盖率方法学** —— case 模型的覆盖点 → 能编译的 SystemVerilog covergroup。

这一层要回答的不是"用例写全了没有"（那是 `analysis/coverage.py` 的事），而是
"**仿真打到了没有**"该怎么量。分母从 `field.value_points()` 来 —— 与
`run_uvm_tests` 同源，所以「激励撒了几个值」和「覆盖率收几个 bin」天然对得上。

三条纪律，各有一组用例钉住：
  1. **生成的 SV 必须能编译** —— 中文取值要投影成整型字面量（否则 `bins x = {首拍}`
     是语法错误），bin 名要合法且不重名；
  2. **对不上就要说出来** —— 空字段、解不出的 cross、超量的取值点，都进 `notes`，
     不静默少生成；
  3. **与 `run_uvm_tests` 分母同源** —— bin 数与取值点数一致。
"""
from __future__ import annotations


import re
from pathlib import Path

import pytest
import yaml

from src.layers.l3_decision.casemodel.api import (TOOL_COVERGROUPS, TOOL_NAMES, RUNNERS,
                                           run_coverage_plan, run_covergroups,
                                           run_uvm_tests)
from src.layers.l3_decision.casemodel.coverage import (MAX_BINS_PER_POINT, sv_ident,
                                                sv_value)

from .conftest import FC

FC_TEXT = FC.read_text(encoding="utf-8")

def _model(**over) -> str:
    base = {
        "version": "1", "object": "dut", "object_code": "DUT",
        "sub_objects": [{"id": "OBJ-01", "name": "功能", "code": "F1"}],
        "dimensions": [],
        "themes": [{"id": "TH-P0", "name": "功能", "priority": "P0"}],
    }
    base.update(over)
    return yaml.safe_dump(base, allow_unicode=True)


ENUM_DIM = {"id": "D_dir", "name": "方向",
            "fields": [{"name": "pwrite", "type": "enum", "values": [0, 1]}]}
RANGE_DIM = {"id": "D_addr", "name": "地址",
             "fields": [{"name": "paddr", "type": "range", "min": 0, "max": 255,
                         "boundary": ["0", "255"]}]}


# ════════════════════════════════════════════════════════════
# 接入面
# ════════════════════════════════════════════════════════════

class TestSurfaces:
    def test_not_in_the_agent_three_faces(self):
        """和 `run_uvm_tests` 一样是**给人用的**，不进 Agent 的三面名单。

        进 `TOOL_NAMES` 就得在 verify/casemodel 的 `tool_specs()` 与 langchain
        包装里各补一份，否则 `classes[name]` KeyError（`api.py` 那段注释记着）。
        """
        assert TOOL_COVERGROUPS not in TOOL_NAMES
        assert TOOL_COVERGROUPS not in RUNNERS

    def test_runners_stay_consistent_with_the_agent_faces(self):
        """`RUNNERS` 与 `TOOL_NAMES` 必须一致 —— 不一致就是三面里有个名字查不到。"""
        assert set(RUNNERS) == set(TOOL_NAMES)


# ════════════════════════════════════════════════════════════
# 方法学：模型 → 覆盖点
# ════════════════════════════════════════════════════════════

class TestMethodology:
    def test_field_becomes_a_coverpoint(self):
        p = run_covergroups(_model(dimensions=[ENUM_DIM]), "dut")
        assert p["coverpoint_count"] == 1
        assert p["coverpoints"][0]["signal"] == "pwrite"

    def test_each_value_point_becomes_a_bin(self):
        p = run_covergroups(_model(dimensions=[ENUM_DIM]), "dut")
        assert [b["value"] for b in p["coverpoints"][0]["bins"]] == [0, 1]

    def test_range_uses_the_declared_boundary_only(self):
        """range 型的分母是**声明的边界**，不是 min..max 全展开（那会是 256 个 bin）。"""
        p = run_covergroups(_model(dimensions=[RANGE_DIM]), "dut")
        assert [b["value"] for b in p["coverpoints"][0]["bins"]] == [0, 255]
        assert all(b["boundary"] for b in p["coverpoints"][0]["bins"])

    def test_cover_bins_give_the_bin_names(self):
        dim = {"id": "D_mode", "name": "模式",
               "fields": [{"name": "mode", "type": "enum", "values": ["首拍", "尾拍"],
                           "cover_bins": ["first_beat", "last_beat"]}]}
        p = run_covergroups(_model(dimensions=[dim]), "dut")
        assert [b["name"] for b in p["coverpoints"][0]["bins"]] == \
            ["first_beat", "last_beat"]

    def test_crossable_pairs_become_crosses(self):
        p = run_covergroups(_model(dimensions=[ENUM_DIM, RANGE_DIM],
                                   cross_matrix={"D_dir × D_addr": "required"}), "dut")
        assert p["cross_count"] == 1
        assert p["crosses"][0]["signals"] == ["pwrite", "paddr"]

    def test_forbidden_pair_is_not_a_cross(self):
        """`forbidden` 是**禁止**组合 —— 生成 cross 正好把语义搞反。"""
        p = run_covergroups(_model(dimensions=[ENUM_DIM, RANGE_DIM],
                                   cross_matrix={"D_dir × D_addr": "forbidden"}), "dut")
        assert p["cross_count"] == 0

    def test_one_covergroup_holds_every_coverpoint(self):
        """cross 要求两个 coverpoint 同作用域 —— 所以合一个，不是每维度一个。"""
        p = run_covergroups(_model(dimensions=[ENUM_DIM, RANGE_DIM]), "dut")
        assert p["covergroup_code"].count("covergroup ") == 1
        assert p["covergroup"] == "cg_dut"


# ════════════════════════════════════════════════════════════
# 纪律一：生成的 SV 必须能编译
# ════════════════════════════════════════════════════════════

class TestGeneratedSvIsCompilable:
    def test_non_ascii_value_is_projected_not_pasted(self):
        """中文取值直接写进 `bins x = {首拍}` 是**语法错误** —— 必须投影成下标。

        语义不丢：原取值以注释留在旁边。bin 名也一样不能是中文（SV 标识符只允许
        `[A-Za-z0-9_$]`），所以它跟着投影成 `b_<下标>`。
        """
        dim = {"id": "D_mode", "name": "模式",
               "fields": [{"name": "mode", "type": "enum", "values": ["首拍", "尾拍"]}]}
        code = run_covergroups(_model(dimensions=[dim]), "dut")["covergroup_code"]
        lcode = [ln.split("//")[0] for ln in code.splitlines()]   # 剥掉注释看代码
        joined = "\n".join(lcode)
        assert "首拍" not in joined and "尾拍" not in joined
        assert "bins b_0 = {0};" in joined
        assert "首拍" in code                          # 注释保住了语义

    def test_a_fully_non_ascii_value_still_gets_a_legal_bin_name(self):
        """`首拍` 折成标识符是**空串** —— 退到下标，不能留下 `bins b_ = {0};`。"""
        dim = {"id": "D_mode", "name": "模式",
               "fields": [{"name": "mode", "type": "enum", "values": ["首拍"]}]}
        code = run_covergroups(_model(dimensions=[dim]), "dut")["covergroup_code"]
        assert "bins b_0 = {0};" in code
        assert "b_ " not in code and "b_=" not in code

    def test_bin_names_are_unique_within_a_coverpoint(self):
        """bins 重名编译不过 —— 两种来源（作者的命名 / 推导的命名）都可能撞。"""
        dim = {"id": "D_x", "name": "X",
               "fields": [{"name": "x", "type": "enum", "values": ["1", "01"],
                           "cover_bins": ["same", "same"]}]}
        bins = run_covergroups(_model(dimensions=[dim]), "dut")["coverpoints"][0]["bins"]
        assert len({b["name"] for b in bins}) == len(bins)

    @pytest.mark.parametrize("raw", ["首拍", "a b", "", "1abc", "a-b", "模式2"])
    def test_ident_is_never_empty_and_never_starts_with_a_digit(self, raw):
        got = sv_ident(raw)
        assert got and re.fullmatch(r"[A-Za-z_$][\w$]*", got), got

    @pytest.mark.parametrize("token,index", [("0", 5), ("255", 5), ("首拍", 3),
                                             ("", 7), ("x", 2)])
    def test_sv_value_is_always_an_int(self, token, index):
        assert isinstance(sv_value(token, index), int)

    def test_sv_value_matches_run_uvm_tests_int_value(self):
        """同一个取值，激励侧（`int_value`）与度量侧（bin）**必须是同一个数**。

        对不上，闭环就断在中间：sequence 打的不是 covergroup 收的那个值。
        """
        dim = {"id": "D_mode", "name": "模式",
               "fields": [{"name": "mode", "type": "enum", "values": ["首拍", "尾拍"]}]}
        text = _model(dimensions=[dim])
        bins = run_covergroups(text, "dut")["coverpoints"][0]["bins"]
        tests = run_uvm_tests(text)["tests"]
        assert [b["value"] for b in bins] == [t["int_value"] for t in tests]


# ════════════════════════════════════════════════════════════
# 纪律二：对不上就说出来
# ════════════════════════════════════════════════════════════

class TestNotesExplainWhatWasDropped:
    def test_field_without_value_points_is_noted_and_skipped(self):
        dim = {"id": "D_e", "name": "E", "fields": [{"name": "e", "type": "range"}]}
        p = run_covergroups(_model(dimensions=[dim]), "dut")
        assert p["coverpoint_count"] == 0
        assert any("取值点" in n for n in p["notes"])

    def test_dimension_without_fields_is_noted(self):
        p = run_covergroups(_model(dimensions=[{"id": "D_n", "name": "空"}]), "dut")
        assert p["coverpoint_count"] == 0
        assert any("字段" in n and "D_n" in n for n in p["notes"])

    def test_unresolvable_cross_is_noted(self):
        p = run_covergroups(_model(dimensions=[ENUM_DIM],
                                   cross_matrix={"D_dir × D_ghost": "optional"}), "dut")
        assert p["cross_count"] == 0
        assert any("D_ghost" in n for n in p["notes"])

    def test_too_many_value_points_are_truncated_and_noted(self):
        """bin 太多会把 vcover 的命中率稀释到没意义 —— 截断并记账，不静默。"""
        vals = [str(i) for i in range(MAX_BINS_PER_POINT + 10)]
        dim = {"id": "D_big", "name": "大",
               "fields": [{"name": "big", "type": "enum", "values": vals}]}
        p = run_covergroups(_model(dimensions=[dim]), "dut")
        assert p["bin_count"] == MAX_BINS_PER_POINT
        assert any("截断" in n for n in p["notes"])


# ════════════════════════════════════════════════════════════
# 显式覆盖仓：仓不必是取值点
# ════════════════════════════════════════════════════════════

def _one_field(field: dict, dim_id: str = "D_x") -> str:
    return _model(dimensions=[{"id": dim_id, "name": "X", "fields": [field]}])


class TestExplicitBins:
    """`cover_bins` 的对象形式 —— 一批真实模型逼出来的能力。

    `queue_level` 的 0-32 要分 `empty/low/mid/high/near_full/full` 六档，那是
    **值域的一个划分**，不是"取了哪几个点"。用取值点（`boundary`）表达不出来：
    六个档里三个是区间。
    """

    def _bins(self, cover_bins: list) -> list:
        text = _one_field({"name": "q", "type": "range", "min": 0, "max": 32,
                           "cover_bins": cover_bins})
        return run_covergroups(text, "dut")["coverpoints"][0]["bins"]

    def test_range_bin(self):
        assert self._bins([{"name": "low", "range": [1, 7]}])[0]["literal"] == "[1:7]"

    def test_at_is_a_single_value(self):
        assert self._bins([{"name": "empty", "at": 0}])[0]["literal"] == "0"

    def test_values_is_a_set(self):
        assert self._bins([{"name": "s", "values": [0, 7, 8]}])[0]["literal"] == "0,7,8"

    def test_from_without_to_is_open_ended(self):
        """`{[33:$]}` —— 上界省略是**有意义的**（33 及以上）。

        错当成 0 会写成 `{[33:0]}`：一个空区间，**编译能过但永远不命中** ——
        非法仓就成了摆设。这是实测踩出来的。
        """
        assert self._bins([{"name": "over", "from": 33}])[0]["literal"] == "[33:$]"

    def test_from_to_is_a_closed_range(self):
        assert self._bins([{"name": "r", "from": 2, "to": 9}])[0]["literal"] == "[2:9]"

    def test_explicit_bins_win_over_value_points(self):
        """两者都有时以显式仓为准，但**要说出来**（不能默默丢掉另一半）。"""
        text = _one_field({"name": "q", "type": "range", "min": 0, "max": 32,
                           "boundary": ["0", "32"],
                           "cover_bins": [{"name": "low", "range": [1, 7]}]})
        out = run_covergroups(text, "dut")
        assert [b["name"] for b in out["coverpoints"][0]["bins"]] == ["low"]
        assert any("以显式仓为准" in n for n in out["notes"])

    def test_a_bin_without_content_is_noted_not_silently_dropped(self):
        """写了个仓但没说是哪些值 —— **记账**，不能静默丢掉那一条。

        这里字段本身也没有取值点（range 不给 min/max/boundary；否则会退化成
        "min/max 两个端点"），于是两边都空 ⇒ 干脆不出覆盖点。**要能看出是为什么**。
        """
        text = _one_field({"name": "q", "type": "range",
                           "cover_bins": [{"name": "nowhere"}]})
        out = run_covergroups(text, "dut")
        assert out["coverpoint_count"] == 0
        assert any("nowhere" in n for n in out["notes"])
        assert any("一条都没解析出来" in n for n in out["notes"])

    def test_duplicate_bin_names_are_dropped_with_a_note(self):
        """`bins` 重定义编译不过 —— 重复的丢掉并记账，不能两个都写出去。"""
        text = _one_field({"name": "q", "type": "range", "min": 0, "max": 32,
                           "cover_bins": [{"name": "a", "at": 1},
                                          {"name": "a", "at": 2}]})
        out = run_covergroups(text, "dut")
        assert out["coverpoints"][0]["bin_count"] == 1
        assert any("重复" in n for n in out["notes"])


class TestIllegalBins:
    """非法仓 —— 命中即报错。这是"约束与覆盖点脱节"那条坑的解药。"""

    def test_field_level_illegal_bin(self):
        text = _one_field({"name": "q", "type": "range", "min": 0, "max": 32,
                           "cover_bins": [{"name": "full", "at": 32}],
                           "cover_illegal": [{"name": "illegal_over", "from": 33}]})
        cp = run_covergroups(text, "dut")["coverpoints"][0]
        assert [b["name"] for b in cp["illegal_bins"]] == ["illegal_over"]
        assert cp["illegal_bins"][0]["illegal"] is True

    def test_it_renders_as_illegal_bins(self):
        text = _one_field({"name": "q", "type": "range", "min": 0, "max": 32,
                           "cover_illegal": [{"name": "bad", "from": 33}]})
        code = run_covergroups(text, "dut")["covergroup_code"]
        assert "illegal_bins bad = {[33:$]};" in code

    def test_illegal_and_normal_bins_share_one_namespace(self):
        """同名的非法仓与正常仓在一个 coverpoint 里重名 —— 也是编译错误。"""
        text = _one_field({"name": "q", "type": "range", "min": 0, "max": 32,
                           "cover_bins": [{"name": "same", "at": 1}],
                           "cover_illegal": [{"name": "same", "from": 33}]})
        out = run_covergroups(text, "dut")
        cp = out["coverpoints"][0]
        assert cp["bin_count"] == 1 and cp["illegal_bin_count"] == 0
        assert any("重复" in n for n in out["notes"])


# ════════════════════════════════════════════════════════════
# 过滤交叉（binsof）与交叉级 illegal
# ════════════════════════════════════════════════════════════

TWO_DIMS = [
    {"id": "D_type", "name": "类型",
     "fields": [{"name": "instr_type", "type": "enum",
                 "values": ["MAC", "VECTOR", "SCALAR", "DMA"],
                 "cover_bins": ["mac", "vector", "scalar", "dma"]}]},
    {"id": "D_unit", "name": "单元",
     "fields": [{"name": "issue_unit", "type": "enum",
                 "values": ["MAC", "VECTOR", "SCALAR", "DMA"],
                 "cover_bins": ["mac", "vector", "scalar", "dma"]}]},
]


class TestFilteredCrosses:
    """`cross_matrix` 的对象形式 —— 只交叉有意义的那几对。

    全交叉的仓数按乘积涨（4×4 = 16），而关心的往往四五个。更要紧的是**非法组合**：
    不写 `illegal` 的话，`mac` 指令发到 `dma` 单元会被当成一个正常状态统计 ——
    那等于在说它合法。
    """

    def _cross(self, decl):
        text = _model(dimensions=TWO_DIMS, cross_matrix={"D_type×D_unit": decl})
        out = run_covergroups(text, "dut")
        return (out["crosses"][0] if out["crosses"] else {}), out

    def test_bare_level_declaration_is_still_a_full_cross(self):
        cx, _ = self._cross("required")
        assert cx["bin_count"] == 0            # 没有 bins ⇒ 渲染成裸 cross

    def test_filtered_bins_are_kept_in_order(self):
        cx, _ = self._cross({
            "level": "required",
            "bins": [{"name": "mac_to_mac", "when": {"instr_type": "mac",
                                                     "issue_unit": "mac"}},
                     {"name": "vec_to_vec", "when": {"instr_type": "vector",
                                                     "issue_unit": "vector"}}]})
        assert [b["name"] for b in cx["bins"]] == ["mac_to_mac", "vec_to_vec"]

    def test_illegal_cross_bin_is_marked(self):
        cx, _ = self._cross({
            "level": "required",
            "illegal": [{"name": "mac_to_dma", "when": {"instr_type": "mac",
                                                        "issue_unit": "dma"}}]})
        assert cx["bins"][0]["illegal"] is True

    def test_it_renders_with_binsof(self):
        text = _model(dimensions=TWO_DIMS, cross_matrix={"D_type×D_unit": {
            "level": "required",
            "bins": [{"name": "mac_to_mac", "when": {"instr_type": "mac",
                                                     "issue_unit": "mac"}}],
            "illegal": [{"name": "mac_to_dma", "when": {"instr_type": "mac",
                                                        "issue_unit": "dma"}}]}})
        code = run_covergroups(text, "dut")["covergroup_code"]
        assert ("bins mac_to_mac = binsof(cp_instr_type.mac) "
                "&& binsof(cp_issue_unit.mac);") in code
        assert ("illegal_bins mac_to_dma = binsof(cp_instr_type.mac) "
                "&& binsof(cp_issue_unit.dma);") in code
        # illegal 排在正常仓之后 —— 读起来顺，且与文档的写法一致
        assert code.index("mac_to_mac") < code.index("mac_to_dma")

    def test_the_value_token_works_too_not_only_the_bin_name(self):
        """作者可能写 bin 名（`mac`）也可能直接写取值（`MAC`）—— 两个都认。"""
        cx, _ = self._cross({
            "level": "required",
            "bins": [{"name": "x", "when": {"instr_type": "MAC",
                                            "issue_unit": "mac"}}]})
        assert cx["bins"][0]["when"] == {"instr_type": "mac", "issue_unit": "mac"}

    def test_an_unknown_bin_name_is_noted_and_skipped(self):
        """**不能默默生成一个 `binsof(cp.nope)`** —— 要么编译不过，要么（更糟）
        被当合法语法收下却永远不命中。"""
        cx, out = self._cross({
            "level": "required",
            "bins": [{"name": "x", "when": {"instr_type": "nope",
                                            "issue_unit": "mac"}}]})
        assert cx["bins"] == []
        assert any("nope" in n for n in out["notes"])

    def test_a_missing_side_is_noted(self):
        cx, out = self._cross({
            "level": "required",
            "bins": [{"name": "x", "when": {"instr_type": "mac"}}]})
        assert cx["bins"] == []
        assert any("那一侧" in n for n in out["notes"])


class TestTraceabilityIds:
    """`cover_id` / `requirement` —— 需求追溯矩阵的两个端点。

    生成器派生的名字是 `cp_<信号名>`（给编译器），文档里引用的是 `CP_NPU_xxx`
    （给人）。两者都要有，不能拿一个当另一个。
    """

    def test_both_ids_ride_along_in_the_declaration(self):
        text = _one_field({"name": "q", "type": "range", "min": 0, "max": 32,
                           "cover_id": "CP_NPU_QUEUE_001",
                           "requirement": "REQ-NPU-001",
                           "cover_bins": [{"name": "full", "at": 32}]})
        cp = run_covergroups(text, "dut")["coverpoints"][0]
        assert cp["cover_id"] == "CP_NPU_QUEUE_001"
        assert cp["requirement"] == "REQ-NPU-001"

    def test_absent_ids_stay_empty_not_invented(self):
        text = _one_field({"name": "q", "type": "range", "min": 0, "max": 32,
                           "cover_bins": [{"name": "full", "at": 32}]})
        cp = run_covergroups(text, "dut")["coverpoints"][0]
        assert cp["cover_id"] == "" and cp["requirement"] == ""
