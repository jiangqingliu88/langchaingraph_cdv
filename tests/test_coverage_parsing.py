"""功能覆盖率的解析与分箱 —— 两个"数字看着有、其实没意义"的坑。

坑一（解析）：`vcover report -cvg` 的输出里有**三处同一个百分比**（Covergroups 行、
TOTAL 行、Total By Instance 行），原来那段代码"把所有百分比抓出来求平均"，
于是报出 26.0% —— 而真值是 1.46%（bin 命中率）。同一数字算三遍，谁也不知道
覆盖率到底是多少。

坑二（模型）：自动生成的 covergroup 不给 coverpoint 写 bins，仿真器就把整个取值
空间自动分箱：8 位字段 256 个 bin，两个这样的字段做 cross 上万。随机激励永远
填不满 —— 4360 个 bin 只命中 64 个。分箱成值类（0/1/其余）之后 cross 只有 3×3。
"""
from __future__ import annotations

from src.tools.common.lib.collect_real_coverage import (_parse_cvg_details,
                                                 _parse_cvg_text)

#: 实测的 vcover 输出（smoke3 那次运行）
VCOVER_CVG = """\
Coverage Report Summary Data by instance

=================================================================================
=== Instance: /apb_uart_env_pkg
=== Design Unit: work.apb_uart_env_pkg
=================================================================================
    Enabled Coverage              Bins      Hits    Misses  Coverage
    ----------------              ----      ----    ------  --------
    Covergroups                      3        na        na    34.24%
        Coverpoints/Crosses          9        na        na        na
            Covergroup Bins       4360        64      4296     1.46%


TOTAL COVERGROUP COVERAGE: 34.24%  COVERGROUP TYPES: 3

Total Coverage By Instance (filtered view): 34.24%
"""


class TestParseCvgText:

    def test_functional_pct_is_the_bin_ratio(self):
        """功能覆盖率 = **bin 命中率**，不是那三处同一个数字的平均。"""
        result = _parse_cvg_text(VCOVER_CVG)
        assert result["functional_pct"] == 1.46
        assert result["bin_total"] == 4360
        assert result["bin_hits"] == 64

    def test_covergroup_count_is_a_count_not_a_percent_sign_count(self):
        result = _parse_cvg_text(VCOVER_CVG)
        assert result["covergroup_count"] == 3          # 不是 4（那是百分号个数）
        assert result["covergroup_pct"] == 34.24

    def test_empty_text_is_all_zero(self):
        result = _parse_cvg_text("")
        assert result["functional_pct"] == 0.0
        assert result["covergroup_count"] == 0


#: `vcover report -cvg -details` 实测输出（截自 output_e2e_fix2 那次运行的 merged.ucdb）。
#:
#: **注意它有两段**：`by instance with details`（逐实例、含每个 bin 的命中数）与
#: `COVERGROUP COVERAGE:`（逐 type）。两段的 `TYPE` 行一模一样 —— 照全文抓会把每个
#: covergroup 收两遍（实测 3 个变 6 个）。
VCOVER_CVG_DETAILS = """\
Coverage Report by instance with details

=================================================================================
=== Instance: /apb_uart_env_pkg
=== Design Unit: work.apb_uart_env_pkg
=================================================================================

Covergroup Coverage:
    Covergroups                      3        na        na    51.58%
        Coverpoints/Crosses          9        na        na        na
            Covergroup Bins         29        16        13    55.17%
----------------------------------------------------------------------------------------------------------
 TYPE /apb_uart_env_pkg/apb_uart_env_coverage/cg_apb
                                                       71.42%        100          -    Uncovered
    covered/total bins:                                    14         24          -
    Coverpoint cp_paddr                                66.66%        100          -    Uncovered
        bin v_zero                                          3          1          -    Covered
    Cross cross_all                                    33.33%        100          -    Uncovered
 TYPE /apb_uart_env_pkg/apb_uart_env_coverage/cg_uart
                                                       33.33%        100          -    Uncovered
    Coverpoint cp_data                                 33.33%        100          -    Uncovered
 TYPE /apb_uart_env_pkg/apb_uart_env_coverage/cg_intr
                                                       50.00%        100          -    Uncovered
    Coverpoint cp_irq                                  50.00%        100          -    Uncovered

COVERGROUP COVERAGE:
----------------------------------------------------------------------------------------------------------
 TYPE /apb_uart_env_pkg/apb_uart_env_coverage/cg_apb
                                                       71.42%        100          -    Uncovered
    Coverpoint cp_paddr                                66.66%        100          -    Uncovered
    Coverpoint cp_pwdata                               66.66%        100          -    Uncovered
    Cross cross_all                                    33.33%        100          -    Uncovered
 TYPE /apb_uart_env_pkg/apb_uart_env_coverage/cg_uart
                                                       33.33%        100          -    Uncovered
    Coverpoint cp_data                                 33.33%        100          -    Uncovered
 TYPE /apb_uart_env_pkg/apb_uart_env_coverage/cg_intr
                                                       50.00%        100          -    Uncovered
    Coverpoint cp_irq                                  50.00%        100          -    Uncovered

TOTAL COVERGROUP COVERAGE: 51.58%  COVERGROUP TYPES: 3
"""


