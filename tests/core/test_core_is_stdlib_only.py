"""core 的依赖方向：只能标准库。

`src/runtime_plane/core/registry.py` 是历史遗留（引用了不存在的 `src.runtime_plane.core.base`），不在新
架构里；守卫明确排除它，避免把死文件当成"core 可以依赖 structlog"的先例。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "core"
LEGACY = {"registry.py"}
FORBIDDEN_PREFIXES = (
    "src.runtime_plane", "langgraph", "langchain", "pydantic", "structlog",
    "src.runtime_plane.core.registry", "src.runtime_plane.core.base",
)


def _modules():
    for path in sorted(CORE.rglob("*.py")):
        if path.name in LEGACY or "__pycache__" in path.parts:
            continue
        yield path


def test_core_imports_stdlib_only():
    bad = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods.append(node.module)
            elif isinstance(node, ast.Import):
                mods.extend(a.name for a in node.names)
            for mod in mods:
                if mod.startswith(FORBIDDEN_PREFIXES):
                    bad.append((path.relative_to(ROOT).as_posix(), node.lineno, mod))
    assert not bad, bad


def test_core_does_not_import_its_own_legacy_registry():
    for path in _modules():
        text = path.read_text(encoding="utf-8")
        assert "src.runtime_plane.core.registry" not in text, path
