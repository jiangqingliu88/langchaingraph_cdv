"""Tests for compilesim tool"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.tools.compilesim import RegressionRunner


def test_regression_runner_import():
    """Test that RegressionRunner is importable"""
    assert RegressionRunner is not None
