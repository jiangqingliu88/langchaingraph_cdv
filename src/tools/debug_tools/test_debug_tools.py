"""Tests for debug_tools"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.tools.debug_tools import analyze_simulation_log


def test_analyze_simulation_log():
    result = analyze_simulation_log("test.log")
    data = json.loads(result)
    assert "errors" in data
