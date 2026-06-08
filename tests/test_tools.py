"""Tool tests"""
import json
from src.tools.spec_tools import analyze_specification, extract_features, generate_test_plan
from src.tools.uvm_tools import generate_uvm
from src.tools.assertion_tools import generate_sva_assertions
from src.tools.debug_tools import analyze_simulation_log
from src.tools.coverage_tools import collect_coverage

def test_analyze_specification():
    result = analyze_specification("UART spec")
    data = json.loads(result)
    assert "features" in data
    assert "interfaces" in data

def test_extract_features():
    result = extract_features("spec")
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
