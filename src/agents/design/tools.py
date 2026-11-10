"""Design 工具集 —— 只读写 `<run>/rtl/`，给 Design 工具循环用。

设计专家最容易“越权改文件”，所以这里的工具刻意做成**窄沙箱**：
  · read_file / list_rtl 只能看 run 目录；
  · write_file 只能写 `<run>/rtl/*.sv`；
  · check_rtl 只做纯代码的 module/文件统计，不跑 EDA。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List


class _Tool:
    name = ""
    description = ""

    def invoke(self, args: Dict[str, Any]) -> str:
        return self._run(args or {})

    def _run(self, args: Dict[str, Any]) -> str:
        raise NotImplementedError


class ReadFileTool(_Tool):
    name = "read_file"
    description = "读取 run 目录内的文本文件；path 相对 run 根目录"

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _run(self, args):
        path = (self.root / str(args.get("path") or "")).resolve()
        if not str(path).startswith(str(self.root)):
            return json.dumps({"error": "path escapes run root"})
        if not path.is_file():
            return json.dumps({"error": f"not found: {path.name}"})
        return path.read_text(encoding="utf-8", errors="replace")[:20000]


class WriteRTLTool(_Tool):
    name = "write_file"
    description = "写入/覆盖 <run>/rtl/*.sv；参数 path + content"

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.rtl = self.root / "rtl"

    def _run(self, args):
        rel = str(args.get("path") or args.get("file") or "")
        content = str(args.get("content") or "")
        if not rel or not content:
            return json.dumps({"error": "path and content are required"})
        path = (self.rtl / rel.lstrip("/\\")).resolve()
        if not str(path).startswith(str(self.rtl)) or path.suffix != ".sv":
            return json.dumps({"error": "only <run>/rtl/*.sv is writable"})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return json.dumps({"ok": True, "path": path.relative_to(self.root).as_posix(),
                           "bytes": len(content.encode("utf-8"))})


class ListRTLTool(_Tool):
    name = "list_rtl"
    description = "列出 <run>/rtl/*.sv"

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.rtl = self.root / "rtl"

    def _run(self, args):
        files = sorted(self.rtl.glob("*.sv")) if self.rtl.is_dir() else []
        return json.dumps({"files": [p.name for p in files], "count": len(files)})


class CheckRTLTool(_Tool):
    name = "check_rtl"
    description = "纯代码检查 RTL：文件数 + module 名，不跑编译"

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.rtl = self.root / "rtl"

    def _run(self, args):
        files = sorted(self.rtl.glob("*.sv")) if self.rtl.is_dir() else []
        modules: List[str] = []
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace")
            modules.extend(re.findall(r"\bmodule\s+(\w+)", text))
        return json.dumps({
            "rtl_present": bool(files),
            "files": [p.name for p in files],
            "modules": sorted(set(modules)),
        }, ensure_ascii=False)


def build_design_tools(root: str | Path) -> List[Any]:
    root = Path(root)
    return [ReadFileTool(root), WriteRTLTool(root), ListRTLTool(root),
            CheckRTLTool(root)]


__all__ = ["build_design_tools"]
