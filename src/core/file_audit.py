"""
文件级证据链 —— git diff + 修改理由统一记录

无论修改了什么文件（RTL/Env/Model/TB），都记录:
  - 文件路径
  - git diff（修改内容）
  - 修改理由（为什么改）
  - 修改者（哪个 Agent 触发的）
  - SHA256 hash（防篡改）

这是"统一证据链"支柱的核心实现。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class FileChangeRecord:
    """单次文件修改记录"""
    file_path: str
    reason: str
    agent: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    git_diff: str = ""
    content_hash: str = ""
    hash: str = ""


class FileAuditTrail:
    """文件级审计链：记录所有文件修改的 git diff + 理由"""

    def __init__(self, repo_root: str = "."):
        self.repo_root = Path(repo_root)
        self.records: List[FileChangeRecord] = []
        self.prev_hash = ""

    def record(self, file_path: str, reason: str, agent: str = "") -> FileChangeRecord:
        """记录一次文件修改（git diff + 内容 hash + 理由 + hash 链）。"""
        diff = self._git_diff(file_path)
        content_hash = self._content_hash(file_path)
        rec = FileChangeRecord(
            file_path=file_path, reason=reason, agent=agent,
            git_diff=diff, content_hash=content_hash,
        )
        # hash 链：文件 + 内容 hash + diff + 理由 + agent + 前一个 hash
        content = json.dumps({
            "file": rec.file_path, "reason": rec.reason,
            "agent": rec.agent, "diff": rec.git_diff,
            "content_hash": rec.content_hash,
        }, sort_keys=True, default=str) + self.prev_hash
        rec.hash = hashlib.sha256(content.encode()).hexdigest()
        self.prev_hash = rec.hash
        self.records.append(rec)
        return rec

    def _git_diff(self, file_path: str) -> str:
        """用 git diff 获取文件修改内容。"""
        try:
            r = subprocess.run(
                ["git", "diff", "--", file_path],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10, cwd=str(self.repo_root),
            )
            return r.stdout if r.returncode == 0 else ""
        except Exception:
            return ""

    def _content_hash(self, file_path: str) -> str:
        """计算文件内容 SHA256（新文件 git diff 为空，但内容 hash 仍可防篡改）。"""
        try:
            p = Path(file_path)
            if p.is_file():
                return hashlib.sha256(p.read_bytes()).hexdigest()
        except Exception:
            pass
        return ""

    def to_dict(self) -> dict:
        return {
            "records": [asdict(r) for r in self.records],
            "final_hash": self.prev_hash,
            "total_changes": len(self.records),
        }

    def verify(self) -> bool:
        """验证审计链完整性（含文件内容 hash 防篡改）。"""
        prev = ""
        for r in self.records:
            content = json.dumps({
                "file": r.file_path, "reason": r.reason,
                "agent": r.agent, "diff": r.git_diff,
                "content_hash": r.content_hash,
            }, sort_keys=True, default=str) + prev
            if r.hash != hashlib.sha256(content.encode()).hexdigest():
                return False
            prev = r.hash
        return True


# 全局单例（可选）
_global_trail: Optional[FileAuditTrail] = None


def get_file_audit_trail(repo_root: str = ".") -> FileAuditTrail:
    """获取全局文件审计链单例。"""
    global _global_trail
    if _global_trail is None:
        _global_trail = FileAuditTrail(repo_root)
    return _global_trail


def record_file_change(file_path: str, reason: str, agent: str = "",
                       repo_root: str = ".") -> dict:
    """便捷入口：记录一次文件修改。"""
    trail = get_file_audit_trail(repo_root)
    rec = trail.record(file_path, reason, agent)
    return asdict(rec)
