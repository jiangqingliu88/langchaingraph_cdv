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

from src.tools.generation.casemodel_tools.api import (TOOL_COVERGROUPS, TOOL_NAMES, RUNNERS,
                                           run_coverage_plan, run_covergroups,
                                           run_uvm_tests)
from src.tools.generation.casemodel_tools.coverage import (MAX_BINS_PER_POINT, sv_ident,
                                                sv_value)

from .conftest import FC

FC_TEXT = FC.read_text(encoding="utf-8")

#: 端到端那条路真会读到的那份模型（front 的草稿与它同形，见
#: `executors/front/main.py::_draft_casemodel`）。上面的合成模型盖不到它的写法。
APB_SPEC = (Path(__file__).resolve().parents[5]
            / "specs" / "apb_uart" / "casemodel.yaml")
APB_TEXT = APB_SPEC.read_text(encoding="utf-8")


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
# 真模型 + CLI
# ════════════════════════════════════════════════════════════

class TestAgainstTheShippedModel:
    """拿仓库里那份真模型跑 —— 上面那些合成模型盖不到的写法在这里现形。"""

    def test_apb_uart_yields_one_coverpoint_per_field(self):
        p = run_covergroups(APB_TEXT, "apb_uart")
        assert p["coverpoint_count"] == 3
        assert {c["signal"] for c in p["coverpoints"]} == {"paddr", "pwrite", "pwdata"}

    def test_apb_uart_bin_count_matches_the_declared_boundaries(self):
        # paddr 6 个边界 + pwrite 2 个枚举 + pwdata 2 个边界
        p = run_covergroups(APB_TEXT, "apb_uart")
        assert p["bin_count"] == 10

    def test_the_rendered_covergroup_names_the_real_signals(self):
        code = run_covergroups(APB_TEXT, "apb_uart")["covergroup_code"]
        assert "covergroup cg_apb_uart;" in code
        for sig in ("paddr", "pwrite", "pwdata"):
            assert f"coverpoint {sig} " in code
        assert code.rstrip().endswith("endgroup")

    def test_the_apb_uart_covergroup_actually_compiles(self, tmp_path):
        """**生成器最容易犯的错是产出一段看着对、vlog 编不过的 SV。**

        合成模型的断言挡不住这一类（我自己就在 `bins b_ = {0};` 上栽过一次，
        是这条端到端编译才暴露的）。没装 Questa 就跳过 —— 缺工具不是失败。
        """
        import shutil
        import subprocess
        from config.settings import questa_home

        vlog = Path(questa_home()) / "win64" / "vlog.exe"
        if not vlog.exists():
            vlog = Path(shutil.which("vlog") or "")
        if not vlog or not vlog.exists():
            pytest.skip("没装 Questa（vlog 找不到）—— 编译验证跳过")

        (tmp_path / "apb_uart_cg.sv").write_text(
            run_covergroups(APB_TEXT, "apb_uart")["covergroup_code"], encoding="utf-8")
        (tmp_path / "stub.sv").write_text(
            'module cg_stub;\n'
            '  logic [7:0] paddr, pwdata;\n'
            '  logic pwrite;\n'
            '  `include "apb_uart_cg.sv"\n'
            '  cg_apb_uart cg;\n'
            '  initial begin cg = new(); cg.sample(); end\n'
            'endmodule\n', encoding="utf-8")
        # 不加 `-quiet`：它会把 `Errors: 0` 那行结算也一起吞掉 —— 那样"编译通过"
        # 就只剩退出码一个证据，而 vlog 对某些错误给的正是退出码 0。
        r = subprocess.run(
            [str(vlog), "-sv", "-work", str(tmp_path / "work"),
             f"+incdir+{tmp_path}", str(tmp_path / "stub.sv")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180)
        out = f"{r.stdout}\n{r.stderr}"
        assert "Errors: 0" in out, out[-2000:]

    def test_cli_writes_the_covergroup_file(self, tmp_path):
        import subprocess
        import sys

        out = tmp_path / "cg.sv"
        r = subprocess.run(
            [sys.executable, "-m", "src.tools.generation.casemodel_tools.cli", "covergroups",
             str(APB_SPEC), "--module", "apb_uart", "--out", str(out)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0, r.stderr
        assert out.is_file()
        assert "covergroup cg_apb_uart;" in out.read_text(encoding="utf-8")


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


class TestTheNpuSchedulerModel:
    """仓库里那份真实模型（`specs/npu_sched/casemodel.yaml`）。

    它是**唯一**同时用上显式区间仓、字段级 illegal、binsof 过滤交叉、
    交叉级 illegal、需求编号这五样的模型 —— 上面那些合成用例各自只盖一角，
    合在一起能不能编译只有它知道。
    """

    NPU = (Path(__file__).resolve().parents[5]
           / "specs" / "npu_sched" / "casemodel.yaml")

    @pytest.fixture(scope="class")
    def payload(self):
        return run_covergroups(self.NPU.read_text(encoding="utf-8"), "npu_sched")

    def test_twelve_coverpoints_one_per_cp(self, payload):
        assert payload["coverpoint_count"] == 12

    def test_the_queue_coverpoint_uses_range_bins(self, payload):
        q = next(c for c in payload["coverpoints"] if c["signal"] == "queue_level")
        assert [(b["name"], b["literal"]) for b in q["bins"]] == [
            ("empty", "0"), ("low", "[1:7]"), ("mid", "[8:15]"),
            ("high", "[16:24]"), ("near_full", "[25:31]"), ("full", "32")]
        assert q["illegal_bins"][0]["literal"] == "[33:$]"

    def test_seven_crosses_as_in_the_plan(self, payload):
        assert payload["cross_count"] == 7

    def test_six_of_them_are_filtered_and_one_is_not(self, payload):
        assert len([c for c in payload["crosses"] if c["bin_count"]]) == 6
        # 唯一没给过滤名单的那条（§3.3 X_NPU_CLUSTER_UNIT_005）走全交叉
        unfiltered = [c for c in payload["crosses"] if not c["bin_count"]]
        assert [c["dimensions"] for c in unfiltered] == [["D_cluster", "D_unit"]]

    def test_every_cross_illegal_from_the_plan_is_there(self, payload):
        illegal = {b["name"] for c in payload["crosses"] for b in c["bins"]
                   if b["illegal"]}
        assert illegal == {"mac_to_dma", "int8_vector", "mac_vec"}

    def test_cp_and_req_ids_cover_all_twelve(self, payload):
        """十二个覆盖点各有编号，且与需求一一对上 —— 追溯矩阵的两头都齐。"""
        ids = [c["cover_id"] for c in payload["coverpoints"]]
        reqs = [c["requirement"] for c in payload["coverpoints"]]
        assert len(set(ids)) == len(set(reqs)) == 12
        assert all(i.startswith("CP_NPU_") for i in ids)
        assert set(reqs) == {f"REQ-NPU-{n:03d}" for n in range(1, 13)}

    def test_it_compiles(self, tmp_path):
        """这套写法（区间仓 / binsof / 两级 illegal）**必须真过 vlog**。

        合成用例的断言挡不住语法问题 —— 实测 `{[33:0]}`（空区间）就是这样
        漏过去的：看着对、编译也过，只是永远不命中。所以这条真调编译器。
        """
        import shutil
        import subprocess

        from config.settings import questa_home

        vlog = Path(questa_home()) / "win64" / "vlog.exe"
        if not vlog.exists():
            vlog = Path(shutil.which("vlog") or "")
        if not vlog or not vlog.exists():
            pytest.skip("没装 Questa（vlog 找不到）—— 编译验证跳过")

        code = run_covergroups(self.NPU.read_text(encoding="utf-8"),
                               "npu_sched")["covergroup_code"]
        frag = code[code.index("covergroup "):
                    code.index("endgroup") + len("endgroup")]
        (tmp_path / "cg.sv").write_text(frag + "\n", encoding="utf-8")
        (tmp_path / "stub.sv").write_text(
            "module cg_stub;\n"
            "  bit [7:0] queue_level;\n"
            "  bit [2:0] instr_type, instr_dtype, dep_type, issue_unit,\n"
            "            instr_seq, pipeline_state, op_priority, barrier_type;\n"
            "  bit [1:0] issue_decision, cluster_id;\n"
            "  bit [3:0] instr_opcode;\n"
            '  `include "cg.sv"\n'
            "  cg_npu_sched cg;\n"
            "  initial begin cg = new(); cg.sample(); end\n"
            "endmodule\n", encoding="utf-8")
        r = subprocess.run(
            [str(vlog), "-sv", "-work", str(tmp_path / "work"),
             f"+incdir+{tmp_path}", str(tmp_path / "stub.sv")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180)
        assert "Errors: 0" in f"{r.stdout}\n{r.stderr}", (r.stdout or "")[-2000:]


# ════════════════════════════════════════════════════════════
# DUT 探针：第二条采样通道
# ════════════════════════════════════════════════════════════

SAMPLING = '''
version: "1"
object: dut
object_code: DUT
sampling: {dut_module: dut_mod, clock: clk, reset: rst_n}
sub_objects: [{id: OBJ-01, name: x, code: X}]
dimensions:
  - id: D_stim
    name: 激励
    fields:
      - name: instr_type
        type: enum
        values: ["MAC", "DMA"]
        cover_bins: [mac, dma]
  - id: D_state
    name: 内部状态
    fields:
      - name: queue_level
        type: range
        min: 0
        max: 32
        cut_width: 6
        sample: dut
        cover_bins:
          - {name: empty, at: 0}
          - {name: low, range: [1, 7]}
        cover_illegal:
          - {name: over, from: 33}
themes: [{id: TH-P0, name: f, priority: P0, dimensions: [D_stim, D_state]}]
'''.replace("cut_width", "width")


def _sampling_model(**over) -> str:
    import re

    text = SAMPLING
    for k, v in over.items():
        text = re.sub(rf"({k}: )[^,\}}]+", rf"\g<1>{v}", text, count=1)
    return text


class TestSamplingSources:
    """`sample: stimulus | dut` —— 两条通道的**可见性完全不同**。

    monitor 的事务通道只看得到激励侧；队列水位、依赖类型、输出端口这些**只有
    从 DUT 内部才看得见**。分不清这一点，就会给一堆采不到的信号生成一份永远
    不命中的覆盖率模型。
    """

    def test_default_is_stimulus(self):
        text = _model(dimensions=[
            {"id": "D_a", "name": "A",
             "fields": [{"name": "sig", "type": "enum", "values": [0, 1]}]}])
        assert run_covergroups(text, "dut")["coverpoints"][0]["source"] == "stimulus"

    def test_source_is_carried_and_split(self):
        p = run_covergroups(SAMPLING, "dut")
        assert p["stimulus_coverpoint_count"] == 1
        assert p["dut_coverpoint_count"] == 1
        assert p["probe_ports"] == ["queue_level"]


class TestProbeRendering:
    """bind 探针的形态 —— 端口、bind 语句、复位屏蔽。"""

    @pytest.fixture(scope="class")
    def code(self):
        return run_covergroups(SAMPLING, "dut")["probe_code"]

    def test_one_port_per_dut_coverpoint(self, code):
        assert "input logic [5:0] queue_level" in code

    def test_clock_and_reset_are_ports_too(self, code):
        """**复位也得是端口** —— 它同样活在 DUT 作用域里。

        裸写在 `if (rst_n)` 里，probe.sv 当场报 `Undefined variable: 'rst_n'`
        （实测踩过）。时钟同理。
        """
        assert "input logic clk," in code
        assert "input logic rst_n," in code
        assert ".rst_n(rst_n)" in code

    def test_reset_guards_the_sampling(self, code):
        assert "always @(posedge clk) if (rst_n) cg.sample();" in code

    def test_the_bind_targets_the_module_not_an_instance(self, code):
        """挂**模块**上 —— 每个实例自动带一份；挂实例名换个 bench 就断。"""
        assert "bind dut_mod cg_dut_dut_probe u_cg_probe(" in code

    def test_no_trailing_comma_in_the_bind_list(self, code):
        """`..., )` 是语法错误 —— vlog 报 `near ")": expecting .* or '.'`（实测）。"""
        import re

        conns = code[code.index("bind dut_mod"):]
        assert not re.search(r",\s*\)\s*;", conns)

    def test_illegal_bins_go_with_the_probe(self, code):
        """区间仓与 illegal 只进探针那份 —— env_cov 的模板没有它们的写法。"""
        assert "bins low = {[1:7]};" in code
        assert "illegal_bins over = {[33:$]};" in code

    def test_a_stimulus_only_model_produces_no_probe(self):
        text = _model(dimensions=[
            {"id": "D_a", "name": "A",
             "fields": [{"name": "sig", "type": "enum", "values": [0, 1]}]}])
        assert run_covergroups(text, "dut")["probe_code"] == ""

    def test_omitting_the_reset_drops_the_guard(self):
        """复位给 `null` = 不屏蔽（有的 DUT 高有效，或者压根不想屏蔽）。"""
        text = SAMPLING.replace("reset: rst_n", "reset: null")
        code = run_covergroups(text, "dut")["probe_code"]
        assert "if (rst_n)" not in code
        assert "always @(posedge clk) cg.sample();" in code


class TestProbeNeedsABindTarget:
    def test_missing_dut_module_is_noted_with_the_fix(self):
        """有 `sample: dut` 的字段却没给 `dut_module` —— **说清楚怎么写**。

        生成不出探针是"缺一句配置"，不是"模型写错了"。这两种提示差很远。
        """
        text = SAMPLING.replace("sampling: {dut_module: dut_mod, clock: clk, reset: rst_n}",
                                "sampling: {clock: clk}")
        out = run_covergroups(text, "dut")
        assert out["probe_code"] == ""
        assert out["probe_ports"] == ["queue_level"]      # 字段还在，只是生成不出
        assert any("dut_module" in n and "sampling:" in n for n in out["notes"])


class TestMixedSourceCrossIsRefused:
    """交叉的两边必须在**同一个 covergroup** 里 —— 一边一边表达不了。"""

    def test_it_is_noted_not_silently_dropped(self):
        text = _model(
            dimensions=[
                {"id": "D_a", "name": "A",
                 "fields": [{"name": "sig_a", "type": "enum", "values": [0, 1]}]},
                {"id": "D_b", "name": "B",
                 "fields": [{"name": "sig_b", "type": "enum", "values": [0, 1],
                             "sample": "dut"}]},
            ],
            cross_matrix={"D_a×D_b": "required"})
        out = run_covergroups(text, "dut")
        assert out["cross_count"] == 0
        assert any("采样来源不同" in n for n in out["notes"])


class TestWidthDerivation:
    def test_range_width_comes_from_max(self):
        text = _model(dimensions=[{"id": "D_q", "name": "Q", "fields": [
            {"name": "q", "type": "range", "min": 0, "max": 32, "sample": "dut"}]}])
        # 32 需要 6 位（0..63）
        assert run_covergroups(text, "dut")["coverpoints"][0]["width"] == 6

    def test_enum_width_comes_from_the_bin_values(self):
        text = _model(dimensions=[{"id": "D_e", "name": "E", "fields": [
            {"name": "e", "type": "enum", "values": [0, 1, 2, 3], "sample": "dut"}]}])
        assert run_covergroups(text, "dut")["coverpoints"][0]["width"] == 2

    def test_a_derived_width_is_noted(self):
        """推出来的宽度可能与端口不一致（枚举 4 个取值推 2 位、端口 3 位）——
        **记账**，因为不一致就是截断告警，而截断的覆盖点是错的数据。"""
        text = _model(dimensions=[{"id": "D_e", "name": "E", "fields": [
            {"name": "e", "type": "enum", "values": [0, 1, 2, 3], "sample": "dut"}]}])
        assert any("width" in n for n in run_covergroups(text, "dut")["notes"])


class TestTheNpuProbeCompiles:
    """NPU 那份模型的探针 —— **必须真过 vlog**（bind 的端口连接尤其容易错）。"""

    NPU = (Path(__file__).resolve().parents[5]
           / "specs" / "npu_sched" / "casemodel.yaml")

    def test_all_twelve_signals_are_dut_sourced(self):
        out = run_covergroups(self.NPU.read_text(encoding="utf-8"), "npu_sched")
        assert out["stimulus_coverpoint_count"] == 0
        assert out["dut_coverpoint_count"] == 12

    def test_it_compiles_against_a_stub_dut(self, tmp_path):
        import shutil
        import subprocess

        from config.settings import questa_home

        vlog = Path(questa_home()) / "win64" / "vlog.exe"
        if not vlog.exists():
            vlog = Path(shutil.which("vlog") or "")
        if not vlog or not vlog.exists():
            pytest.skip("没装 Questa（vlog 找不到）—— 编译验证跳过")

        out = run_covergroups(self.NPU.read_text(encoding="utf-8"), "npu_sched")
        (tmp_path / "probe.sv").write_text(out["probe_code"], encoding="utf-8")
        (tmp_path / "dut.sv").write_text(
            "module npu_sched (input logic clk, input logic rst_n,\n"
            "  input logic [2:0] instr_type, input logic [2:0] instr_dtype,\n"
            "  input logic [3:0] instr_opcode, input logic [1:0] barrier_type,\n"
            "  input logic [1:0] cluster_id, input logic [2:0] op_priority,\n"
            "  output logic [2:0] issue_unit, output logic [1:0] issue_decision);\n"
            "  logic [5:0] queue_level; logic [1:0] dep_type;\n"
            "  logic [7:0] instr_seq; logic [2:0] pipeline_state;\n"
            "endmodule\n", encoding="utf-8")
        r = subprocess.run(
            [str(vlog), "-sv", "-mfcu", "-cuname", "npu_sched_cu",
             "-work", str(tmp_path / "work"),
             str(tmp_path / "dut.sv"), str(tmp_path / "probe.sv")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180)
        assert "Errors: 0" in f"{r.stdout}\n{r.stderr}", (r.stdout or "")[-2000:]


# ════════════════════════════════════════════════════════════
# 功能覆盖率计划：覆盖点 + 批次 + 种子管理 + 需求追溯
# ════════════════════════════════════════════════════════════

def _plan_model(**over) -> str:
    base = {
        "version": "1", "object": "dut", "object_code": "DUT",
        "sub_objects": [{"id": "OBJ-01", "name": "F", "code": "F1"}],
        "dimensions": [
            {"id": "D_a", "name": "A", "fields": [
                {"name": "sig_a", "type": "enum", "values": [0, 1],
                 "cover_id": "CP_A", "requirement": "REQ-001"}]},
            {"id": "D_b", "name": "B", "fields": [
                {"name": "sig_b", "type": "enum", "values": [0, 1],
                 "cover_id": "CP_B", "requirement": "REQ-002"}]},
        ],
        "cross_matrix": {"D_a×D_b": {
            "level": "required", "cover_id": "X_AB", "requirement": "REQ-001/002"}},
        "themes": [
            {"id": "TH-T1", "name": "批一", "priority": "P0", "dimensions": ["D_a"],
             "test": "t1_test", "seeds": {"base": 1001, "count": 5, "explore": 2}},
        ],
    }
    base.update(over)
    return yaml.safe_dump(base, allow_unicode=True)


class TestCoveragePlan:
    """一份计划里摆四张表：覆盖点 / 批次 / 种子 / 追溯。

    **为什么要一起生成**：它们同源（都从同一份 case 模型派生），分散在三四个
    文件里对账很痛苦 —— 尤其"声明了 N 个覆盖点、回归里只跑 M 条"这种事，
    只有把两边摆在一张表上才看得出来。
    """

    @pytest.fixture(scope="class")
    def plan(self):
        return run_coverage_plan(_plan_model(), "dut")["plan"]

    def test_coverpoints_carry_their_ids(self, plan):
        assert [c["cover_id"] for c in plan["coverpoints"]] == ["CP_A", "CP_B"]

    def test_crosses_carry_their_ids(self, plan):
        assert plan["crosses"][0]["cover_id"] == "X_AB"

    def test_batches_carry_test_and_seeds(self, plan):
        b = plan["batches"][0]
        assert b["test"] == "t1_test"
        assert b["seeds"] == {"base": 1001, "count": 5, "explore": 2}

    def test_total_runs_is_count_plus_explore(self, plan):
        """探索种子**并进**总次数 —— 它们跑法一样，只是目的不同；
        分成两条反而让"这一批一共跑了多少次"说不清。"""
        assert plan["batches"][0]["total_runs"] == 7
        assert plan["summary"]["total_runs"] == 7

    def test_covered_by_links_a_coverpoint_to_its_batches(self, plan):
        cp_a = next(c for c in plan["coverpoints"] if c["signal"] == "sig_a")
        assert cp_a["covered_by"] == ["TH-T1"]

    def test_a_compound_requirement_is_split_not_left_whole(self, plan):
        """`REQ-001/002` 是"这两条"，**不是一条叫 REQ-001/002 的需求**。

        不拆的话追溯矩阵正好在**最该串起来的地方**断掉：那条交叉自己成一行，
        而 REQ-002 那一行没有交叉。
        """
        by = {t["requirement"]: t for t in plan["traceability"]}
        assert "REQ-001/002" not in by
        assert by["REQ-001"]["crosses"] == ["X_AB"]
        assert by["REQ-002"]["crosses"] == ["X_AB"]

    def test_the_shorthand_half_gets_the_prefix_back(self, plan):
        """`REQ-NPU-002/005` 的后半段是 **`REQ-NPU-005` 的简写**。

        照 `/` 硬拆会得到一条叫 `005` 的"需求" —— 矩阵上凭空多一条，而真正的
        REQ-NPU-005 仍然没有交叉。
        """
        text = _plan_model()
        text = text.replace("REQ-001/002", "REQ-NPU-002/005")
        text = text.replace('requirement: REQ-001\n', 'requirement: REQ-NPU-001\n')
        reqs = {t["requirement"] for t in
                run_coverage_plan(text, "dut")["plan"]["traceability"]}
        assert "005" not in reqs
        assert "REQ-NPU-005" in reqs

    def test_orphan_coverpoints_are_noted(self):
        """签核要的「无孤立覆盖点」过不了 —— 得在计划里说出来，不能只在表上留空。"""
        model = yaml.safe_load(_plan_model())
        del model["dimensions"][0]["fields"][0]["requirement"]   # A 没需求编号
        out = run_coverage_plan(yaml.safe_dump(model, allow_unicode=True), "dut")
        assert out.get("error") is None, out
        assert any("没有需求编号" in n for n in out["plan"]["notes"])

    def test_a_requirement_covered_only_by_a_cross_is_not_orphan(self):
        """**只看覆盖点是错的**：一条需求由交叉覆盖完全正当。

        按"有没有覆盖点"算，`X_AB` 认领的 REQ-001/002 会被全判成孤立需求 ——
        而它俩明明被那条交叉盖着。判据必须是"覆盖点**和**交叉都没有"。
        """
        model = yaml.safe_load(_plan_model())
        for d in model["dimensions"]:
            del d["fields"][0]["requirement"]          # 两个覆盖点都摘掉编号
        out = run_coverage_plan(yaml.safe_dump(model, allow_unicode=True), "dut")
        assert out.get("error") is None, out
        assert not any("既没有覆盖点也没有交叉" in n for n in out["plan"]["notes"]),             "被交叉认领的需求不该判成孤立需求"

    def test_a_batch_without_a_test_is_noted(self):
        text = _plan_model(themes=[{"id": "TH-T1", "name": "批一", "priority": "P0",
                                    "dimensions": ["D_a"]}])
        out = run_coverage_plan(text, "dut")
        assert any("没有 test 名" in n for n in out["plan"]["notes"])

    def test_a_batch_without_seeds_is_noted(self):
        text = _plan_model(themes=[{"id": "TH-T1", "name": "批一", "priority": "P0",
                                    "dimensions": ["D_a"], "test": "t1_test"}])
        out = run_coverage_plan(text, "dut")
        assert any("没有声明 seeds" in n for n in out["plan"]["notes"])


class TestTheNpuCoveragePlan:
    """NPU 那份模型的计划 —— 与文档 §3/§5/§6/§8 逐项对。"""

    NPU = (Path(__file__).resolve().parents[5]
           / "specs" / "npu_sched" / "casemodel.yaml")

    @pytest.fixture(scope="class")
    def plan(self):
        return run_coverage_plan(self.NPU.read_text(encoding="utf-8"),
                                 "npu_sched")["plan"]

    def test_twelve_coverpoints_and_seven_crosses(self, plan):
        assert plan["summary"]["coverpoint_count"] == 12
        assert plan["summary"]["cross_count"] == 7

    def test_eleven_batches_each_with_a_test_and_seeds(self, plan):
        assert len(plan["batches"]) == 11
        assert all(b["test"] and b["seeds"] for b in plan["batches"])

    def test_total_runs_matches_the_plans_seed_table(self, plan):
        """§6.1 的总运行次数逐条加起来 = 195。"""
        assert [b["total_runs"] for b in plan["batches"]] == \
            [1, 18, 18, 30, 12, 18, 12, 10, 14, 14, 48]
        assert plan["summary"]["total_runs"] == 195

    def test_the_traceability_matrix_has_no_orphans(self, plan):
        """§9.1 的签核条件之一：「无孤立需求，无孤立覆盖点」。"""
        assert plan["summary"]["requirement_count"] == 12
        assert all(t["coverpoints"] for t in plan["traceability"])
        assert all(c["requirement"] for c in plan["coverpoints"])

    def test_requirement_001_sees_both_its_coverpoint_and_its_cross(self, plan):
        """§8 那一行：REQ-NPU-001 → CP_NPU_QUEUE_001 + X_NPU_LEVEL_DEC_004。"""
        row = next(t for t in plan["traceability"]
                   if t["requirement"] == "REQ-NPU-001")
        assert row["coverpoints"] == ["CP_NPU_QUEUE_001"]
        assert row["crosses"] == ["X_NPU_LEVEL_DEC_004"]
        assert row["batches"] == ["TH-B06", "TH-B11"]


# ════════════════════════════════════════════════════════════
# 覆盖率接口（bind 进 DUT，把信号引给 env 覆盖率组件）
# ════════════════════════════════════════════════════════════

DUT_STUB = """\
module npu_sched (input logic clk, input logic rst_n,
                  input logic [7:0] instr_opcode, input logic [2:0] instr_type,
                  input logic [1:0] op_priority,
                  output logic [2:0] issue_unit);
  logic [5:0] queue_level;
  logic [1:0] dep_type;
  always_ff @(posedge clk) if (!rst_n) begin
    queue_level <= 0; dep_type <= 0;
  end else begin
    queue_level <= queue_level + 1;
    dep_type <= instr_type[1:0];
  end
  assign issue_unit = instr_type;
endmodule
"""

COV_MODEL = """
version: "1.0"
module: {name: @MODULE@, object_ref: X}
coverpoints:
  - id: CP_Q
    name: cp_queue_level
    signal: queue_level
    bins: [{name: cp_low, ranges: [[0, 15]]}, {name: cp_high, ranges: [[16, 63]]}]
  - id: CP_T
    name: cp_instr_type
    signal: instr_type
    bins: [{name: cp_mac, values: [0]}, {name: cp_vec, values: [1]}]
  - id: CP_OP
    name: cp_opcode
    signal: instr_opcode
    width: 8
    bins: [{name: cp_op0, values: [0]}]
crosses:
  - id: X_QT
    name: X_qt
    cross: [cp_instr_type, cp_queue_level]
"""


def _cov_cm(**over):
    from src.tools.generation.casemodel_tools.coverage import parse_coverage_model

    name = over.pop("name", "npu_sched")
    # **不能用 `.format()`**：YAML 的流式写法 `{name: ..., object_ref: X}` 里的
    # 花括号会被当成占位符（KeyError）。用显式记号替换。
    text = COV_MODEL.replace("@MODULE@", name)
    for k, v in over.items():
        text = text.replace(k, v)
    return parse_coverage_model(text, None)


class TestCoverageInterface:
    """覆盖率接口 = **bind 进 DUT 的接口**，把采样信号（含内部状态）引给 env 组件。

    为什么不直接把 covergroup 写进 `env/<env>_coverage.sv`：那个文件被
    `include` 进 `env_pkg`（`environment.sv` 把它当 `uvm_component` 例化），
    **里面只能是 class** —— 而 class 看不到 DUT 的内部状态。信号得先被引出来。
    """

    def test_signals_are_declared_as_ports_not_variables(self):
        """**必须是端口**：`bind` 的 `.sig(expr)` 连的是**被绑模块的端口**。

        写成接口体内的变量时 `vlog` 照样 `Errors: 0`（它压根不查 bind 的连接），
        要到 `vopt` 才报 `(vopt-2912) Port 'sig' not found`。
        """
        from src.tools.generation.casemodel_tools.coverage import render_cov_interface

        sv = render_cov_interface(_cov_cm(), {"dut_module": "npu_sched"})
        assert "interface npu_sched_cov_if (" in sv
        assert "input logic [5:0] queue_level" in sv     # 端口，且带位宽
        assert "logic queue_level;" not in sv            # 不是接口体内的变量
        assert "bind npu_sched npu_sched_cov_if" in sv

    def test_the_clock_and_reset_are_ports_too(self):
        """组件靠**端口**时钟沿采样 + 复位屏蔽 —— 时钟/复位同样活在 DUT 作用域里，
        不引出来组件够不到（探针那边为同一个原因吃过一次 `Undefined variable`）。"""
        from src.tools.generation.casemodel_tools.coverage import render_cov_interface

        sv = render_cov_interface(
            _cov_cm(), {"dut_module": "npu_sched", "clock": "clk", "reset": "rst_n"})
        assert "input logic clk," in sv
        assert "input logic rst_n," in sv
        assert ".clk(clk)" in sv and ".rst_n(rst_n)" in sv

    def test_extra_signals_are_exposed_for_assertion_rules(self):
        """断言规则引用、但没被覆盖点采的信号也要引成端口。

        历史坑：`raw_never_issues` 要读 `issue_valid`，而它不在任何覆盖点里 →
        接口没有它 → env 检查组「引用到接口上没有的信号」直接跳过这条规则，
        **断言那一半等于没查**。规则声明的 `{name,width}` 正好够生成端口。
        """
        from src.tools.generation.casemodel_tools.coverage import (
            checker_rules, cov_interface_meta, render_cov_interface)

        sampling = {"dut_module": "npu_sched"}
        cm = _cov_cm()
        meta = cov_interface_meta(cm, sampling,
                                  extra_signals=[{"name": "issue_valid", "width": 1}])
        assert "issue_valid" in meta["signals"]
        sv = render_cov_interface(cm, sampling,
                                  extra_signals=[{"name": "issue_valid", "width": 1}])
        assert "input logic issue_valid" in sv
        assert ".issue_valid(issue_valid)" in sv
        # 引了端口，规则就该**能查**而不是被跳过
        # 左半边用**采样信号**（模型里有），右半边用额外引的 —— 两边都在
        # `available` 里，规则才求得了值
        decl = [{"name": "raw", "expr": "queue_level == 6'd32 |-> issue_valid == 1'b0",
                 "signals": [{"name": "queue_level", "width": 6},
                             {"name": "issue_valid", "width": 1}]}]
        got = checker_rules(decl, meta["signals"])
        assert [r["name"] for r in got["rules"]] == ["raw"]
        assert got["skipped"] == []

    def test_extra_signals_dedupes_against_sampled_ones(self):
        """已经在采样里的名字不能再引一遍 —— 会撞端口名。"""
        from src.tools.generation.casemodel_tools.coverage import cov_interface_meta

        meta = cov_interface_meta(_cov_cm(), {"dut_module": "npu_sched"},
                                  extra_signals=[{"name": "queue_level", "width": 6}])
        assert meta["extra_signals"] == []
        assert meta["signals"].count("queue_level") == 1

    def test_only_dut_sourced_coverpoints_are_exposed(self):
        """`sample: stimulus` 的走 env_cov 那条路，不该出现在这个接口里。"""
        from src.tools.generation.casemodel_tools.coverage import render_cov_interface

        cm = _cov_cm()
        cm.coverpoints[0].source = "stimulus"
        sv = render_cov_interface(cm, {"dut_module": "npu_sched"})
        assert "queue_level" not in sv
        assert "instr_type" in sv

    def test_no_dut_module_no_interface(self):
        from src.tools.generation.casemodel_tools.coverage import render_cov_interface

        assert render_cov_interface(_cov_cm(), {"dut_module": ""}) == ""
        assert render_cov_interface(_cov_cm(), {}) == ""

    def test_the_name_comes_from_one_place(self):
        """名字 / 实例 / 时钟 / 复位 / 文件路径**只有一处出处**（`cov_interface_meta`）。

        三处各推一次就是"改了三个漏一个"：生成方按它落盘、env 组件持
        `virtual <type>`、tb_top 写 `<dut 实例>.u_<name>` —— 有一个推错就对不上，
        而对不上的表现是**句柄为空、覆盖率 0%**（编译不报错）。
        """
        from src.tools.generation.casemodel_tools.coverage import (cov_interface_meta,
                                                        render_cov_interface)

        sampling = {"dut_module": "npu_sched", "clock": "clk", "reset": "rst_n"}
        meta = cov_interface_meta(_cov_cm(), sampling)
        assert meta["type"] == "npu_sched_cov_if"
        assert meta["instance"] == "u_npu_sched_cov_if"
        assert meta["file"] == "coverage/npu_sched_cov_if.sv"
        sv = render_cov_interface(_cov_cm(), sampling)
        # 渲染出来的东西必须**逐字**对得上 meta —— 否则三处就漂了
        for key in ("type", "instance", "dut_module", "clock", "reset"):
            assert meta[key] in sv, key

    def test_it_elaborates_against_a_real_dut(self, tmp_path):
        """**用 `vopt` 验，不用 `vlog`** —— 后者对 bind 的连接一言不发。

        实测：故意 bind 一个不存在的信号，`vlog` 仍然 `Errors: 0`；
        换 `vopt` 才报 `(vopt-2958) Implicit wire ... does not have any driver`。
        所以"编译过了"这句话，只有 vopt 说过才算数。
        """
        import shutil
        import subprocess

        from config.settings import questa_home

        from src.tools.generation.casemodel_tools.coverage import render_cov_interface

        bindir = Path(questa_home()) / "win64"
        vlog, vopt = bindir / "vlog.exe", bindir / "vopt.exe"
        if not vlog.exists() or not vopt.exists():
            pytest.skip("没装 Questa（vlog/vopt 找不到）—— elaborate 验证跳过")

        (tmp_path / "dut.sv").write_text(DUT_STUB, encoding="utf-8")
        (tmp_path / "cov_if.sv").write_text(
            render_cov_interface(_cov_cm(), {"dut_module": "npu_sched"}),
            encoding="utf-8")
        r1 = subprocess.run(
            [str(vlog), "-sv", "-mfcu", "-cuname", "t_cu",
             "-work", str(tmp_path / "work"),
             str(tmp_path / "dut.sv"), str(tmp_path / "cov_if.sv")],
            cwd=str(tmp_path), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180)
        assert "Errors: 0" in f"{r1.stdout}\n{r1.stderr}", (r1.stdout or "")[-1500:]
        r2 = subprocess.run([str(vopt), "-work", "work", "npu_sched", "-o", "t_opt"],
                            cwd=str(tmp_path), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=180)
        out = f"{r2.stdout}\n{r2.stderr}"
        assert "Errors: 0" in out, out[-1500:]
        # 内部状态（queue_level）也连上了 —— 这正是这条通道存在的理由
        assert "does not have any driver" not in out, out[-1500:]

    def test_vlog_alone_does_not_catch_a_bogus_bind(self, tmp_path):
        """**把那个教训本身钉住**：vlog 说"过了"不算过。

        这条不是验证生成器，是验证"我们用的标尺对不对" —— 一条故意连错信号的
        bind，`vlog` 必须报 `Errors: 0`（说明它不查），`vopt` 必须报错。
        哪天 vlog 开始查了，这条会红，那时可以把标尺换回 vlog。
        """
        import shutil
        import subprocess

        from config.settings import questa_home

        bindir = Path(questa_home()) / "win64"
        vlog, vopt = bindir / "vlog.exe", bindir / "vopt.exe"
        if not vlog.exists() or not vopt.exists():
            pytest.skip("没装 Questa（vlog/vopt 找不到）")

        (tmp_path / "dut.sv").write_text(DUT_STUB, encoding="utf-8")
        (tmp_path / "bad.sv").write_text(
            "interface bad_if (input logic nowhere);\nendinterface\n"
            "bind npu_sched bad_if u_bad(.nowhere(no_such_signal));\n", encoding="utf-8")
        r1 = subprocess.run(
            [str(vlog), "-sv", "-mfcu", "-cuname", "b_cu",
             "-work", str(tmp_path / "work"),
             str(tmp_path / "dut.sv"), str(tmp_path / "bad.sv")],
            cwd=str(tmp_path), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180)
        assert "Errors: 0" in f"{r1.stdout}\n{r1.stderr}", \
            "vlog 开始查 bind 了？那标尺可以简化"
        r2 = subprocess.run([str(vopt), "-work", "work", "npu_sched", "-o", "b_opt"],
                            cwd=str(tmp_path), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=180)
        out = f"{r2.stdout}\n{r2.stderr}"
        # 两种情况 vlog 都不吭声，vopt 才说 —— 而**说法还不一样**：
        #   接口上没这个**端口**  → vopt **error**（vopt-2912）
        #   DUT 里没这个**信号**  → vopt **warning**（vopt-2958 隐式线）
        # 所以"vopt 报了 error"不是这条通道的完整结论，`does not have any driver`
        # 同样要当回事（上一条测试正是按它断言的）。
        assert "does not have any driver" in out, out[-800:]
