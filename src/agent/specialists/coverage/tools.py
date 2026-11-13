"""Coverage 工具集 —— 只读 run 的覆盖率报告，最多写一份 agent 备注。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


class _Tool:
    name = ""
    description = ""

    def invoke(self, args: Dict[str, Any]) -> str:
        return self._run(args or {})

    def _run(self, args: Dict[str, Any]) -> str:
        raise NotImplementedError


class _RootTool(_Tool):
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _inside(self, path: Path) -> bool:
        return str(path.resolve()).startswith(str(self.root))


class ReadCoverageTool(_RootTool):
    name = "read_coverage"
    description = "读取 <run>/sim/coverage/coverage_result.json 或 <run>/coverage/coverage_result.json"

    def _run(self, args):
        for rel in ("sim/coverage/coverage_result.json",
                    "coverage/coverage_result.json"):
            path = (self.root / rel).resolve()
            if path.is_file() and self._inside(path):
                return path.read_text(encoding="utf-8", errors="replace")[:20000]
        return json.dumps({"error": "coverage_result.json not found"})


class ListCoverageFilesTool(_RootTool):
    name = "list_coverage_files"
    description = "列出 run 下的 coverage / sim/coverage 文件"

    def _run(self, args):
        files = []
        for sub in ("coverage", "sim/coverage"):
            base = self.root / sub
            if base.is_dir():
                files.extend(p.relative_to(self.root).as_posix()
                             for p in sorted(base.rglob("*")) if p.is_file())
        return json.dumps({"files": files[:200], "count": len(files)})


class ReadFileTool(_RootTool):
    name = "read_file"
    description = "读取 run 内文本文件；path 相对 run 根目录"

    def _run(self, args):
        path = (self.root / str(args.get("path") or "")).resolve()
        if not self._inside(path) or not path.is_file():
            return json.dumps({"error": "not found or escapes run root"})
        return path.read_text(encoding="utf-8", errors="replace")[:20000]


class WriteNoteTool(_RootTool):
    name = "write_note"
    description = "写 <run>/coverage/agent_notes.md（只允许这一个文件）"

    def _run(self, args):
        content = str(args.get("content") or "")
        if not content:
            return json.dumps({"error": "content required"})
        path = (self.root / "coverage" / "agent_notes.md").resolve()
        if not self._inside(path):
            return json.dumps({"error": "path escapes run root"})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return json.dumps({"ok": True, "path": "coverage/agent_notes.md"})


def build_coverage_tools(root: str | Path) -> List[Any]:
    root = Path(root)
    return [ReadCoverageTool(root), ListCoverageFilesTool(root),
            ReadFileTool(root), WriteNoteTool(root)]


__all__ = ["build_coverage_tools"]
