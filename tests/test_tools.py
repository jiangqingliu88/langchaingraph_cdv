"""Tool tests — 工具层（spec/uvm/assertion/debug/coverage）

说明：旧测试引用不存在的 analyze_simulation_log（实际为 collect_sim_log），
以及 import 链上已删除的模块。已修正为当前真实工具 API。
"""
import json

from src.layers.l3_decision.spec_tools import analyze_specification, extract_features, generate_test_plan
from src.tools.generation.uvm_tools import generate_uvm
from src.tools.checking.assertion_tools import generate_sva_assertions
from src.executors.debug.tools import collect_sim_log
from src.layers.l3_decision.evidence import collect_coverage


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
    """有可断言特征时，返回的必须是**能编译的 module + bind**（不是散着的 property）。

    原来只要求"返回非空文本"，于是"把 `property` 平铺在 $unit 作用域"也算通过 ——
    而那种文件**编不过**（`property` 不能待在 $unit），而且没人把它放进编译清单。
    "有文本"和"真的在断言"是两件事。
    """
    import json as _json

    code = generate_sva_assertions(_json.dumps({
        "sampling": {"dut_module": "apb_dut"},
        "interfaces": [{"name": "APB", "signals": {"psel": {}, "penable": {},
                                                   "paddr": {"width": 8}, "pwrite": {}}}]}))
    assert "module apb_dut_sva" in code          # 包成 module（$unit 里放不了 property）
    assert "bind apb_dut apb_dut_sva" in code    # 挂进 DUT
    assert "assert property" in code             # **真的断言**（只声明 property 不 assert 等于没断言）
    assert "input logic psel" in code            # 引用到的信号是**端口**（否则 vlog 报未定义）


def test_sva_assertions_without_a_bind_target_are_not_fabricated():
    """挂不到对象上就**不出** —— 一份绑不上任何模块的断言，只是又一个"看着有"的产物。"""
    assert generate_sva_assertions("{}") == ""
    assert generate_sva_assertions('{"interfaces": [{"name": "APB"}]}') == ""


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
