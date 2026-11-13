"""Playbook 文件系统 —— `.playbooks/*.md` 发现、读取、注入 system prompt。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from src.runtime_plane.workspace_manager import WorkspaceZones


@dataclass
class Playbook:
    name: str
    description: str
    path: Path
    content: str


def _parse(text: str) -> tuple[str, str, str]:
    """极简 frontmatter：`--- name/description ---`；没有就用首行标题。"""
    body = text.lstrip("﻿")
    if body.startswith("---"):
        _, _, rest = body.partition("---")
        meta, sep, content = rest.partition("\n---")
        if sep:
            name = description = ""
            for line in meta.splitlines():
                key, _, value = line.partition(":")
                if key.strip() == "name":
                    name = value.strip()
                elif key.strip() == "description":
                    description = value.strip()
            return name, description, content.lstrip("\n")
    first = next((line.strip("# ").strip() for line in body.splitlines()
                  if line.strip()), "")
    return first, "", body


class PlaybookLibrary:
    def __init__(self, zones: WorkspaceZones, dirs: List[Path] | None = None):
        self.dirs = dirs or [zones.root / ".playbooks"]
        self._playbooks: Dict[str, Playbook] = {}
        self.reload()

    def reload(self) -> None:
        self._playbooks.clear()
        for base in self.dirs:
            if not base.is_dir():
                continue
            for path in sorted(base.glob("*.md")):
                name, description, content = _parse(
                    path.read_text(encoding="utf-8", errors="replace"))
                name = name or path.stem
                self._playbooks[name] = Playbook(name, description or name, path, content)

    def names(self) -> List[str]:
        return sorted(self._playbooks)

    def read(self, name: str) -> str:
        skill = self._playbooks.get(name)
        if skill is None:
            raise KeyError(f"没有 skill：{name}（已有：{', '.join(self.names())}）")
        return skill.content

    def prompt_section(self, limit: int = 4000) -> str:
        if not self._playbooks:
            return ""
        lines = ["Available playbooks (call `read_playbook(name)` for full text):"]
        for name in self.names():
            skill = self._playbooks[name]
            lines.append(f"- {name}: {skill.description}")
        return "\n".join(lines)[:limit]
