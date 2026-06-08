"""Tests for coverage_tools"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.tools.coverage_tools import collect_coverage


def test_collect_coverage():
    result = collect_coverage("all")
    assert result is not None
