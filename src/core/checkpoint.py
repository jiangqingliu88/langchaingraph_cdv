"""
流水线暂停/恢复/断点续跑机制

PipelineCheckpoint: 保存完整执行状态，支持从中断处恢复
"""
from __future__ import annotations

import json, pickle
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class PipelineCheckpoint:
    """流水线检查点"""
    checkpoint_id: str = ""
    run_id: str = ""
    workflow: str = ""

    # 执行进度
    current_phase: str = ""         # 当前阶段名称
    current_phase_index: int = 0    # 当前阶段序号 (0-based)
    total_phases: int = 0
    completed_phases: list[str] = field(default_factory=list)

    # 阶段内部进度
    step_index: int = 0             # 阶段内子步骤序号
    step_name: str = ""             # 子步骤名称

    # 上下文快照
    ctx_snapshot: dict = field(default_factory=dict)
    agent_states: dict = field(default_factory=dict)    # agent_role -> state

    # 元数据
    status: str = "running"         # running / paused / resumed / completed
    created_at: str = ""
    updated_at: str = ""
    resume_count: int = 0           # 恢复次数

    def to_dict(self) -> dict:
        return {
            "checkpoint_id": self.checkpoint_id,
            "run_id": self.run_id, "workflow": self.workflow,
            "current_phase": self.current_phase,
            "current_phase_index": self.current_phase_index,
            "total_phases": self.total_phases,
            "completed_phases": self.completed_phases,
            "step_index": self.step_index, "step_name": self.step_name,
            "status": self.status,
            "created_at": self.created_at, "updated_at": self.updated_at,
            "resume_count": self.resume_count,
        }


class CheckpointManager:
    """检查点管理器"""

    def __init__(self, output_root: str = "output"):
        self.output_root = Path(output_root)
        self._checkpoints: dict[str, PipelineCheckpoint] = {}
        self._checkpoint_dir = self.output_root / "checkpoints"
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def create(self, run_id: str, workflow: str, total_phases: int,
               ctx: dict = None, agent_states: dict = None) -> PipelineCheckpoint:
        """创建检查点"""
        cid = f"ckpt_{run_id}"
        cp = PipelineCheckpoint(
            checkpoint_id=cid,
            run_id=run_id,
            workflow=workflow,
            total_phases=total_phases,
            ctx_snapshot=ctx or {},
            agent_states=agent_states or {},
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        self._checkpoints[cid] = cp
        self._save_to_disk(cp)
        return cp

    def update(self, run_id: str, phase_name: str = "", phase_index: int = None,
               step_name: str = "", step_index: int = 0, ctx: dict = None):
        """更新检查点进度"""
        cid = f"ckpt_{run_id}"
        if cid not in self._checkpoints:
            return
        cp = self._checkpoints[cid]
        if phase_name:
            cp.current_phase = phase_name
            cp.completed_phases.append(phase_name)
        if phase_index is not None:
            cp.current_phase_index = phase_index
        if step_name:
            cp.step_name = step_name
        cp.step_index = step_index
        if ctx:
            cp.ctx_snapshot.update(ctx)
        cp.updated_at = datetime.now().isoformat()
        self._save_to_disk(cp)

    def pause(self, run_id: str) -> bool:
        """暂停流水线"""
        cid = f"ckpt_{run_id}"
        if cid not in self._checkpoints:
            return False
        self._checkpoints[cid].status = "paused"
        self._checkpoints[cid].updated_at = datetime.now().isoformat()
        self._save_to_disk(self._checkpoints[cid])
        return True

    def resume(self, run_id: str) -> Optional[PipelineCheckpoint]:
        """恢复流水线"""
        cid = f"ckpt_{run_id}"
        # 先查内存
        if cid in self._checkpoints:
            cp = self._checkpoints[cid]
            cp.status = "resumed"
            cp.resume_count += 1
            cp.updated_at = datetime.now().isoformat()
            return cp
        # 从磁盘加载
        cp = self._load_from_disk(cid)
        if cp:
            cp.status = "resumed"
            cp.resume_count += 1
            self._checkpoints[cid] = cp
            return cp
        return None

    def get(self, run_id: str) -> Optional[PipelineCheckpoint]:
        """获取检查点"""
        cid = f"ckpt_{run_id}"
        if cid in self._checkpoints:
            return self._checkpoints[cid]
        return self._load_from_disk(cid)

    def list_paused(self) -> list[dict]:
        """列出所有暂停的流水线"""
        paused = []
        for f in sorted(self._checkpoint_dir.glob("ckpt_*.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("status") == "paused":
                    paused.append({
                        "run_id": data.get("run_id"),
                        "workflow": data.get("workflow"),
                        "current_phase": data.get("current_phase"),
                        "progress": f"{data.get('current_phase_index',0)+1}/{data.get('total_phases',0)}",
                        "paused_at": data.get("updated_at"),
                        "resume_count": data.get("resume_count", 0),
                    })
            except Exception:
                pass
        return paused

    def _save_to_disk(self, cp: PipelineCheckpoint):
        path = self._checkpoint_dir / f"{cp.checkpoint_id}.json"
        path.write_text(json.dumps(cp.to_dict(), indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")

    def _load_from_disk(self, checkpoint_id: str) -> Optional[PipelineCheckpoint]:
        path = self._checkpoint_dir / f"{checkpoint_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return PipelineCheckpoint(**data)
        except Exception:
            return None


# ── 全局 ──
_checkpoint_mgr: Optional[CheckpointManager] = None

def get_checkpoint_mgr() -> CheckpointManager:
    global _checkpoint_mgr
    if _checkpoint_mgr is None:
        _checkpoint_mgr = CheckpointManager()
    return _checkpoint_mgr
