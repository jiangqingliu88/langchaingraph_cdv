"""工具板块（generation / checking / execution / flow / integration / common / humanview）。

钉的是**组织不变量**：
  ① 每个工具包只属于一个板块；
  ② 没有未登记的工具包；
  ③ 板块包可导入，且懒加载能拿到对应包。
"""
from __future__ import annotations

import importlib
from pathlib import Path

from src.runtime_plane.tools import boards


def _tool_dirs() -> set:
    root = Path("src/runtime_plane/tools")
    out = set()
    for p in root.iterdir():
        if not p.is_dir() or p.name.startswith("__"):
            continue
        if p.name in boards.BOARDS:          # 板块包本身
            continue
        out.add(p.name)
    return out


def test_every_tool_package_has_exactly_one_board():
    seen = {}
    for board, pkgs in boards.BOARDS.items():
        for pkg in pkgs:
            assert pkg not in seen, f"{pkg} 同时登记在 {seen[pkg]} 与 {board}"
            seen[pkg] = board
    assert seen, "板块表是空的"


def test_no_unregistered_tool_package():
    missing = _tool_dirs() - set(boards.BOARD_OF)
    assert not missing, f"这些工具包没有登记板块：{sorted(missing)}"


def test_packages_live_under_their_board_directory():
    """板块表不仅声明职责，还钉住**物理位置**。"""
    root = Path("src/runtime_plane/tools")
    wrong = []
    for board, pkgs in boards.BOARDS.items():
        for pkg in pkgs:
            expected = (Path("src/generation_plane") / pkg if board == "generation"
                        else root / board / pkg)
            if not expected.is_dir():
                wrong.append(f"{pkg} 应在 {expected}")
    assert not wrong, wrong


def test_board_packages_are_importable_and_lazy_load():
    for board in boards.BOARDS:
        mod = importlib.import_module(
            "src.generation_plane" if board == "generation" else f"src.runtime_plane.tools.{board}")
        for pkg in boards.BOARDS[board]:
            assert getattr(mod, pkg) is not None
