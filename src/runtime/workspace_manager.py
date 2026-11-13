"""三个区、两条边界。

```
<workspace>/
  main/        签核过的内容（sandbox 只读；只有 gate.promote 写）
  staging/     沙箱工作区（可写、可丢弃；loop 只在这里面动）
  proposals/   Proposal JSON（staging → gate 的唯一通道）
  gate/        GateReport / 人工批准 / promote 账本与备份
```

`staging` 与 `main` 是**物理隔离**：沙箱没有写 main 的 API；唯一写入点是
`workspace.gate.promote`。出错代价 = 丢一个 staging 目录。
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

from src.core.runtime.atomic import atomic_write_json, atomic_write_text

ZONES = ("main", "staging", "proposals", "gate")

#: in-place 模式下不参与 diff / 不暴露的目录（相对项目根）。
_DIRECT_SKIP = {".git", "__pycache__", "venv", ".venv", "node_modules",
                ".pytest_cache", ".mypy_cache", ".idea", ".vscode"}


class WorkspaceError(RuntimeError):
    """越区 / 非法路径 / 工作区未初始化。"""


def _discover_project_root(from_dir, fallback: Path) -> Path:
    """没有显式 project_root 时向上找工程根（`.git` / `pyproject.toml`）。"""
    start = Path(from_dir).expanduser().resolve() if from_dir is not None else fallback
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / "pyproject.toml").is_file():
            return candidate
    return start


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class WorkspaceZones:
    """一个 workspace 的分区句柄。

    `direct=True` 时没有 main/staging 副本：工作区根就是项目根，agent 直接
    读写真实工程；会话/日志/run 元数据放 `<root>/.signoffai/`。默认仍是四区
    沙箱（main/staging/proposals/gate）。
    """

    def __init__(self, root: str | Path, *, direct: bool = False):
        self.root = Path(root).expanduser().resolve()
        self.direct = bool(direct)
        if self.direct:
            self.main = self.root
            self.staging = self.root
            self.proposals = self.root / ".signoffai" / "proposals"
            self.gate = self.root / ".signoffai" / "gate"
            self.harness_dir = self.root / ".signoffai"
        else:
            self.main = self.root / "main"
            self.staging = self.root / "staging"
            self.proposals = self.root / "proposals"
            self.gate = self.root / "gate"
            self.harness_dir = self.root / ".harness"
        self.metadata_path = self.harness_dir / "workspace.json"

    @classmethod
    def direct_mode(cls, root: str | Path,
                    project_root: str | Path | None = None) -> "WorkspaceZones":
        """直接模式：agent 在真实工程里工作，不再复制 main/staging。"""
        zones = cls(root, direct=True)
        zones.root.mkdir(parents=True, exist_ok=True)
        for sub in ("sessions", "logs", "jobs", "runs"):
            (zones.harness_dir / sub).mkdir(parents=True, exist_ok=True)
        atomic_write_json(zones.metadata_path, {
            "schema": "workspace_meta_v1",
            "mode": "direct",
            "root": str(zones.root),
            "source": str(zones.root),
            "project_root": str(Path(project_root).expanduser().resolve()
                                if project_root else zones.root),
        })
        return zones

    # ── 生命周期 ──────────────────────────────────────────────────────────

    @classmethod
    def init(cls, root: str | Path, from_dir: str | Path | None = None,
             project_root: str | Path | None = None) -> "WorkspaceZones":
        """建出四区；`from_dir` 给出时作为 main 基线（并复制一份到 staging）。"""
        zones = cls(root)
        zones.root.mkdir(parents=True, exist_ok=True)
        for name in ZONES:
            getattr(zones, name).mkdir(parents=True, exist_ok=True)
        zones.harness_dir.mkdir(parents=True, exist_ok=True)
        if from_dir is not None:
            source = Path(from_dir).expanduser().resolve()
            if not source.is_dir():
                raise WorkspaceError(f"main 基线目录不存在：{source}")
            if not any(zones.main.iterdir()):
                shutil.copytree(source, zones.main, dirs_exist_ok=True)
        if not zones.staging.exists() or not any(zones.staging.iterdir()):
            if zones.staging.exists():
                shutil.rmtree(zones.staging)
            shutil.copytree(zones.main, zones.staging, dirs_exist_ok=True)
        marker = zones.metadata_path
        if project_root is not None or not marker.is_file():
            source = str(Path(project_root).expanduser().resolve()
                         if project_root is not None
                         else _discover_project_root(from_dir, zones.root))
            atomic_write_json(marker, {
                "schema": "workspace_meta_v1",
                "root": str(zones.root),
                "source": source,
                "project_root": source,
            })
        return zones

    def project_root(self) -> Path:
        """只读项目视图根（init 时记录：显式值或向上发现的工程根）。"""
        try:
            import json
            doc = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            value = str(doc.get("project_root") or "")
        except (OSError, ValueError):
            value = ""
        return Path(value).expanduser().resolve() if value else self.root

    def ensure(self) -> "WorkspaceZones":
        if not self.root.is_dir():
            raise WorkspaceError(f"workspace 不存在：{self.root}（先 workspace init）")
        if self.direct:
            for sub in ("sessions", "logs", "jobs", "runs"):
                (self.harness_dir / sub).mkdir(parents=True, exist_ok=True)
            return self
        for name in ZONES:
            getattr(self, name).mkdir(parents=True, exist_ok=True)
        self.harness_dir.mkdir(parents=True, exist_ok=True)
        return self

    def reset_staging(self) -> None:
        """丢弃沙箱：staging 恢复成 main 的副本。直接模式没有副本。"""
        if self.direct:
            raise WorkspaceError("直接模式没有 staging 快照可重置")
        self.ensure()
        shutil.rmtree(self.staging, ignore_errors=True)
        shutil.copytree(self.main, self.staging, dirs_exist_ok=True)

    @property
    def workdir(self) -> Path:
        """工具的工作目录：沙箱=staging，直接模式=项目根。"""
        return self.staging

    @property
    def logs_dir(self) -> Path:
        if self.direct:
            return self.harness_dir / "logs"
        return self.staging / ".evidence"

    # ── 路径与隔离 ────────────────────────────────────────────────────────

    @staticmethod
    def _clean_rel(rel: str | Path) -> Path:
        text = str(rel).strip().replace("\\", "/")
        if not text:
            raise WorkspaceError("空路径")
        path = Path(text)
        if path.is_absolute() or ":" in text.split("/")[0]:
            raise WorkspaceError(f"只接受 workspace 相对路径：{rel}")
        if ".." in path.parts:
            raise WorkspaceError(f"路径不能穿越 workspace：{rel}")
        return path

    def is_blocked(self, path: str | Path) -> bool:
        """直接模式下不可读写的路径：版本库/虚拟环境/缓存/密钥。"""
        if not self.direct:
            return False
        candidate = Path(path)
        try:
            rel = candidate.expanduser().resolve().relative_to(self.root)
        except (OSError, ValueError):
            return True
        if rel.parts and rel.parts[0] in _DIRECT_SKIP:
            return True
        # 复用只读项目视图的敏感文件规则（.env / 凭据 / 私钥）。
        from .resources import _skip
        return _skip(rel)

    def _resolve(self, base: Path, rel: str | Path, *, must_exist: bool = False) -> Path:
        path = (base / self._clean_rel(rel)).resolve()
        try:
            path.relative_to(base.resolve())
        except ValueError as exc:
            raise WorkspaceError(f"路径越出分区：{rel}") from exc
        if self.is_blocked(path):
            raise WorkspaceError(f"敏感/忽略路径不可访问：{rel}")
        if must_exist and not path.exists():
            raise WorkspaceError(f"文件不存在：{rel}")
        return path

    def staging_path(self, rel: str | Path, *, must_exist: bool = False) -> Path:
        return self._resolve(self.staging, rel, must_exist=must_exist)

    def main_path(self, rel: str | Path, *, must_exist: bool = False) -> Path:
        return self._resolve(self.main, rel, must_exist=must_exist)

    def zone_path(self, rel: str | Path, zone: str = "staging", *,
                  must_exist: bool = False) -> Path:
        """接受 `staging/x` / `main/x`（workspace 相对）或裸 `x`（该区内相对）。"""
        if zone not in ("main", "staging"):
            raise WorkspaceError(f"未知分区：{zone}")
        text = str(rel).strip().replace("\\", "/")
        if self.direct:
            for prefix in ("main/", "staging/"):
                if text.startswith(prefix):
                    text = text[len(prefix):]
                    break
            return self._resolve(self.staging, text, must_exist=must_exist)
        for other in ("main", "staging"):
            if text.startswith(other + "/") and other != zone:
                raise WorkspaceError(f"路径属于 {other}/，不是 {zone}/：{rel}")
        if text.startswith(zone + "/"):
            text = text[len(zone) + 1:]
        return self._resolve(getattr(self, zone), text, must_exist=must_exist)

    def sibling_path(self, rel: str | Path, zone: str = "main", *,
                     must_exist: bool = False) -> Path:
        """同一相对路径映射到另一个区（`staging/x` → `main/x`）。"""
        if zone not in ("main", "staging"):
            raise WorkspaceError(f"未知分区：{zone}")
        text = str(rel).strip().replace("\\", "/")
        for prefix in ("staging/", "main/"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        return self._resolve(getattr(self, zone), text, must_exist=must_exist)

    def read(self, rel: str | Path, *, zone: str = "staging") -> str:
        base = self.main if zone == "main" else self.staging
        path = self._resolve(base, rel, must_exist=True)
        return path.read_text(encoding="utf-8", errors="replace")

    def write_staging(self, rel: str | Path, text: str) -> Path:
        path = self.staging_path(rel)
        if path.exists() and path.is_symlink():
            raise WorkspaceError(f"拒绝写符号链接：{rel}")
        # `staging_path` 已经 resolve 并校验过父链；这里只建目录、写文件。
        path.parent.mkdir(parents=True, exist_ok=True)
        return atomic_write_text(path, text)

    def delete_staging(self, rel: str | Path) -> None:
        path = self.staging_path(rel, must_exist=True)
        if path.is_dir():
            raise WorkspaceError(f"只允许删文件：{rel}")
        path.unlink()

    # ── 指纹与差异 ────────────────────────────────────────────────────────

    @staticmethod
    def _files(base: Path) -> Dict[str, str]:
        out: Dict[str, str] = {}
        if not base.is_dir():
            return out
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            out[path.relative_to(base).as_posix()] = _sha256(path)
        return out

    def _git_changes(self) -> List[Dict[str, str]]:
        """`git status --porcelain` → add/modify/delete；非 git 仓库返回空。"""
        if not (self.root / ".git").exists():
            return []
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.root), "status", "--porcelain",
                 "--untracked-files=all"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30)
        except (OSError, subprocess.SubprocessError):
            return []
        if completed.returncode != 0:
            return []
        rows: List[Dict[str, str]] = []
        for line in completed.stdout.splitlines():
            if len(line) < 4:
                continue
            status, rel = line[:2], line[3:].strip().strip('"')
            if (not rel or rel.startswith((".signoffai/", "output", "work/"))
                    or self.is_blocked(self.root / rel)):
                continue
            if "D" in status:
                action = "delete"
            elif status.strip() == "??":
                action = "add"
            else:
                action = "modify"
            rows.append({"path": rel, "action": action, "sha256": ""})
        return rows

    def fingerprint(self, zone: str = "main") -> str:
        base = self.main if zone == "main" else self.staging
        lines = [f"{rel}:{sha}" for rel, sha in self._files(base).items()]
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()

    def changed_files(self) -> List[Dict[str, str]]:
        """直接模式用 git 工作区变更；沙箱模式用 staging 相对 main 的 diff。"""
        if self.direct:
            return self._git_changes()
        main_files = self._files(self.main)
        staging_files = self._files(self.staging)
        rows: List[Dict[str, str]] = []
        for rel in sorted(set(staging_files) | set(main_files)):
            # 沙箱证据（命令日志）是过程材料，不是要 promote 的交付物。
            if rel == ".evidence" or rel.startswith(".evidence/"):
                continue
            before = main_files.get(rel)
            after = staging_files.get(rel)
            if before == after:
                continue
            action = "add" if before is None else "delete" if after is None else "modify"
            rows.append({"path": f"staging/{rel}", "action": action,
                         "sha256": after or ""})
        return rows

    # ── 通道文件 ──────────────────────────────────────────────────────────

    def proposal_path(self, proposal_id: str) -> Path:
        return self.proposals / f"{self._clean_rel(proposal_id).name}.json"

    def gate_path(self, proposal_id: str) -> Path:
        return self.gate / f"{self._clean_rel(proposal_id).name}.json"

    def backup_dir(self, proposal_id: str) -> Path:
        path = self.gate / "backups" / self._clean_rel(proposal_id).name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ledger_path(self) -> Path:
        return self.gate / "ledger.jsonl"

    def session_path(self, session_id: str) -> Path:
        path = self.harness_dir / "sessions" / f"{self._clean_rel(session_id).name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
