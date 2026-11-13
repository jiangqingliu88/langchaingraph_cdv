"""ProjectMemory —— 工程长期记忆的**紧凑投影**，不把整个仓库塞进上下文。

只提取：
  · 顶层目录与关键文档标题；
  · 语言/构建入口（pyproject / package.json / Makefile）；
  · specs 项目清单；
  · 工具链开关（QuestaSim / Python）。
缓存在 `.signoffai/project_context.md`；仓库结构变化（mtime）时重建。
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List

from src.core.runtime.atomic import atomic_write_text

from src.runtime.workspace_manager import WorkspaceZones

_MAX_HEADINGS = 40


def _headings(path: Path, limit: int = _MAX_HEADINGS) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [line.strip() for line in text.splitlines()
            if re.match(r"^#{1,3}\s+", line)][:limit]


def _dirs(root: Path, limit: int = 40) -> List[str]:
    try:
        return sorted(p.name + ("/" if p.is_dir() else "")
                      for p in root.iterdir()
                      if not p.name.startswith((".", "__"))
                      and p.name not in ("venv", "node_modules", "output"))[:limit]
    except OSError:
        return []


class ProjectMemory:
    def __init__(self, zones: WorkspaceZones, project_root: str | Path | None = None):
        self.zones = zones
        self.root = Path(project_root or zones.project_root()).expanduser().resolve()
        self.path = zones.harness_dir / "project_context.md"

    def _stale(self) -> bool:
        try:
            cache = self.path.stat().st_mtime
            if time.time() - cache > 24 * 3600:
                return True
            # 顶层目录/关键文件变化视为过期
            for name in ("pyproject.toml", "ARCHITECTURE.md", "README.md", "specs"):
                path = self.root / name
                if path.exists() and path.stat().st_mtime > cache:
                    return True
        except OSError:
            return True
        return False

    def build(self) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "project_root": str(self.root),
            "top_level": _dirs(self.root),
            "specs": sorted(p.name for p in (self.root / "specs").iterdir()
                            if p.is_dir()) if (self.root / "specs").is_dir() else [],
            "architecture": _headings(self.root / "ARCHITECTURE.md")
            or _headings(self.root / "ARCHITECTURE_CURRENT.md"),
            "readme": _headings(self.root / "README.md", 12),
            "toolchain": {
                "python": os.environ.get("PYTHON_VERSION", ""),
                "questa": bool(os.environ.get("QUESTA_HOME")
                               or os.environ.get("SIGNOFFAI_QUESTA_HOME")),
            },
        }
        return doc

    def render(self, doc: Dict[str, Any] | None = None) -> str:
        doc = doc or self.build()
        lines = ["# PROJECT CONTEXT", "", f"root: {doc.get('project_root')}"]
        if doc.get("specs"):
            lines += ["", "## SPECS", *[f"- {s}" for s in doc["specs"]]]
        if doc.get("top_level"):
            lines += ["", "## TOP-LEVEL", "- " + " ".join(doc["top_level"][:20])]
        if doc.get("architecture"):
            lines += ["", "## ARCHITECTURE HEADINGS",
                      *[f"- {h}" for h in doc["architecture"][:20]]]
        return "\n".join(lines).strip() + "\n"

    def load_or_build(self) -> str:
        if not self.path.is_file() or self._stale():
            text = self.render()
            self.zones.harness_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.path, text)
            return text
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return self.render()


__all__ = ["ProjectMemory"]