class TestParseCvgDetails:
    """逐 covergroup 的列表 —— 证据链功能覆盖层读的就是它。

    修之前后端只产出一个标量 `covergroup_count`，`five_layer` 读不到列表，
    于是永远打印「0 covergroups」；而盘上明明有 3 个 covergroup。
    """

    def test_one_entry_per_covergroup_type(self):
        cgs = _parse_cvg_details(VCOVER_CVG_DETAILS)
        assert [c["name"] for c in cgs] == ["cg_apb", "cg_uart", "cg_intr"]

    def test_the_two_sections_do_not_double_count(self):
        """两段里 `TYPE` 行一模一样 —— 只看 `COVERGROUP COVERAGE:` 那段。"""
        cgs = _parse_cvg_details(VCOVER_CVG_DETAILS)
        assert len(cgs) == len({c["path"] for c in cgs}) == 3

    def test_actual_is_this_covergroups_own_percentage(self):
        by = {c["name"]: c for c in _parse_cvg_details(VCOVER_CVG_DETAILS)}
        assert by["cg_apb"]["actual"] == 71.42
        assert by["cg_uart"]["actual"] == 33.33
        assert by["cg_intr"]["actual"] == 50.00

    def test_key_names_match_the_evidence_schema(self):
        """`config/evidence_schema.yaml` 的 `evidence_fields.covergroups` 要这几个键。

        键名对不上，`five_layer` 读到的就是空 —— 那和"没有 covergroup"长得一样。
        """
        c = _parse_cvg_details(VCOVER_CVG_DETAILS)[0]
        assert {"name", "goal", "actual", "coverpoints", "crosses"} <= set(c)

    def test_coverpoints_and_crosses_are_kept_per_covergroup(self):
        by = {c["name"]: c for c in _parse_cvg_details(VCOVER_CVG_DETAILS)}
        assert [cp["name"] for cp in by["cg_apb"]["coverpoints"]] == \
            ["cp_paddr", "cp_pwdata"]
        assert [x["name"] for x in by["cg_apb"]["crosses"]] == ["cross_all"]
        assert by["cg_apb"]["cross_actual"] == 33.33

    def test_cross_actual_defaults_to_pass_when_there_is_no_cross(self):
        """没声明 cross 不等于 cross 挂了 —— 给 100（与 `five_layer` 的默认同义）。"""
        by = {c["name"]: c for c in _parse_cvg_details(VCOVER_CVG_DETAILS)}
        assert by["cg_uart"]["cross_actual"] == 100.0

    def test_no_details_section_yields_no_covergroups_not_a_crash(self):
        """老的 `-cvg`（无 `-details`）输出里没有 TYPE 行 —— 给空列表，不抛。"""
        assert _parse_cvg_details(VCOVER_CVG) == []

    def test_empty_text_is_an_empty_list(self):
        assert _parse_cvg_details("") == []

    def test_details_ride_along_on_parse_cvg_text(self):
        """`_parse_cvg_text` 的结果里也带上它 —— 调用方不用再解析一遍。"""
        result = _parse_cvg_text(VCOVER_CVG_DETAILS)
        assert len(result["covergroups"]) == 3


