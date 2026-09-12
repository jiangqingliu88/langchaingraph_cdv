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
    # 链内序号：用于连续性检查。DB 侧审计链（repository.verify_audit_chain）
    # 早就有 chain_index 连续性校验，文件级链一直缺这一项。
    seq: int = -1


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
            git_diff=diff, content_hash=content_hash, seq=len(self.records),
        )
        rec.hash = self._digest(rec, self.prev_hash)
        self.prev_hash = rec.hash
        self.records.append(rec)
        return rec

    @staticmethod
    def _digest(rec: Any, prev_hash: str) -> str:
        """链哈希：文件 + 内容 hash + diff + 理由 + agent + 序号 + 前一个 hash。

        把 seq 纳入哈希，使「重排序号」也无法在不破坏链的前提下完成。
        """
        content = json.dumps({
            "file": rec.file_path if hasattr(rec, "file_path") else rec.get("file_path"),
            "reason": rec.reason if hasattr(rec, "reason") else rec.get("reason"),
            "agent": rec.agent if hasattr(rec, "agent") else rec.get("agent"),
            "diff": rec.git_diff if hasattr(rec, "git_diff") else rec.get("git_diff"),
            "content_hash": (rec.content_hash if hasattr(rec, "content_hash")
                             else rec.get("content_hash")),
            "seq": rec.seq if hasattr(rec, "seq") else rec.get("seq"),
        }, sort_keys=True, default=str) + prev_hash
        return hashlib.sha256(content.encode()).hexdigest()

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
        """验证**内存中**的审计链完整性（含序号连续性与内容 hash 防篡改）。

        注意：本方法只校验内存里的 records —— 删掉尾部记录后，链会从剩下的
        记录重新算起，依然「通过」。要发现落盘后被裁剪，请用 verify_persisted()。
        """
        prev = ""
        for i, r in enumerate(self.records):
            if r.seq != i:
                return False
            if r.hash != self._digest(r, prev):
                return False
            prev = r.hash
        return True

    @classmethod
    def verify_persisted(cls, path: str | Path) -> Dict[str, Any]:
        """从**磁盘**回读并校验审计链。

        这是与 verify() 的关键区别：verify() 等于「自己验自己」——内存里剩什么
        就验什么，尾部被删不可检测。本方法重新读盘，因此能发现：
          - index_gap     序号不连续（中间被抽走一条）
          - hash_broken   某条内容的哈希与记录不符（被改写）
          - tail_truncated final_hash 与最后一条记录不一致（尾部被裁掉）
        返回 {valid, total, final_hash, issues}。
        """
        p = Path(path)
        if not p.exists():
            return {"valid": False, "total": 0, "final_hash": "", "issues": [
                {"type": "missing", "detail": f"{p} 不存在"}]}

        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return {"valid": False, "total": 0, "final_hash": "",
                    "issues": [{"type": "unreadable", "detail": str(e)[:200]}]}

        records = data.get("records", []) or []
        issues: List[Dict[str, Any]] = []
        prev = ""
        for i, r in enumerate(records):
            if r.get("seq", i) != i:
                issues.append({"type": "index_gap", "at": i,
                               "expected": i, "actual": r.get("seq")})
            expect = cls._digest(r, prev)
            if r.get("hash") != expect:
                issues.append({"type": "hash_broken", "at": i,
                               "file": r.get("file_path")})
                break  # 链已断，后续比较无意义
            prev = r["hash"]

        # 尾部指针必须等于最后一条记录的 hash —— 删掉尾部记录会在这里暴露
        declared = data.get("final_hash", "")
        last = records[-1].get("hash") if records else ""
        if declared != last:
            issues.append({"type": "tail_truncated",
                           "final_hash": declared, "last_record_hash": last})

        return {"valid": not issues, "total": len(records),
                "final_hash": declared, "issues": issues}


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
