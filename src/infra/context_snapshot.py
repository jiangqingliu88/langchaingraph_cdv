"""
上下文快照 + 产物自动归类

每次执行流程时保存完整上下文快照（输入/配置/环境变量/依赖版本），
产物按类型自动归入对应分类目录，便于复现问题和审计追溯。
"""
from __future__ import annotations

import os, json, hashlib, shutil
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════════
# 产物分类
# ═══════════════════════════════════════════════════════════

ARTIFACT_CATEGORIES = {
    "regression_report": {"dir": "reports/regression", "exts": [".rpt", ".html", ".json", ".txt"]},
    "coverage_report": {"dir": "reports/coverage", "exts": [".html", ".ucdb", ".json", ".xml"]},
    "debug_log": {"dir": "logs/debug", "exts": [".log", ".txt", ".trace"]},
    "signoff_evidence": {"dir": "evidence/signoff", "exts": [".json", ".zip", ".pdf"]},
    "manifest": {"dir": "manifests", "exts": [".json"]},
    "testcase": {"dir": "testcases", "exts": [".sv", ".v", ".svh", ".yaml"]},
    "rtl_output": {"dir": "rtl", "exts": [".v", ".sv", ".vh"]},
    "uvm_env": {"dir": "uvm", "exts": [".sv", ".svh", ".pkg"]},
    "c_model": {"dir": "cmodel", "exts": [".cpp", ".h", ".hpp"]},
    "waveform": {"dir": "waves", "exts": [".wlf", ".vcd", ".fsdb"]},
    "compile_log": {"dir": "logs/compile", "exts": [".log", ".txt"]},
    "ppa_report": {"dir": "reports/ppa", "exts": [".rpt", ".txt", ".json"]},
    "snapshot": {"dir": "snapshots", "exts": [".json"]},
}


@dataclass
class ContextSnapshot:
    """执行上下文快照"""
    snapshot_id: str = ""
    run_id: str = ""
    workflow: str = ""
    phase: str = ""

    # 输入上下文
    spec_hash: str = ""
    spec_summary: str = ""
    config_snapshot: dict = field(default_factory=dict)
    env_vars: dict = field(default_factory=dict)
    dependencies: dict = field(default_factory=dict)

    # 执行环境
    python_version: str = ""
    platform: str = ""
    workspace_root: str = ""
    agent_versions: dict = field(default_factory=dict)

    # 时间戳
    created_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "run_id": self.run_id, "workflow": self.workflow, "phase": self.phase,
            "spec_hash": self.spec_hash, "spec_summary": self.spec_summary,
            "config": self.config_snapshot, "env_vars": self.env_vars,
            "dependencies": self.dependencies,
            "python_version": self.python_version, "platform": self.platform,
            "workspace_root": self.workspace_root,
            "agent_versions": self.agent_versions,
            "created_at": self.created_at, "completed_at": self.completed_at,
        }


