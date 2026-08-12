"""Tool tests"""
import json
from src.tools.spec_tools import analyze_specification, extract_features, generate_test_plan
from src.tools.uvm_tools import generate_uvm
from src.tools.assertion_tools import generate_sva_assertions
from src.tools.debug_tools import analyze_simulation_log
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

## Features
- Full duplex communication
- Configurable baud rate
- FIFO buffer support
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
    result = generate_sva_assertions("{}")
    data = json.loads(result)
    assert "assertions" in data

def test_analyze_log():
    result = analyze_simulation_log("test.log")
    data = json.loads(result)
    assert "errors" in data

def test_collect_coverage():
    result = collect_coverage("all")
    data = json.loads(result)
    assert "code_coverage" in data
