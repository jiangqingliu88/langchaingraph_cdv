"""CLI 共享底座 —— 退出码与无状态 helper 只有一处定义。"""
from __future__ import annotations

import hashlib

from src.cli import commands, common


def test_exit_codes_are_defined_once_and_reexported():
    assert common.EXIT_OK == 0 and common.EXIT_USAGE == 2
    assert commands.EXIT_WAITING is common.EXIT_WAITING
    assert commands.EXIT_LAYER_VIOLATION is common.EXIT_LAYER_VIOLATION
    assert commands.EXIT_STRICT is common.EXIT_STRICT


def test_helpers_are_reexported_for_cmd_modules():
    for name in ("_extract_requirements_from_md", "_get_git_info",
                 "_output_junit", "_output_gitlab_ci",
                 "_sha256_path", "_approver_name"):
        assert getattr(commands, name) is getattr(common, name)


def test_requirement_extraction_keeps_line_numbers():
    text = "intro\n**REQ_A**\n\n**REQ_B**"
    assert common._extract_requirements_from_md(text) == [
        {"id": "REQ_A", "line": 2}, {"id": "REQ_B", "line": 4}]


def test_sha256_path_and_missing_file(tmp_path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"hello")
    assert common._sha256_path(p) == hashlib.sha256(b"hello").hexdigest()
    assert common._sha256_path(tmp_path / "missing") == ""