class ContextSnapshotter:
    """上下文快照管理器"""

    def __init__(self, output_root: str):
        self.output_root = Path(output_root)
        self._snapshots: dict[str, ContextSnapshot] = {}

    def capture(self, run_id: str, workflow: str, phase: str = "",
                spec_text: str = "", config: dict = None) -> ContextSnapshot:
        """捕获当前执行上下文"""
        import sys, platform

        snapshot_id = f"snap_{run_id}_{phase or 'init'}"
        if phase:
            snapshot_id = f"snap_{run_id}_{phase}"

        snapshot = ContextSnapshot(
            snapshot_id=snapshot_id,
            run_id=run_id,
            workflow=workflow,
            phase=phase,
            spec_hash=hashlib.sha256(spec_text.encode()).hexdigest()[:16] if spec_text else "",
            spec_summary=(spec_text[:200] + "..." if len(spec_text) > 200 else spec_text) if spec_text else "",
            config_snapshot=config or {},
            env_vars={k: v for k, v in os.environ.items()
                      if not k.startswith(("PATH", "PYTHON", "SECRET", "KEY", "TOKEN"))},
            dependencies=self._capture_deps(),
            python_version=sys.version,
            platform=platform.platform(),
            workspace_root=str(Path.cwd()),
            created_at=datetime.now().isoformat(),
        )

        self._snapshots[snapshot_id] = snapshot
        return snapshot

    def finalize(self, snapshot_id: str):
        """标记快照完成"""
        if snapshot_id in self._snapshots:
            self._snapshots[snapshot_id].completed_at = datetime.now().isoformat()

    def save(self, snapshot_id: str) -> Path:
        """持久化快照到文件"""
        if snapshot_id not in self._snapshots:
            raise KeyError(f"Snapshot not found: {snapshot_id}")
        snap = self._snapshots[snapshot_id]
        snap_dir = self.output_root / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        path = snap_dir / f"{snapshot_id}.json"
        path.write_text(json.dumps(snap.to_dict(), indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
        return path

    def load(self, snapshot_id: str) -> Optional[dict]:
        """加载快照"""
        path = self.output_root / "snapshots" / f"{snapshot_id}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def list_snapshots(self, run_id: str = "") -> list:
        """列出快照"""
        snap_dir = self.output_root / "snapshots"
        if not snap_dir.exists():
            return []
        snaps = sorted(snap_dir.glob("snap_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        result = []
        for s in snaps:
            try:
                data = json.loads(s.read_text(encoding="utf-8"))
                if not run_id or data.get("run_id") == run_id:
                    result.append({
                        "snapshot_id": data.get("snapshot_id"),
                        "run_id": data.get("run_id"),
                        "phase": data.get("phase"),
                        "spec_hash": data.get("spec_hash"),
                        "created_at": data.get("created_at"),
                    })
            except Exception:
                pass
        return result

    @staticmethod
    def _capture_deps() -> dict:
        """捕获关键依赖版本"""
        deps = {}
        try:
            import pkg_resources
            for pkg in ["fastapi", "sqlalchemy", "pydantic", "uvicorn", "pyyaml"]:
                try:
                    deps[pkg] = pkg_resources.get_distribution(pkg).version
                except Exception:
                    pass
        except Exception:
            pass
        return deps


class ArtifactClassifier:
    """产物自动归类器"""

    def __init__(self, output_root: str):
        self.output_root = Path(output_root)
        self._ensure_dirs()

    def _ensure_dirs(self):
        """创建所有分类目录"""
        for cat, info in ARTIFACT_CATEGORIES.items():
            (self.output_root / info["dir"]).mkdir(parents=True, exist_ok=True)

    def classify_file(self, file_path: Path) -> Optional[str]:
        """判断单个文件应归属哪个分类"""
        ext = file_path.suffix.lower()
        name = file_path.name.lower()

        # 精确匹配
        for cat, info in ARTIFACT_CATEGORIES.items():
            if ext in info["exts"]:
                # 进一步按名称特征区分
                if cat == "coverage_report" and "coverage" not in name and "cov" not in name:
                    continue
                if cat == "debug_log" and "debug" not in name and "error" not in name and "fail" not in name:
                    continue
                return cat

        # 按内容特征匹配
        if "manifest" in name:
            return "manifest"
        if "evidence" in name:
            return "signoff_evidence"
        if "report" in name:
            return "regression_report"
        if "log" in name or ext == ".log":
            return "debug_log"

        return None

    def organize(self, source_dir: str = None, dry_run: bool = False) -> dict:
        """自动归类目录下的所有产物"""
        src = Path(source_dir) if source_dir else self.output_root
        if not src.exists():
            return {"error": f"Source directory not found: {src}"}

        result = {"classified": {}, "skipped": 0, "total": 0}

        for f in src.rglob("*"):
            if not f.is_file() or f.name.startswith("."):
                continue
            result["total"] += 1

            # 跳过已在分类目录中的文件
            rel = str(f.relative_to(src))
            if any(rel.startswith(info["dir"]) for info in ARTIFACT_CATEGORIES.values()):
                result["skipped"] += 1
                continue

            cat = self.classify_file(f)
            if cat:
                target_dir = self.output_root / ARTIFACT_CATEGORIES[cat]["dir"]
                target = target_dir / f.name

                # 去重：如果目标已存在且内容相同，跳过
                if target.exists():
                    existing_hash = hashlib.sha256(target.read_bytes()).hexdigest()
                    new_hash = hashlib.sha256(f.read_bytes()).hexdigest()
                    if existing_hash == new_hash:
                        result["skipped"] += 1
                        continue

                if not dry_run:
                    target.write_bytes(f.read_bytes())
                result["classified"].setdefault(cat, []).append(str(f.name))

        return result

    def get_catalog(self) -> dict:
        """获取产物目录"""
        catalog = {}
        for cat, info in ARTIFACT_CATEGORIES.items():
            cat_dir = self.output_root / info["dir"]
            if cat_dir.exists():
                files = sorted(
                    [{"name": f.name, "size_kb": round(f.stat().st_size / 1024, 1),
                      "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat()}
                     for f in cat_dir.iterdir() if f.is_file()],
                    key=lambda x: x["modified"], reverse=True
                )
                catalog[cat] = {
                    "path": info["dir"],
                    "file_count": len(files),
                    "files": files[:20],
                }
        return catalog


# ── 全局实例 ──
_snapshotter: Optional[ContextSnapshotter] = None


def get_snapshotter(output_root: str = "output") -> ContextSnapshotter:
    global _snapshotter
    if _snapshotter is None:
        _snapshotter = ContextSnapshotter(output_root)
    return _snapshotter
