"""Tests for spec_tools"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
from src.layers.l3_decision.spec_tools import analyze_specification, extract_features, generate_test_plan


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
