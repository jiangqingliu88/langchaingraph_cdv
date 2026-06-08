"""Tests for testcase tool"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.tools.testcase import TestCaseGenerator, parse_test_points, map_policies_to_tests


def test_imports():
    """Test that key symbols are importable"""
    assert TestCaseGenerator is not None
    assert parse_test_points is not None
    assert map_policies_to_tests is not None
