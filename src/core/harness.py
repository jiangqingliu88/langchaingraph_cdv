"""
Harness — 执行安全带：快照 + 超时 + 中断恢复 + 退避重试

位置: PipelineExecutionService → Harness → StepExecutor → Agent
      Harness 不替代 StepExecutor，而是包裹它，添加安全保护层。

Claude Code 的 Harness 概念:
  - 每次 tool_call 前 snapshot
  - tool_call 超时或出错 → restore snapshot → retry
  - 用户中断修改代码 → 检测变更 → 从变更点恢复

SignOffAI 适配:
  - phase 级 snapshot（非 tool_call 级，IC 验证的 phase 比 Claude 的 tool_call 粗）
  - 文件级快照（记录 output/ 下的文件 hash 列表）
  - 人工中断标记文件（.harness_pause → 暂停管线）
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from copy import deepcopy

import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# Snapshot — 可恢复的检查点
# ═══════════════════════════════════════════════════════════════

@dataclass
class FileManifest:
    """文件快照: 路径 → hash，用于检测人工修改"""
    path: str
    hash: str
    size: int
    mtime: float


@dataclass
class PhaseSnapshot:
    """单个阶段的完整快照"""
    phase_name: str
    phase_index: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    ctx_copy: dict = field(default_factory=dict)
    file_manifest: List[FileManifest] = field(default_factory=list)
    scores: Dict[str, int] = field(default_factory=dict)
    results: Dict[str, str] = field(default_factory=dict)


def _hash_file(path: Path) -> str:
    """快速 hash 一个文件"""
    if not path.exists():
        return ""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()[:16]


def _scan_files(root: Path) -> List[FileManifest]:
    """扫描目录下的所有文件，生成 manifest"""
    if not root.exists():
        return []
    manifest = []
    for f in sorted(root.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            manifest.append(FileManifest(
                path=str(f.relative_to(root)),
                hash=_hash_file(f),
                size=f.stat().st_size,
                mtime=f.stat().st_mtime,
            ))
    return manifest


def _diff_manifests(before: List[FileManifest], after: List[FileManifest]) -> dict:
    """比较两个文件快照，检测变更"""
    before_map = {f.path: f.hash for f in before}
    after_map = {f.path: f.hash for f in after}

    added = [p for p in after_map if p not in before_map]
    removed = [p for p in before_map if p not in after_map]
    modified = [p for p in before_map if p in after_map and before_map[p] != after_map[p]]
    unchanged = [p for p in before_map if p in after_map and before_map[p] == after_map[p]]

    return {
        "added": added, "removed": removed, "modified": modified,
        "unchanged_count": len(unchanged),
        "human_intervention": len(added) > 0 or len(modified) > 0,
    }


# ═══════════════════════════════════════════════════════════════
# Harness — 安全执行包装器
# ═══════════════════════════════════════════════════════════════

class Harness:
    """执行安全带：快照 + 超时 + 中断恢复 + 退避重试

    用法:
      harness = Harness(output_root="output/v1")
      snapshot = harness.snapshot(phase_name, phase_index, ctx, results, scores)

      try:
          result = await harness.run_with_timeout(step_executor.execute, task_input, timeout=600)
      except HarnessTimeout:
          harness.restore(snapshot)  # 恢复快照
          # 重试或升级
    """

    # 文件标记 — 放在 output_root 下，人工创建即可触发中断
    PAUSE_MARKER = ".harness_pause"
    ABORT_MARKER = ".harness_abort"

    def __init__(self, output_root: str = "output",
                 max_retries: int = 3, base_timeout: int = 600,
                 backoff_base: float = 2.0):
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir = self.output_root / ".harness_snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        self.max_retries = max_retries
        self.base_timeout = base_timeout
        self.backoff_base = backoff_base

        self.snapshots: List[PhaseSnapshot] = []
        self.interrupted = False
        self.interrupt_phase = ""
        self.human_modifications: Dict[str, dict] = {}  # phase → diff

    # ── 快照 ──

    def snapshot(self, phase_name: str, phase_index: int,
                 ctx, results: dict, scores: dict) -> PhaseSnapshot:
        """创建阶段快照，保存到磁盘。"""
        # 复制 ctx
        ctx_copy = {}
        if hasattr(ctx, 'snapshot'):
            ctx_copy = ctx.snapshot()
        elif hasattr(ctx, '_data'):
            ctx_copy = {k: e.value for k, e in ctx._data.items()}

        # 文件快照
        file_manifest = _scan_files(self.output_root)

        snap = PhaseSnapshot(
            phase_name=phase_name,
            phase_index=phase_index,
            ctx_copy=ctx_copy,
            file_manifest=file_manifest,
            scores=deepcopy(scores),
            results=deepcopy(results),
        )
        self.snapshots.append(snap)

        # 持久化到磁盘
        snap_path = self.snapshots_dir / f"snap_{phase_index:02d}_{phase_name}.json"
        try:
            snap_path.write_text(
                json.dumps({
                    "phase_name": phase_name, "phase_index": phase_index,
                    "timestamp": snap.timestamp,
                    "ctx_keys": list(ctx_copy.keys()),
                    "file_count": len(file_manifest),
                    "scores": scores,
                }, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Snapshot save failed: {e}")

        return snap

    def restore(self, snapshot: PhaseSnapshot) -> dict:
        """从快照恢复 — 返回恢复信息。"""
        # 检测文件变更（人工可能修改了代码）
        current_files = _scan_files(self.output_root)
        diff = _diff_manifests(snapshot.file_manifest, current_files)

        self.human_modifications[snapshot.phase_name] = diff

        if diff["human_intervention"]:
            logger.info(f"Harness: detected human intervention in phase '{snapshot.phase_name}'",
                        added=len(diff["added"]), modified=len(diff["modified"]))
            self.interrupted = True
            self.interrupt_phase = snapshot.phase_name

        return {
            "snapshot_phase": snapshot.phase_name,
            "timestamp": snapshot.timestamp,
            "human_intervention": diff["human_intervention"],
            "files_modified": diff["modified"],
            "files_added": diff["added"],
            "can_resume": True,
        }

    def check_interrupt(self) -> Optional[str]:
        """检查人工中断标记文件。

        如果 output_root/.harness_pause 存在 → 暂停
        如果 output_root/.harness_abort 存在 → 终止
        返回: None (继续) / "pause" / "abort"
        """
        if (self.output_root / self.ABORT_MARKER).exists():
            return "abort"
        if (self.output_root / self.PAUSE_MARKER).exists():
            return "pause"
        return None

    def clear_interrupt(self):
        """清除中断标记（人工操作完成后调用）。"""
        for marker in [self.PAUSE_MARKER, self.ABORT_MARKER]:
            path = self.output_root / marker
            if path.exists():
                path.unlink()

    # ── 超时执行 ──

    async def run_with_timeout(self, coro, *args,
                                timeout: int = None, phase_name: str = "",
                                **kwargs) -> Any:
        """执行协程，超时则抛 HarnessTimeout。

        用法:
          result = await harness.run_with_timeout(
              executor.execute, task_input,
              timeout=600, phase_name="UVM"
          )
        """
        timeout = timeout or self.base_timeout
        try:
            result = await asyncio.wait_for(coro(*args, **kwargs), timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.error(f"Harness timeout: {phase_name} exceeded {timeout}s")
            raise HarnessTimeout(phase_name, timeout)

    # ── 退避重试 ──

    async def execute_with_retry(self, executor_fn: Callable, task_input: Any,
                                  phase_name: str = "", timeout: int = None) -> Tuple[Any, int]:
        """执行 + 超时 + 指数退避重试。

        返回: (result, attempts)
        """
        timeout = timeout or self.base_timeout
        last_error = None

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                delay = self.backoff_base ** (attempt - 1)
                logger.info(f"Harness retry: {phase_name} attempt {attempt}/{self.max_retries}, "
                           f"backoff {delay:.1f}s")
                await asyncio.sleep(delay)

            # 检查中断标记
            interrupt = self.check_interrupt()
            if interrupt == "abort":
                raise HarnessInterrupted(phase_name, "abort marker found")
            if interrupt == "pause":
                logger.info(f"Harness: paused before {phase_name} (human intervention)")
                self.interrupted = True
                self.interrupt_phase = phase_name
                # 等待标记清除
                while self.check_interrupt() == "pause":
                    await asyncio.sleep(2)
                logger.info(f"Harness: pause marker cleared, resuming {phase_name}")

            try:
                result = await self.run_with_timeout(
                    executor_fn, task_input,
                    timeout=timeout, phase_name=phase_name
                )
                return result, attempt
            except HarnessTimeout as e:
                last_error = e
                if attempt >= self.max_retries:
                    raise
            except Exception as e:
                last_error = e
                if attempt >= self.max_retries:
                    raise

        raise last_error or RuntimeError(f"Harness: {phase_name} failed after {self.max_retries} retries")

    # ── 中断恢复入口 ──

    def load_last_snapshot(self) -> Optional[PhaseSnapshot]:
        """从磁盘加载最近的快照（恢复用）。"""
        snap_files = sorted(self.snapshots_dir.glob("snap_*.json"), reverse=True)
        if not snap_files:
            return None
        try:
            data = json.loads(snap_files[0].read_text(encoding="utf-8"))
            return PhaseSnapshot(
                phase_name=data["phase_name"],
                phase_index=data["phase_index"],
                timestamp=data["timestamp"],
                scores=data.get("scores", {}),
                results=data.get("results", {}),
            )
        except Exception:
            return None

    def can_resume(self) -> bool:
        """检查是否有可恢复的快照"""
        return len(list(self.snapshots_dir.glob("snap_*.json"))) > 0

    def resume_info(self) -> dict:
        """返回恢复信息供 CLI 展示"""
        snap = self.load_last_snapshot()
        if not snap:
            return {"can_resume": False}
        return {
            "can_resume": True,
            "last_phase": snap.phase_name,
            "last_index": snap.phase_index,
            "timestamp": snap.timestamp,
            "completed_phases": list(snap.scores.keys()),
        }

    def summary(self) -> dict:
        """Harness 运行摘要"""
        return {
            "snapshots_taken": len(self.snapshots),
            "interrupted": self.interrupted,
            "interrupt_phase": self.interrupt_phase,
            "human_interventions": {
                phase: {
                    "files_modified": len(diff["modified"]),
                    "files_added": len(diff["added"]),
                }
                for phase, diff in self.human_modifications.items()
                if diff.get("human_intervention")
            },
            "snapshot_dir": str(self.snapshots_dir),
        }


# ═══════════════════════════════════════════════════════════════
# 异常类
# ═══════════════════════════════════════════════════════════════

class HarnessTimeout(Exception):
    """阶段执行超时"""
    def __init__(self, phase: str, timeout: int):
        self.phase = phase
        self.timeout = timeout
        super().__init__(f"Phase '{phase}' timed out after {timeout}s")


class HarnessInterrupted(Exception):
    """人工中断"""
    def __init__(self, phase: str, reason: str):
        self.phase = phase
        self.reason = reason
        super().__init__(f"Phase '{phase}' interrupted: {reason}")
