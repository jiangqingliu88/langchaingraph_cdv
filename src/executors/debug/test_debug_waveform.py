"""debug agent 的波形证据 —— "log + 波形诊断"里**波形**那一半。

不碰 Questa：用 `.vcd` 当波形（`extract_signal_trace` 直接读）。测的是
"agent 会不会真去取波形、取的是不是该取的那个信号"，不是 Questa 转换器。
"""
from __future__ import annotations

from src.executors.debug.main import DebugExecutor

VCD = """$timescale 1ns $end
$scope module tb $end
$scope module dut $end
$var wire 1 ! penable $end
$var wire 8 " ctrl [7:0] $end
$upscope $end
$enddefinitions $end
#0
0!
b00000000 "
#5
1!
b10100101 "
"""


def _case(tmp_path):
    case = tmp_path / "test_t"
    (case / "waves").mkdir(parents=True)
    (case / "waves" / "t.vcd").write_text(VCD, encoding="utf-8")
    (case / "sim_vsim.log").write_text("", encoding="utf-8")
    return case


class TestFindCaseWave:
    def test_finds_the_wave_next_to_the_log(self, tmp_path):
        """`log_file` 是 `<用例>/sim_*.log` → 波形就在同目录的 `waves/` 下。"""
        case = _case(tmp_path)
        assert DebugExecutor._find_case_wave(str(case / "sim_vsim.log")).endswith("t.vcd")

    def test_no_log_file_gives_empty(self):
        assert DebugExecutor._find_case_wave("") == ""

    def test_case_without_wave_gives_empty(self, tmp_path):
        case = tmp_path / "c"
        case.mkdir()
        (case / "sim_vsim.log").write_text("", encoding="utf-8")
        assert DebugExecutor._find_case_wave(str(case / "sim_vsim.log")) == ""


class TestSignalNamesIn:
    def test_identifiers_kept_in_message_order(self):
        names = DebugExecutor._signal_names_in("reg CTRL mismatch: w=0xA5 r=0x00")
        assert names[0] == "CTRL"

    def test_hex_fragments_are_not_signal_names(self):
        """`0xA5` 会被正则切成 `xA5` —— 那是数值，不能当成信号名去波形里找。"""
        assert "xA5" not in DebugExecutor._signal_names_in("w=0xA5 r=0x00")


class TestWaveformEvidence:
    def test_prefers_the_subject_named_first(self, tmp_path):
        """消息里 `ctrl` 在前、`penable` 在后 → 取 **ctrl**（更可能是主语），
        而不是"采样最多"的那个（penable 也有变化，但它只是被顺带提了一嘴）。"""
        case = _case(tmp_path)
        err = {"log_file": str(case / "sim_vsim.log")}
        trace, src = DebugExecutor._waveform_evidence(err, "reg ctrl mismatch penable=1")
        assert src.endswith("#ctrl")
        assert trace == [(0.0, 0), (5.0, 165)]

    def test_no_wave_and_no_match_give_empty(self, tmp_path):
        case = _case(tmp_path)
        err = {"log_file": str(case / "sim_vsim.log")}
        # 消息里没有任何波形里存在的信号 → 不硬凑
        assert DebugExecutor._waveform_evidence(err, "timeout waiting for sequencers") == ({}, "")
