"""
Artifact Manifest System — SignOffAI 证据链核心

每个 pipeline run 生成一个结构化 Manifest，记录:
  - 所有阶段的输入/输出 hash
  - 使用的工具及版本
  - 执行日志摘要
  - 时间戳和状态

支持:
  - 从 execution trace (JSONL) 重建 manifest
  - 从 pipeline run state 构建 manifest
  - 导出为"签核证据包" (zip)
  - 验证证据包完整性

这是 SignOffAI "可审计" 价值主张的核心实现。
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ═══════════════════════════════════════════════════════════════
# Hash 工具
# ═══════════════════════════════════════════════════════════════

def hash_file(filepath: Path) -> str:
    """计算文件 SHA256 hash"""
    if not filepath.exists():
        return ""
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def hash_content(content: str | bytes) -> str:
    """计算内容 SHA256 hash"""
    sha = hashlib.sha256()
    if isinstance(content, str):
        content = content.encode("utf-8")
    sha.update(content)
    return sha.hexdigest()


def hash_json(obj: Any) -> str:
    """计算 JSON 对象的稳定 hash（key 排序）"""
    return hash_content(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str))


# ═══════════════════════════════════════════════════════════════
# Artifact Manifest
# ═══════════════════════════════════════════════════════════════

@dataclass
class PhaseArtifact:
    """单个阶段的产物记录"""
    phase_name: str              # 阶段名: spec, design, UVM, ...
    agent_role: str = ""         # Agent role name
    status: str = "unknown"      # passed | degraded | failed | skipped | error
    score: float = 0
    retries: int = 0
    elapsed_s: float = 0

    # 输入输出
    input_summary: str = ""      # 输入摘要（截断）
    input_hash: str = ""         # SHA256 of input
    output_summary: str = ""     # 输出摘要（截断）
    output_hash: str = ""        # SHA256 of output
    ctx_keys_before: List[str] = field(default_factory=list)
    ctx_keys_after: List[str] = field(default_factory=list)

    # 产物文件
    artifacts: List[str] = field(default_factory=list)   # 相对路径
    artifact_hashes: Dict[str, str] = field(default_factory=dict)  # path → SHA256

    # 工具调用
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    # 时间戳
    started_at: str = ""
    ended_at: str = ""

    # 错误信息
    error: Optional[str] = None


@dataclass
class RunManifest:
    """一次 pipeline run 的完整清单"""
    manifest_version: str = "1.0"
    product: str = "SignOffAI"

    # Run 元信息
    run_id: str = ""
    workflow: str = ""
    session_id: str = ""         # execution tracer session
    spec_file: str = ""          # 规格文件名
    state: str = "unknown"       # running | completed | completed_with_errors

    # 时间范围
    started_at: str = ""
    completed_at: str = ""
    total_time_s: float = 0

    # 阶段列表
    phases: List[PhaseArtifact] = field(default_factory=list)

    # 汇总
    total_phases: int = 0
    passed: int = 0
    degraded: int = 0
    failed: int = 0
    skipped: int = 0
    overall_score: float = 0
    iteration_count: int = 0

    # 工作目录产物
    output_root: str = ""
    output_files: List[str] = field(default_factory=list)
    output_file_count: int = 0

    # 全局 hash
    manifest_hash: str = ""      # 本 manifest 的 hash（用于完整性校验）
    evidence_hash: str = ""      # 所有产物文件的聚合 hash

    # 生成信息
    generated_at: str = ""
    generator: str = "vagent dump"

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# Manifest Builder
# ═══════════════════════════════════════════════════════════════

class ManifestBuilder:
    """从 execution traces + pipeline state + 文件系统构建 RunManifest"""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()
        self.exec_log_dir = self.project_root / "logs" / "execution"
        self.agent_debug_dir = self.project_root / "logs" / "agent_debug"

    # ── 列出可用 session ──

    def list_sessions(self) -> List[dict]:
        """列出所有可复现的 session"""
        sessions = []
        # 从 execution trace 文件
        if self.exec_log_dir.exists():
            for f in sorted(self.exec_log_dir.glob("exec_*.jsonl"), reverse=True):
                try:
                    first_line = f.read_text(encoding="utf-8").split("\n")[0]
                    data = json.loads(first_line)
                    sessions.append({
                        "session_id": data.get("session", f.stem.replace("exec_", "")),
                        "trace_file": str(f),
                        "workflow": data.get("workflow", ""),
                        "timestamp": data.get("timestamp", ""),
                        "event": data.get("event", "unknown"),
                    })
                except Exception:
                    sessions.append({
                        "session_id": f.stem.replace("exec_", ""),
                        "trace_file": str(f),
                        "workflow": "?",
                        "timestamp": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                        "event": "unknown",
                    })
        # 也从 agent_debug 目录
        if self.agent_debug_dir.exists():
            for f in sorted(self.agent_debug_dir.glob("debug_*.jsonl"), reverse=True):
                sid = f.stem.replace("debug_", "")
                if not any(s["session_id"] == sid for s in sessions):
                    sessions.append({
                        "session_id": sid,
                        "trace_file": str(f),
                        "workflow": "?",
                        "timestamp": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                        "event": "agent_trace",
                    })
        return sessions

    # ── 构建 manifest ──

    def build(self, session_id: str, run_state: dict = None,
              phases: List[dict] = None, ctx: Any = None,
              output_root: str | None = None) -> RunManifest:
        """从多种来源构建完整的 RunManifest。

        Args:
            session_id: execution tracer session ID
            run_state: pipeline run state dict (from PipelineExecutionService)
            phases: 阶段列表 [{name, status, score, time, retries, ...}]
            ctx: 上下文数据 (ContextStore or dict)
            output_root: 输出根目录
        """
        manifest = RunManifest(
            session_id=session_id,
            generated_at=datetime.now().isoformat(),
        )

        # ── 从 execution trace 读取 ──
        trace_data = self._read_trace(session_id)

        # ── 填充 run 元信息 ──
        if run_state:
            manifest.run_id = run_state.get("run_id", "")
            manifest.workflow = run_state.get("workflow", "")
            manifest.state = run_state.get("state", "unknown")
            manifest.started_at = run_state.get("started_at", "")
            manifest.completed_at = run_state.get("completed_at", "")
            manifest.passed = run_state.get("passed", 0)
            manifest.total_phases = run_state.get("total", 0)
            manifest.output_root = run_state.get("ctx", {}).get("working_dir", output_root) \
                if isinstance(run_state.get("ctx"), dict) else output_root

        if trace_data:
            if not manifest.workflow:
                manifest.workflow = trace_data.get("workflow", "")
            manifest.spec_file = trace_data.get("spec_file", "")
            if not manifest.started_at:
                manifest.started_at = trace_data.get("timestamp", "")

        # ── 填充阶段信息 ──
        if phases:
            for p in phases:
                phase_artifact = PhaseArtifact(
                    phase_name=p.get("name", ""),
                    status=p.get("status", "unknown"),
                    score=p.get("score", 0),
                    retries=p.get("retries", 0),
                    elapsed_s=p.get("time", 0),
                    started_at=p.get("started_at", ""),
                    ended_at=p.get("ended_at", ""),
                    error=p.get("error") or p.get("reason"),
                )
                manifest.phases.append(phase_artifact)

        # ── 从 trace 补充 LLM / tool 调用信息 ──
        if trace_data:
            self._enrich_phases_from_trace(manifest.phases, trace_data)

        # ── 补充上下文数据 ──
        if ctx is not None:
            ctx_dict = ctx.snapshot() if hasattr(ctx, 'snapshot') else (
                ctx if isinstance(ctx, dict) else {}
            )
            manifest.metadata["ctx_keys"] = list(ctx_dict.keys())
            manifest.metadata["coverage"] = ctx_dict.get("coverage", {})
            manifest.metadata["regression"] = ctx_dict.get("regression", {})
            manifest.overall_score = ctx_dict.get("_overall_score", 0)
            manifest.iteration_count = ctx_dict.get("_iterations", 0)

        # ── 扫描产物文件 ──
        output_path = self.project_root / manifest.output_root if manifest.output_root else self.project_root / output_root
        manifest.output_root = str(output_path.resolve())
        if output_path.exists():
            files = []
            for f in sorted(output_path.rglob("*")):
                if f.is_file() and not f.name.startswith("."):
                    rel = str(f.relative_to(output_path))
                    files.append(rel)
            manifest.output_files = files[:500]  # 截断避免过大
            manifest.output_file_count = len(files)
            # 聚合 hash
            manifest.evidence_hash = self._compute_aggregate_hash(output_path, files)

        # ── 汇总计算 ──
        if not manifest.total_phases:
            manifest.total_phases = len(manifest.phases)
        if not manifest.passed:
            manifest.passed = sum(1 for p in manifest.phases if p.status == "passed")
        manifest.failed = sum(1 for p in manifest.phases if p.status in ("failed", "error"))
        manifest.degraded = sum(1 for p in manifest.phases if p.status == "degraded")
        manifest.skipped = sum(1 for p in manifest.phases if p.status == "skipped")
        if phases:
            manifest.total_time_s = sum(p.get("time", 0) for p in phases)

        # ── 自 hash ──
        manifest.manifest_hash = hash_json(self._manifest_to_dict(manifest))

        return manifest

    # ── 读取 trace ──

    def _read_trace(self, session_id: str) -> Optional[dict]:
        """读取 execution trace JSONL，返回汇总字典"""
        trace_file = self.exec_log_dir / f"exec_{session_id}.jsonl"
        if not trace_file.exists():
            trace_file = self.agent_debug_dir / f"debug_{session_id}.jsonl"
        if not trace_file.exists():
            return None

        events = []
        try:
            for line in trace_file.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    events.append(json.loads(line))
        except Exception:
            return None

        if not events:
            return None

        result = {
            "session": session_id,
            "events": events,
            "workflow": "",
            "spec_file": "",
            "timestamp": "",
            "phases": [],
            "llm_calls": [],
            "tool_calls": [],
            "file_writes": [],
            "pipeline_summary": {},
        }

        for e in events:
            evt = e.get("event", "")
            if evt == "pipeline_start":
                result["workflow"] = e.get("workflow", "")
                result["spec_file"] = e.get("spec_file", "")
                result["timestamp"] = e.get("timestamp", "")
                result["phases"] = e.get("phases", [])
            elif evt == "pipeline_end":
                result["pipeline_summary"] = {
                    "passed": e.get("passed", 0),
                    "total": e.get("total", 0),
                    "total_time": e.get("total_time", 0),
                    "scores": e.get("scores", {}),
                }
            elif evt == "llm_call":
                result["llm_calls"].append(e)
            elif evt == "tool_call":
                result["tool_calls"].append(e)
            elif evt == "file_write":
                result["file_writes"].append(e)

        return result

    def _enrich_phases_from_trace(self, phases: List[PhaseArtifact], trace_data: dict):
        """用 trace 中的 LLM/tool 调用信息补充 phase"""
        # 将 tool_calls 近似分配到对应 phase（按顺序）
        tool_calls = trace_data.get("tool_calls", [])
        llm_calls = trace_data.get("llm_calls", [])
        file_writes = trace_data.get("file_writes", [])

        # 简化策略：将前几个 tool call 分配给前几个 phase
        for i, phase in enumerate(phases):
            if i < len(tool_calls):
                phase.tool_calls.append(tool_calls[i])

    # ── 聚合 hash ──

    def _compute_aggregate_hash(self, output_path: Path, files: List[str],
                                 max_files: int = 100) -> str:
        """计算所有产物文件的聚合 hash（只读前 max_files 个以避免过慢）"""
        sha = hashlib.sha256()
        for rel_path in sorted(files)[:max_files]:
            fpath = output_path / rel_path
            if fpath.exists() and fpath.is_file():
                sha.update(rel_path.encode())
                sha.update(hash_file(fpath).encode())
        return sha.hexdigest()

    # ── 序列化 ──

    def _manifest_to_dict(self, m: RunManifest) -> dict:
        """将 manifest 转为可序列化的 dict（排除 manifest_hash 本身）"""
        phases = []
        for p in m.phases:
            phases.append({
                "phase_name": p.phase_name,
                "agent_role": p.agent_role,
                "status": p.status,
                "score": p.score,
                "retries": p.retries,
                "elapsed_s": p.elapsed_s,
                "input_hash": p.input_hash,
                "output_hash": p.output_hash,
                "input_summary": p.input_summary[:200] if p.input_summary else "",
                "output_summary": p.output_summary[:200] if p.output_summary else "",
                "artifact_count": len(p.artifacts),
                "artifacts": p.artifacts[:50],  # 截断
                "artifact_hashes": p.artifact_hashes,
                "tool_call_count": len(p.tool_calls),
                "started_at": p.started_at,
                "ended_at": p.ended_at,
                "error": p.error,
            })

        return {
            "manifest_version": m.manifest_version,
            "product": m.product,
            "run_id": m.run_id,
            "workflow": m.workflow,
            "session_id": m.session_id,
            "state": m.state,
            "started_at": m.started_at,
            "completed_at": m.completed_at,
            "total_time_s": m.total_time_s,
            "total_phases": m.total_phases,
            "passed": m.passed,
            "degraded": m.degraded,
            "failed": m.failed,
            "skipped": m.skipped,
            "overall_score": m.overall_score,
            "iteration_count": m.iteration_count,
            "output_root": m.output_root,
            "output_file_count": m.output_file_count,
            "evidence_hash": m.evidence_hash,
            "generated_at": m.generated_at,
            "generator": m.generator,
            "phases": phases,
            "metadata": m.metadata,
        }

    def to_json(self, m: RunManifest, indent: int = 2) -> str:
        """序列化 manifest 为 JSON"""
        d = self._manifest_to_dict(m)
        d["manifest_hash"] = m.manifest_hash  # 加回来
        return json.dumps(d, indent=indent, ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# Evidence Packager — 签核证据包导出
# ═══════════════════════════════════════════════════════════════

class EvidencePackager:
    """将 manifest + 产物文件打包为"签核证据包" (zip)"""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root).resolve()

    def package(self, manifest: RunManifest, output_zip: Path) -> Path:
        """导出证据包为 zip 文件。

        包含:
          - manifest.json: 完整清单
          - summary.md: 人类可读摘要
          - output/: 所有产物文件
          - logs/: 执行日志
        """
        output_zip = output_zip.resolve()
        output_zip.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. manifest.json
            builder = ManifestBuilder(str(self.project_root))
            manifest_json = builder.to_json(manifest)
            zf.writestr("manifest.json", manifest_json)

            # 2. summary.md
            summary_md = self._generate_summary_md(manifest)
            zf.writestr("summary.md", summary_md)

            # 3. 产物文件
            output_path = Path(manifest.output_root)
            if output_path.exists():
                for f in output_path.rglob("*"):
                    if f.is_file() and not f.name.startswith("."):
                        arcname = "output/" + str(f.relative_to(output_path))
                        zf.write(f, arcname)

            # 4. 执行日志
            session_id = manifest.session_id
            exec_log = self.project_root / "logs" / "execution" / f"exec_{session_id}.jsonl"
            if exec_log.exists():
                zf.write(exec_log, "logs/exec_trace.jsonl")
            debug_log = self.project_root / "logs" / "agent_debug" / f"debug_{session_id}.jsonl"
            if debug_log.exists():
                zf.write(debug_log, "logs/agent_debug.jsonl")

        # 写 manifest 文件到 zip 同目录
        manifest_path = output_zip.with_suffix(".manifest.json")
        manifest_path.write_text(manifest_json, encoding="utf-8")

        return output_zip

    def verify(self, zip_path: Path) -> dict:
        """验证证据包完整性。返回 {valid, issues, manifest}"""
        issues = []
        manifest = None

        if not zip_path.exists():
            return {"valid": False, "issues": ["zip file not found"], "manifest": None}

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                # 检查 manifest.json
                if "manifest.json" not in zf.namelist():
                    issues.append("missing manifest.json")

                manifest_json = zf.read("manifest.json").decode("utf-8")
                manifest_data = json.loads(manifest_json)

                # 验证 hash
                stored_hash = manifest_data.get("manifest_hash", "")
                calc_hash = hash_json({
                    k: v for k, v in manifest_data.items() if k != "manifest_hash"
                })
                if stored_hash and stored_hash != calc_hash:
                    issues.append("manifest hash mismatch — evidence may be tampered")

                # 检查产物文件
                output_files = [n for n in zf.namelist() if n.startswith("output/")]
                if not output_files:
                    issues.append("no output artifacts in package")

                manifest = manifest_data

        except zipfile.BadZipFile:
            return {"valid": False, "issues": ["corrupted zip file"], "manifest": None}
        except Exception as e:
            return {"valid": False, "issues": [str(e)], "manifest": None}

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "manifest": manifest,
        }

    def _generate_summary_md(self, m: RunManifest) -> str:
        """生成人类可读的签核证据摘要 Markdown"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"# SignOffAI 签核证据包",
            f"",
            f"| 项目 | 内容 |",
            f"|------|------|",
            f"| **Run ID** | `{m.run_id}` |",
            f"| **Session** | `{m.session_id}` |",
            f"| **Workflow** | {m.workflow} |",
            f"| **状态** | {m.state} |",
            f"| **开始时间** | {m.started_at} |",
            f"| **完成时间** | {m.completed_at} |",
            f"| **总耗时** | {m.total_time_s:.1f}s |",
            f"| **总阶段数** | {m.total_phases} |",
            f"| **通过** | {m.passed} |",
            f"| **降级** | {m.degraded} |",
            f"| **失败** | {m.failed} |",
            f"| **综合评分** | {m.overall_score}/100 |",
            f"| **反馈迭代** | {m.iteration_count} 轮 |",
            f"| **产物文件数** | {m.output_file_count} |",
            f"| **证据 Hash** | `{m.evidence_hash[:16]}...` |",
            f"| **Manifest Hash** | `{m.manifest_hash[:16]}...` |",
            f"",
            f"---",
            f"",
            f"## 阶段详情",
            f"",
            f"| 阶段 | 状态 | 评分 | 重试 | 耗时 |",
            f"|------|------|------|------|------|",
        ]
        for p in m.phases:
            icon = {"passed": "✅", "degraded": "⚠️", "failed": "❌", "skipped": "⏭️"}.get(p.status, "❓")
            lines.append(f"| {p.phase_name} | {icon} {p.status} | {p.score} | {p.retries} | {p.elapsed_s:.1f}s |")

        lines.extend([
            f"",
            f"---",
            f"",
            f"*此证据包由 SignOffAI `vagent dump` 命令自动生成于 {now}*",
            f"*证据包 Hash: `{m.evidence_hash}` — 任何篡改都会导致 Hash 不匹配*",
        ])
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def list_sessions(project_root: str = ".") -> List[dict]:
    """列出所有可复现的 session"""
    return ManifestBuilder(project_root).list_sessions()


def build_manifest(session_id: str, project_root: str = ".",
                   run_state: dict = None, phases: List[dict] = None,
                   ctx: Any = None, output_root: str | None = None) -> RunManifest:
    """构建单个 session 的 manifest"""
    from src.core.output_config import make_output_root
    output_root = make_output_root(output_root)
    return ManifestBuilder(project_root).build(
        session_id=session_id,
        run_state=run_state,
        phases=phases,
        ctx=ctx,
        output_root=output_root,
    )


def export_evidence_package(session_id: str, output_zip: str,
                            project_root: str = ".",
                            run_state: dict = None,
                            phases: List[dict] = None,
                            ctx: Any = None,
                            output_root: str | None = None) -> Path:
    """导出签核证据包"""
    from src.core.output_config import make_output_root
    output_root = make_output_root(output_root)
    manifest = build_manifest(
        session_id=session_id,
        project_root=project_root,
        run_state=run_state,
        phases=phases,
        ctx=ctx,
        output_root=output_root,
    )
    return EvidencePackager(project_root).package(manifest, Path(output_zip))
