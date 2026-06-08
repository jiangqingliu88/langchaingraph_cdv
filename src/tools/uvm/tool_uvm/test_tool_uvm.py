"""Tests for tool_uvm"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))
from src.tools.uvm.tool_uvm import UVMGenerator, JinjaRenderer, YAMLLoader


def test_imports():
    """Test that key classes are importable"""
    assert UVMGenerator is not None
    assert JinjaRenderer is not None
    assert YAMLLoader is not None
