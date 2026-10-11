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

from src.tools.casemodel_tools.api import (TOOL_COVERGROUPS, TOOL_NAMES, RUNNERS,
                                           run_covergroups, run_uvm_tests)
from src.tools.casemodel_tools.coverage import (MAX_BINS_PER_POINT, sv_ident,
                                                sv_value)

from .conftest import FC

FC_TEXT = FC.read_text(encoding="utf-8")

#: 端到端那条路真会读到的那份模型（front 的草稿与它同形，见
#: `executors/front/main.py::_draft_casemodel`）。上面的合成模型盖不到它的写法。
APB_SPEC = (Path(__file__).resolve().parents[4]
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
            [sys.executable, "-m", "src.tools.casemodel_tools.cli", "covergroups",
             str(APB_SPEC), "--module", "apb_uart", "--out", str(out)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0, r.stderr
        assert out.is_file()
        assert "covergroup cg_apb_uart;" in out.read_text(encoding="utf-8")
