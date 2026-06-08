"""Tests for assertion_tools"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.tools.assertion_tools import generate_sva_assertions


def test_generate_sva_assertions():
    result = generate_sva_assertions("{}")
    data = json.loads(result)
    assert "assertions" in data
