"""
虚拟文件系统（VFS）—— Agent 文件操作的覆盖层 + 事务 + 快照 + 变更追踪。

为什么需要：Agent 越来越自主（自愈/蒸馏/重构都会改文件），直接写磁盘的风险是
"改了一半崩了，留下一堆半成品"。VFS 让文件操作先发生在虚拟层，验证通过才提交，
失败则整体回滚——这正是 harness 工程里"可回滚、可隔离、可审计"的基础。

核心能力：
  1. 覆盖层（overlay）：Agent 写文件先进虚拟层，不直接碰真实磁盘
  2. 事务（transaction）：一组修改原子提交/回滚（begin → commit/rollback）
  3. 快照（snapshot）：某个时间点的文件状态，可恢复
  4. 变更追踪（diff）：所有未提交变更可查看，配合 file_audit 证据链

用法:
    from src.core.virtual_fs import VirtualFileSystem
    vfs = VirtualFileSystem("output/run_x")
    vfs.begin()                      # 开始事务
    vfs.write("rtl/dut.sv", "...")   # 虚拟写入（不落盘）
    vfs.edit("rtl/dut.sv", "a+b", "a-b")  # 精确编辑
    vfs.commit()                     # 提交到磁盘
    # 或 vfs.rollback()              # 回滚全部
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class FileChange:
    """一次文件变更记录（供证据链）。"""
    path: str
    action: str                      # write | edit | delete
    before: str = ""                 # 变更前内容（截断）
    after: str = ""                  # 变更后内容（截断）


class VirtualFileSystem:
    """虚拟文件系统：覆盖层 + 事务 + 快照 + 变更追踪。"""

    def __init__(self, root: str = "output"):
        self.root = Path(root)
        self.overlay: Dict[str, str] = {}   # rel_path → 虚拟内容（未提交）
        self.deleted: set = set()           # 虚拟删除的文件
        self._snapshots: List[Dict] = []    # 快照栈
        self._changes: List[FileChange] = []  # 当前事务的变更

    # ═══════════════════════════════════════════════════════════
    # 读 / 写 / 编辑（走虚拟层）
    # ═══════════════════════════════════════════════════════════

    def read(self, path: str) -> str:
        """读文件：虚拟层优先，回退真实磁盘。"""
        rel = self._rel(path)
        if rel in self.deleted:
            return ""
        if rel in self.overlay:
            return self.overlay[rel]
        p = self.root / rel
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace")
        return ""

    def write(self, path: str, content: str) -> None:
        """虚拟写入（不落盘），记录变更。"""
        rel = self._rel(path)
        before = self.read(rel)
        self.overlay[rel] = content
        self.deleted.discard(rel)
        self._changes.append(FileChange(path=rel, action="write",
                                        before=before[:200], after=content[:200]))

    def edit(self, path: str, old_string: str, new_string: str) -> Dict[str, Any]:
        """精确编辑（基于虚拟层内容），复用 file_editor 的冲突检测。"""
        rel = self._rel(path)
        current = self.read(rel)
        count = current.count(old_string)
        if count == 0:
            return {"success": False, "error": f"old_string 未找到（0 次匹配）"}
        if count > 1:
            return {"success": False, "error": f"old_string 不唯一（{count} 次匹配）"}
        new_content = current.replace(old_string, new_string, 1)
        self.write(rel, new_content)
        return {"success": True, "replaced": 1}

    def delete(self, path: str) -> None:
        rel = self._rel(path)
        before = self.read(rel)
        self.deleted.add(rel)
        self.overlay.pop(rel, None)
        self._changes.append(FileChange(path=rel, action="delete", before=before[:200]))

    # ═══════════════════════════════════════════════════════════
    # 事务
    # ═══════════════════════════════════════════════════════════

    def begin(self) -> None:
        """开始事务（清空未提交变更，从干净状态开始）。"""
        self._changes = []

    def commit(self) -> Dict[str, Any]:
        """提交：把虚拟层变更写入真实磁盘，返回变更数。"""
        count = 0
        for rel, content in self.overlay.items():
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content, encoding="utf-8")
            count += 1
        for rel in self.deleted:
            p = self.root / rel
            if p.exists():
                p.unlink()
                count += 1
        result = {"committed": count, "changes": [c.path for c in self._changes]}
        self.overlay.clear()
        self.deleted.clear()
        self._changes = []
        return result

    def rollback(self) -> Dict[str, Any]:
        """回滚：丢弃所有未提交的虚拟变更，返回丢弃数。"""
        result = {"rolled_back": len(self._changes),
                  "changes": [c.path for c in self._changes]}
        self.overlay.clear()
        self.deleted.clear()
        self._changes = []
        return result

    # ═══════════════════════════════════════════════════════════
    # 快照 / 恢复
    # ═══════════════════════════════════════════════════════════

    def snapshot(self) -> int:
        """保存当前覆盖层状态到快照栈，返回快照栈深度。"""
        self._snapshots.append({
            "overlay": dict(self.overlay),
            "deleted": set(self.deleted),
        })
        return len(self._snapshots)

    def restore(self) -> bool:
        """恢复到最近一个快照（pop 栈）。"""
        if not self._snapshots:
            return False
        snap = self._snapshots.pop()
        self.overlay = dict(snap["overlay"])
        self.deleted = set(snap["deleted"])
        return True

    # ═══════════════════════════════════════════════════════════
    # 变更视图 / 审计
    # ═══════════════════════════════════════════════════════════

    def diff(self) -> List[Dict[str, str]]:
        """查看当前未提交的变更（供审计）。"""
        return [{"path": c.path, "action": c.action,
                 "before": c.before, "after": c.after} for c in self._changes]

    def status(self) -> Dict[str, Any]:
        """VFS 状态：未提交变更数 + 虚拟文件数。"""
        return {
            "pending_changes": len(self._changes),
            "virtual_files": len(self.overlay),
            "virtual_deleted": len(self.deleted),
            "snapshot_depth": len(self._snapshots),
        }

    # ═══════════════════════════════════════════════════════════
    # 辅助
    # ═══════════════════════════════════════════════════════════

    def _rel(self, path: str) -> str:
        """归一化为相对路径（去掉 root 前缀）。"""
        p = Path(path)
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            return str(p)
