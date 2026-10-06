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

from src.tools.lib.collect_real_coverage import _parse_cvg_text

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
        """用**项目自己的渲染器**（它挂了 `now` 之类全局）—— 别自己搭一个裸 Jinja。"""
        from pathlib import Path

        from src.tools.uvm_tools.tool_uvm.gen_uvm import JinjaRenderer, TEMPLATES_DIR

        renderer = JinjaRenderer(Path(TEMPLATES_DIR))
        return renderer.render("environment_templates/env_cov.sv.j2", dict(self.CONTEXT))

    def test_multi_bit_field_gets_value_class_bins(self):
        sv = self._render()
        assert "cp_paddr: coverpoint apb_item.paddr {" in sv
        assert "bins v_zero = {0};" in sv
        assert "bins v_rest = {[2:255]};" in sv      # 2**8 - 1

    def test_one_bit_field_stays_plain(self):
        """1 位字段本来就只有 2 个取值，分箱反而多此一举（`[2:1]` 是非法区间）。"""
        sv = self._render()
        assert "cp_pwrite: coverpoint apb_item.pwrite;" in sv


class TestGapSequenceHasItsOwnTimeout:
    """补出来的定向激励**自己带超时**，不指望全局看门狗。

    实测：激励随机到对手方不应答的事务，`finish_item` 一直等 → 全局看门狗
    （100µs）把整场仿真掐掉，失败现场看不出是"激励等不到应答"还是"DUT 挂了"，
    于是决策层拿它去改 RTL。包一层带超时的 `fork/join_any` 之后，超时由这段激励
    自己报出来（`GAPSEQ`），归因就明确了。
    """

    def _seq(self) -> str:
        from src.tools.coverage_tools.main import generate_gap_directed_seq

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