class TestCoverageModelIsBounded:
    """生成的 covergroup 必须给多位字段分箱 —— 否则模型不可收敛。"""

    #: 最小可渲染上下文（模板要用的键，照 `EnvironmentCovRenderTask` 那边给）
    CONTEXT = {
        "environment": {"env_name": "apb_uart_env"},
        "agents": [{"name": "apb", "seq_item_type": "apb_master_seq_item",
                    "transaction_vars": [
                        {"name": "paddr", "type": "bit [7:0]", "isrand": "True"},
                        {"name": "pwrite", "type": "bit", "isrand": "True"},
                    ]}],
        "coverage_crosses": [],
        "coverage_bins": [],
    }

    def _render(self) -> str:
        return self._render_with(self.CONTEXT)

    def _render_with(self, ctx: dict) -> str:
        """用**项目自己的渲染器**（它挂了 `now` 之类全局）—— 别自己搭一个裸 Jinja。"""
        from pathlib import Path

        from src.tools.generation.uvm_tools.tool_uvm.constants import TEMPLATES_DIR
        from src.tools.generation.uvm_tools.tool_uvm.render.jinja_renderer import JinjaRenderer

        renderer = JinjaRenderer(Path(TEMPLATES_DIR))
        return renderer.render("environment_templates/env_cov.sv.j2", dict(ctx))

    def test_multi_bit_field_gets_value_class_bins(self):
        sv = self._render()
        assert "cp_paddr: coverpoint apb_item.paddr {" in sv
        assert "bins v_zero = {0};" in sv
        assert "bins v_rest = {[2:255]};" in sv      # 2**8 - 1

    def test_one_bit_field_stays_plain(self):
        """1 位字段本来就只有 2 个取值，分箱反而多此一举（`[2:1]` 是非法区间）。"""
        sv = self._render()
        assert "cp_pwrite: coverpoint apb_item.pwrite;" in sv

    def test_case_model_bins_replace_the_value_classes(self):
        """模型声明了覆盖点就用模型的边界值 —— 那是"这一维该扫哪些点"的建模结论。

        `0/1/其余` 是**兜底**（模型没覆盖到这个字段），不是首选：覆盖率的意义就在于
        "声明的扫描点有没有被打到"，分母不对，结论就是错的。
        """
        ctx = dict(self.CONTEXT,
                   coverage_field_bins={"paddr": [{"name": "b_0", "value": 0},
                                                  {"name": "b_255", "value": 255}]})
        sv = self._render_with(ctx)
        assert "cp_paddr: coverpoint apb_item.paddr {   // 取自 case 模型" in sv
        assert "bins b_0 = {0};" in sv
        assert "bins b_255 = {255};" in sv
        assert "v_rest" not in sv                    # 值类兜底被替换掉了

    def test_a_field_the_model_does_not_cover_falls_back(self):
        """模型只管了 paddr —— pwrite 仍走兜底，不能被"没建模"变成没有覆盖点。"""
        ctx = dict(self.CONTEXT,
                   coverage_field_bins={"paddr": [{"name": "b_0", "value": 0}]})
        sv = self._render_with(ctx)
        assert "cp_pwrite: coverpoint apb_item.pwrite;" in sv

    def test_missing_field_bins_key_does_not_break_the_render(self):
        """夹具/老调用方不给这个键也得能渲染 —— 少一个键不该让整份 env 渲染失败。"""
        sv = self._render()
        assert "covergroup cg_apb;" in sv


class TestGapSequenceHasItsOwnTimeout:
    """补出来的定向激励**自己带超时**，不指望全局看门狗。

    实测：激励随机到对手方不应答的事务，`finish_item` 一直等 → 全局看门狗
    （100µs）把整场仿真掐掉，失败现场看不出是"激励等不到应答"还是"DUT 挂了"，
    于是决策层拿它去改 RTL。包一层带超时的 `fork/join_any` 之后，超时由这段激励
    自己报出来（`GAPSEQ`），归因就明确了。
    """

    def _seq(self) -> str:
        from src.layers.l3_decision.evidence.main import generate_gap_directed_seq

        return generate_gap_directed_seq(
            "apb", [{"dimension": "toggle", "location": "paddr[7:0]",
                     "reason": "unstimulated", "count": 2}],
            {"paddr": 8}, "", item_class="apb_master_seq_item")

    def test_body_is_wrapped_in_a_timeout_fork(self):
        code = self._seq()
        assert "fork" in code and "join_any" in code and "disable fork;" in code
        assert "GAP_TXN_TIMEOUT_NS" in code
        assert "对手方未应答" in code

    def test_directed_transaction_randomizes_before_overriding(self):
        """先 randomize 再压目标字段 —— 只设目标字段会让框架字段停在 0，
        事务在 DUT 看来根本不成立（实测：24 个 case 挂 21 个）。"""
        code = self._seq()
        override = code.index("req.paddr = ")
        assert "randomize()" in code[:override]


VCOVER_BIN_HITS = """\
Coverage Report by instance with details

 TYPE /p/npu_sched_env_pkg/npu_sched_env_coverage/cg_dut
                                                       72.63%        100          -    Uncovered
    covered/total bins:                                    39         59          -                      
    Coverpoint cp_queue_level                         100.00%        100          -    Covered
        covered/total bins:                                 6          6          -                      
        illegal_bin illegal_over                            0                     -    ZERO                 
        bin empty                                           8          1          -    Covered              
        bin low                                             7          1          -    Covered              
    Coverpoint cp_instr_type                           75.00%        100          -    Uncovered
        bin mac                                            12          1          -    Covered              
        bin vector                                          0          1          -    ZERO                 
COVERGROUP COVERAGE:
 TYPE /p/npu_sched_env_pkg/npu_sched_env_coverage/cg_dut
                                                       72.63%        100          -    Uncovered
"""

