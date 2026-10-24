"""Tests for uvm tool package"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent)).parent
from src.tools.generation.uvm_tools import generate_uvm


def test_import_generate_uvm():
    """Test that generate_uvm is importable from uvm package"""
    assert generate_uvm is not None
    assert callable(generate_uvm)
