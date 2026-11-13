"""debug_tools 的两个入口：`collect_sim_log`（日志）与 `collect_waveform`（波形）。

（原先这文件 import 的是 `analyze_simulation_log` —— 那个名字早就改成
`collect_sim_log` 了，整份测试因此一直是 ImportError。这里改成测**现役 API**。）
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
from src.engine_plane.diagnostics import collect_sim_log, collect_waveform  # noqa: E402

VCD = """$timescale 1ns $end
$scope module tb $end
$var wire 1 ! clk $end
$upscope $end
$enddefinitions $end
#0
0!
#5
1!
"""


def test_collect_sim_log_reports_uvm_errors(tmp_path):
    case = tmp_path / "regression_run" / "build_b1" / "test_t1"
    case.mkdir(parents=True)
    (case / "sim_vsim.log").write_text(
        "# UVM_INFO x @ 0: uvm_test_top [T] ok\n"
        "# UVM_ERROR e.sv(3) @ 10: uvm_test_top [E] boom\n",
        encoding="utf-8")

    data = json.loads(collect_sim_log(str(tmp_path)))
    assert data["logs_scanned"] >= 1
    msgs = [e["message"] for entry in data["errors"] for e in entry["errors"]]
    assert any("boom" in m for m in msgs)


def test_collect_sim_log_without_logs_is_not_an_error(tmp_path):
    data = json.loads(collect_sim_log(str(tmp_path)))
    assert data["logs_scanned"] == 0 and data["errors"] == []


def test_collect_waveform_finds_and_extracts(tmp_path):
    """波形后缀从只认 `.wlf` 扩到 `.db/.vcd/.fsdb` —— qwave.db 是现在的产物。"""
    waves = tmp_path / "waves"
    waves.mkdir()
    (waves / "t.vcd").write_text(VCD, encoding="utf-8")

    data = json.loads(collect_waveform(
        json.dumps({"output_dir": str(tmp_path), "signals": "clk"})))
    assert data["waveforms_found"] == 1
    assert data["analyzed"][0]["signal_traces"]["clk"] == [[0.0, 0], [5.0, 1]]


def test_collect_waveform_with_no_wave_reports_zero(tmp_path):
    data = json.loads(collect_waveform(json.dumps({"output_dir": str(tmp_path)})))
    assert data["waveforms_found"] == 0
