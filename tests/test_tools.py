"""Tool tests — 工具层（spec/uvm/assertion/debug/coverage）

说明：旧测试引用不存在的 analyze_simulation_log（实际为 collect_sim_log），
以及 import 链上已删除的模块。已修正为当前真实工具 API。
"""
import json

from src.tools.spec_tools import analyze_specification, extract_features, generate_test_plan
from src.tools.uvm_tools import generate_uvm
from src.tools.assertion_tools import generate_sva_assertions
from src.tools.debug_tools import collect_sim_log
from src.tools.coverage_tools import collect_coverage


def test_analyze_specification():
    spec_text = """# UART Module
## Overview
Universal asynchronous receiver transmitter supporting 8N1 format.

## Interfaces
| Signal | Width | Direction | Protocol | Description |
|--------|-------|-----------|----------|-------------|
| clk | 1 | INPUT |  | Clock |
| rst_n | 1 | INPUT |  | Reset |
| tx | 1 | OUTPUT | uart | TX out |
| rx | 1 | INPUT | uart | RX in |
"""
    result = analyze_specification(spec_text)
    data = json.loads(result)
    assert "features" in data
    assert "interfaces" in data


def test_extract_features():
    result = extract_features("UART module with full duplex communication, configurable baud rate, and FIFO buffer support")
    data = json.loads(result)
    assert "basic_features" in data


def test_generate_test_plan():
    result = generate_test_plan("reqs")
    data = json.loads(result)
    assert "test_categories" in data
    assert len(data["test_categories"]) > 0


def test_uvm_generate_uvm():
    """Test generate_uvm is importable and callable"""
    assert generate_uvm is not None
    assert callable(generate_uvm)


def test_sva_assertions():
    """generate_sva_assertions 返回 SystemVerilog 文本（不是 JSON）。"""
    result = generate_sva_assertions("{}")
    assert isinstance(result, str) and len(result) > 0
    assert "property" in result or "assert" in result


def test_collect_sim_log_no_output_dir(tmp_path):
    """无输出目录 → 返回结构化错误（不抛异常），且无日志可扫。"""
    result = collect_sim_log(str(tmp_path / "nonexistent_run"))
    data = json.loads(result)
    assert "error" in data or "logs_scanned" in data


def test_collect_sim_log_with_errors(tmp_path):
    """有仿真日志含 UVM_ERROR → 能被解析出来（logs_with_errors > 0）。"""
    sim_dir = tmp_path / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "sim_test1.log").write_text(
        "# UVM_ERROR test_pkg.sv(42) @ 100ns: scoreboard mismatch expected=0x5 actual=0x0\n"
        "# UVM_INFO ... TEST PASSED\n",
        encoding="utf-8")
    result = collect_sim_log(str(tmp_path))
    data = json.loads(result)
    assert data["logs_scanned"] >= 1
    assert data["logs_with_errors"] >= 1


def test_collect_coverage():
    result = collect_coverage("all")
    data = json.loads(result)
    assert "code_coverage" in data