class TestTpMatrix:
    def _write_tp(self, tmp_path, rows):
        import yaml
        p = tmp_path / "coverage" / "testpoints.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump({"testpoints": rows}, allow_unicode=True),
                     encoding="utf-8")
        rep = tmp_path / "sim" / "coverage" / "reports"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "coverage_cvg.txt").write_text(VCOVER_BIN_HITS, encoding="utf-8")
        return {"report_dir": str(rep)}

    def test_bin_hits_are_parsed_per_coverpoint(self):
        from src.tools.common.lib.collect_real_coverage import _parse_cvg_bin_hits

        hits = _parse_cvg_bin_hits(VCOVER_BIN_HITS)
        assert hits["cg_dut"]["cp_queue_level"] == {"illegal_over": 0,
                                                    "empty": 8, "low": 7}
        assert hits["cg_dut"]["cp_instr_type"]["mac"] == 12

    def test_four_states_keep_observe_apart(self, tmp_path):
        from src.tools.common.lib.collect_real_coverage import _tp_matrix

        cov = self._write_tp(tmp_path, [
            {"tp_id": "TP-1", "coverpoint": "cp_queue_level", "bin": "empty",
             "observe_only": True},
            {"tp_id": "TP-2", "coverpoint": "cp_instr_type", "bin": "mac",
             "observe_only": False},
            {"tp_id": "TP-3", "coverpoint": "cp_instr_type", "bin": "vector",
             "observe_only": False},
            {"tp_id": "TP-4", "coverpoint": "cp_queue_level", "bin": "low",
             "observe_only": False},
        ])
        m = _tp_matrix(tmp_path, cov)
        assert m["counts"] == {"HIT": 2, "MISS": 1, "OBSERVED": 1,
                               "UNOBSERVED": 0, "BACKDOOR_HIT": 0,
                               "BACKDOOR_MISS": 0, "UNMAPPED": 0,
                               # 没有回归目录 → 没有逐用例证据：签核一律 UNSIGNED，
                               # 不把"合并库里命中"冒充成"这条用例证明了"。
                               "SIGNED_OFF": 0, "UNSIGNED": 4}
        assert m["drivable"] == 3 and m["drivable_hit"] == 2
        assert [r["tp_id"] for r in m["missed"]] == ["TP-3"]

    def test_unknown_bin_is_unmapped_not_a_silent_miss(self, tmp_path):
        """模型与生成漂了 → UNMAPPED，**不冒充"没命中"**（那样会去补错用例）。"""
        from src.tools.common.lib.collect_real_coverage import _tp_matrix

        cov = self._write_tp(tmp_path, [
            {"tp_id": "TP-X", "coverpoint": "cp_queue_level", "bin": "nope"},
        ])
        m = _tp_matrix(tmp_path, cov)
        assert m["counts"]["UNMAPPED"] == 1
        assert m["unmapped"][0]["tp_id"] == "TP-X"

    def test_no_testpoints_means_no_matrix(self, tmp_path):
        from src.tools.common.lib.collect_real_coverage import _tp_matrix

        assert _tp_matrix(tmp_path, {}) == {}


def test_behavior_testpoints_are_pending_not_unmapped():
    """行为 TP 没有覆盖率数据可判 —— 单独一栏，混进 UNMAPPED 就是误报。"""
    import tempfile
    from pathlib import Path

    from src.tools.common.lib.collect_real_coverage import _tp_matrix

    class _T(TestTpMatrix):
        pass

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cov = _T()._write_tp(tmp_path, [
            {"tp_id": "TP-A", "coverpoint": "cp_instr_type", "bin": "mac"},
            {"tp_id": "TP-BEH", "coverpoint": "", "bin": "",
             "realization": {"kind": "observe"},
             "execution": {"stage": "behavior"}},
        ])
        m = _tp_matrix(tmp_path, cov)
    assert m["counts"]["PENDING_BACKEND"] == 1
    assert m["counts"]["UNMAPPED"] == 0
    assert m["behavior_pending"] == 1
    assert m["drivable"] == 1          # 行为 TP 不进可激励分母
    assert [r["tp_id"] for r in m["unmapped"]] == []
