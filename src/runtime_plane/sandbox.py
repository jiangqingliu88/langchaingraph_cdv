"""沙箱工具 —— 写只落 staging，main 只读。

这些工具**不是** OS 级隔离（没有容器/虚拟机）；它们保证的是**路径边界**：
任何写、删、子进程 cwd 都落在 `staging/` 内，出错代价 = 丢一个 staging 目录。
真正的强隔离由外部执行环境承担（见 `tool_sandbox.py` 的策略层）。
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from .workspace_manager import WorkspaceError, WorkspaceZones

_SECRET_ENV = re.compile(r"(SECRET|TOKEN|PASSWORD|API[_-]?KEY|PRIVATE[_-]?KEY)",
                         re.IGNORECASE)


def _staging_rel(rel: str) -> str:
    text = str(rel).strip().replace("\\", "/")
    if text.startswith("main/") or text == "main":
        raise WorkspaceError("main/ 只读，沙箱只能写 staging/")
    return text[len("staging/"):] if text.startswith("staging/") else text


class SandboxTools:
    def __init__(self, zones: WorkspaceZones, *, timeout: int = 120,
                 max_output_bytes: int = 200_000):
        self.zones = zones
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes
        self._command_index = 0

    # ── 分发 ──────────────────────────────────────────────────────────────

    def call(self, tool: str, args: Dict[str, Any] | None = None) -> Dict[str, Any]:
        args = dict(args or {})
        handler = getattr(self, f"_tool_{tool}", None)
        if handler is None:
            return {"ok": False, "tool": tool,
                    "error": f"未知工具：{tool}"}
        try:
            return {"ok": True, "tool": tool, "result": handler(**args)}
        except (WorkspaceError, OSError, ValueError, TypeError) as exc:
            return {"ok": False, "tool": tool, "error": str(exc)}

    # ── 读 ────────────────────────────────────────────────────────────────

    def _tool_read_file(self, path: str, zone: str = "auto") -> str:
        if zone in ("auto", ""):
            try:
                return self.zones.read(path, zone="staging")
            except WorkspaceError:
                return self.zones.read(path, zone="main")
        return self.zones.read(path, zone=zone)

    def _tool_list_files(self, path: str = "", zone: str = "staging",
                         limit: int = 300) -> List[Dict[str, str]]:
        base = self.zones.zone_path(path or ".", zone, must_exist=True)
        if base.is_file():
            return [{"path": path, "kind": "file"}]
        rows = []
        for child in sorted(base.iterdir()):
            if self.zones.is_blocked(child):
                continue
            rows.append({"path": child.relative_to(self.zones.root).as_posix(),
                         "kind": "dir" if child.is_dir() else "file"})
            if len(rows) >= limit:
                break
        return rows

    def _iter_files(self, base: Path):
        """遍历文件并剪掉被屏蔽的目录（.git/venv/.env…），避免直连模式下扫全盘。"""
        if base.is_file():
            yield base
            return
        for dirpath, dirnames, filenames in os.walk(base):
            current = Path(dirpath)
            dirnames[:] = sorted(d for d in dirnames
                                 if not self.zones.is_blocked(current / d))
            for name in sorted(filenames):
                path = current / name
                if not self.zones.is_blocked(path):
                    yield path

    def _tool_search(self, pattern: str, path: str = "", zone: str = "staging",
                     glob: str = "*", limit: int = 100) -> List[Dict[str, Any]]:
        regex = re.compile(pattern)
        base = self.zones.zone_path(path or ".", zone, must_exist=True)
        rows: List[Dict[str, Any]] = []
        for file in self._iter_files(base):
            if glob and glob != "*" and not file.match(glob):
                continue
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rows.append({"path": file.relative_to(self.zones.root).as_posix(),
                                 "line": number, "text": line.strip()[:300]})
                    if len(rows) >= limit:
                        return rows
        return rows

    # ── 写（只 staging）──────────────────────────────────────────────────

    def _tool_write_file(self, path: str, content: str) -> Dict[str, Any]:
        import difflib

        rel = _staging_rel(path)
        target = self.zones.staging_path(rel)
        existed = target.exists()
        before = ""
        if existed and target.is_file() and target.stat().st_size <= 500_000:
            try:
                before = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                before = ""
        target = self.zones.write_staging(rel, content)
        label = rel if self.zones.direct else f"staging/{rel}"
        diff = "\n".join(difflib.unified_diff(
            before.splitlines(), str(content).splitlines(),
            fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""))
        return {"path": label, "sha256": _sha256(target),
                "created": not existed,
                "before_sha": _sha256_text(before) if before else "",
                "diff": diff}

    def _tool_delete_file(self, path: str) -> Dict[str, Any]:
        import difflib

        rel = _staging_rel(path)
        target = self.zones.staging_path(rel, must_exist=True)
        before = ""
        try:
            if target.stat().st_size <= 500_000:
                before = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            before = ""
        self.zones.delete_staging(rel)
        label = rel if self.zones.direct else f"staging/{rel}"
        diff = "\n".join(difflib.unified_diff(
            before.splitlines(), [], fromfile=f"a/{rel}", tofile="/dev/null",
            lineterm=""))
        return {"path": label, "action": "delete",
                "before_sha": _sha256_text(before) if before else "",
                "diff": diff}

    # ── 跑 ────────────────────────────────────────────────────────────────

    def _tool_run_shell(self, command, timeout: int | None = None) -> Dict[str, Any]:
        shell = isinstance(command, str)
        self._command_index += 1
        if self.zones.direct:
            log_path = self.zones.harness_dir / "logs" / f"{self._command_index:03d}.log"
            log_label = f".signoffai/logs/{self._command_index:03d}.log"
        else:
            log_path = self.zones.logs_dir / f"{self._command_index:03d}.log"
            log_label = f"staging/.evidence/{self._command_index:03d}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
        env["SIGNOFFAI_WORKSPACE"] = str(self.zones.root)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        try:
            completed = subprocess.run(
                command, cwd=str(self.zones.workdir), shell=shell,
                env=env, capture_output=True, text=True,
                timeout=timeout or self.timeout,
                encoding="utf-8", errors="replace")
            exit_code = completed.returncode
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = f"TIMEOUT after {timeout or self.timeout}s"
        except OSError as exc:
            exit_code = 127
            stdout, stderr = "", str(exc)

        body = (f"$ {command if shell else ' '.join(map(str, command))}\n"
                f"exit={exit_code}\n--- stdout ---\n{stdout}\n"
                f"--- stderr ---\n{stderr}\n")
        log_path.write_text(body[: self.max_output_bytes], encoding="utf-8")
        return {
            "exit_code": exit_code,
            "stdout": stdout[: self.max_output_bytes],
            "stderr": stderr[: self.max_output_bytes],
            "log": log_label,
            "command": command if shell else list(map(str, command)),
        }


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
