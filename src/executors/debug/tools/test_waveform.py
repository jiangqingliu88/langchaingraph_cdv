"""波形解析 —— VCD 解析 + 按名字取信号。

`qwave.db`（qwaveman）与 `.wlf`（wlf2vcd）都先转成 VCD，再走**同一个** `parse_vcd_text`，
所以这里只测纯解析/选择逻辑，不碰 Questa 转换器（那要装 Questa + 真波形）。
"""
from __future__ import annotations

from src.executors.debug.tools.waveform import extract_signal_trace, parse_vcd_text

#: 最小但形状正确的 VCD：同名信号 `data` 故意出现在两个层次。
VCD = """$timescale 1ns $end
$scope module top $end
$scope module dut $end
$var wire 1 ! clk $end
$var wire 8 " data [7:0] $end
$upscope $end
$scope module ifc $end
$var wire 8 # data [7:0] $end
$upscope $end
$enddefinitions $end
#0
0!
b00000001 "
b00000010 #
#5
1!
b11111111 "
#10
0!
"""


def _write(tmp_path, text=VCD):
    p = tmp_path / "w.vcd"
    p.write_text(text, encoding="utf-8")
    return p


class TestParseVcdText:
    def test_hierarchy_and_values(self):
        t = parse_vcd_text(VCD)
        assert t["top/dut/clk"] == [(0.0, 0), (5.0, 1), (10.0, 0)]
        assert t["top/dut/data"] == [(0.0, 1), (5.0, 255)]
        assert t["top/ifc/data"] == [(0.0, 2)]

    def test_x_and_z_are_not_a_comparable_value(self):
        """含 x/z 的位串一律 None（未知态不是可比数值）。"""
        vcd = VCD.replace("b00000001 \"", "bxxxxxxxx \"")
        t = parse_vcd_text(vcd)
        # 该信号只剩 #5 的 b11111111
        assert t["top/dut/data"] == [(5.0, 255)]


class TestExtractSignalTrace:
    def test_picks_the_richest_path_not_a_merge(self, tmp_path):
        """同名信号在多个层次 → 取**采样最多**的那条，不是把几条 extend 到一起。

        合并不同层次的跳变会交织成一条假时间线（0,5 和 0 混在一起），
        拿去跟期望值比对必然错。
        """
        out = extract_signal_trace(_write(tmp_path), ["data"])
        assert out["data"] == [(0.0, 1), (5.0, 255)]        # 来自 top/dut/data

    def test_path_hint_selects_the_scope(self, tmp_path):
        out = extract_signal_trace(_write(tmp_path), ["data"], path_hint="ifc")
        assert out["data"] == [(0.0, 2)]

    def test_declared_but_never_changing_signal_is_omitted(self, tmp_path):
        """有 `$var` 声明、却没任何值变化的信号，不给空时间线（当"没有"）。"""
        vcd = VCD.replace("b00000010 #\n", "")
        out = extract_signal_trace(_write(tmp_path, vcd), ["data"])
        assert "#" not in out                                  # 没有 top/ifc/data
        assert out["data"] == [(0.0, 1), (5.0, 255)]

    def test_missing_file_gives_empty(self, tmp_path):
        assert extract_signal_trace(tmp_path / "nope.db", ["clk"]) == {}

    def test_unknown_extension_gives_empty(self, tmp_path):
        p = tmp_path / "x.xyz"
        p.write_text("junk", encoding="utf-8")
        assert extract_signal_trace(p, ["clk"]) == {}
