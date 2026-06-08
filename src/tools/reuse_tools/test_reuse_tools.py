"""Tests for reuse_tools"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from src.tools.reuse_tools import scan_environment, library_stats


def test_scan_environment():
    result = scan_environment("")
    data = json.loads(result)
    assert "summary" in data


def test_library_stats():
    result = library_stats("output/vip_library")
    data = json.loads(result)
    assert "total_components" in data
