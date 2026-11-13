"""
Artifacts 机制 —— Agent 生成的产物管理（对齐 Claude Code）

每个产物有: 类型、版本、hash、创建时间、来源 Agent
可追溯、可导出、可版本化。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Artifact:
    """单个产物"""
    name: str                       # 产物名（如 apb_uart.sv）
    type: str                       # 类型: rtl | testbench | model | report | coverage
    content: str = ""               # 内容（或文件路径）
    agent: str = ""                 # 生成者 Agent
    version: str = "v1"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.hash:
            self.hash = hashlib.sha256(self.content.encode()).hexdigest()[:16]


class ArtifactRegistry:
    """产物注册表：记录、查询、导出所有 Agent 产物"""

    def __init__(self, artifacts_dir: str = "artifacts"):
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts: List[Artifact] = []

    def add(self, name: str, type: str, content: str, agent: str,
            version: str = "v1", metadata: Dict = None) -> Artifact:
        """注册一个产物。"""
        art = Artifact(name=name, type=type, content=content, agent=agent,
                       version=version, metadata=metadata or {})
        self._artifacts.append(art)
        self._persist(art)
        return art

    def _persist(self, art: Artifact):
        """持久化产物到磁盘。"""
        type_dir = self.artifacts_dir / art.type
        type_dir.mkdir(parents=True, exist_ok=True)
        fpath = type_dir / f"{art.name}_{art.version}"
        fpath.write_text(art.content, encoding="utf-8")
        # 更新索引
        index = self.artifacts_dir / "index.json"
        index.write_text(json.dumps({
            "artifacts": [asdict(a) for a in self._artifacts],
            "total": len(self._artifacts),
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_by_type(self, type: str) -> List[Artifact]:
        return [a for a in self._artifacts if a.type == type]

    def list_by_agent(self, agent: str) -> List[Artifact]:
        return [a for a in self._artifacts if a.agent == agent]

    def get(self, name: str) -> Optional[Artifact]:
        for a in self._artifacts:
            if a.name == name:
                return a
        return None

    def to_dict(self) -> dict:
        return {
            "artifacts": [asdict(a) for a in self._artifacts],
            "total": len(self._artifacts),
        }


# 全局单例
_global_registry: Optional[ArtifactRegistry] = None


def get_artifact_registry(artifacts_dir: str = "artifacts") -> ArtifactRegistry:
    global _global_registry
    if _global_registry is None:
        _global_registry = ArtifactRegistry(artifacts_dir)
    return _global_registry
