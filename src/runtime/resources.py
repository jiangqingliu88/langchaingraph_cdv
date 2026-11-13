"""项目只读资源视图 —— RTL / 验证代码 / 覆盖率 / 环境 / spec / 模型（含 SC）。

沙箱的写边界不变：这里**只读**。敏感文件（`.env`、凭据、私钥）永不暴露；
二进制（如 `.ucdb`）只给元数据，不给内容。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

_SKIP_PARTS = {".git", "__pycache__", "venv", ".venv", "node_modules",
               ".idea", ".vscode", ".pytest_cache", ".mypy_cache"}
_SKIP_NAMES = {".env", ".env.local", ".env.example", ".jwt_secret",
               ".credentials.yaml", ".credentials.yml"}
_SKIP_SUFFIXES = (".pem", ".key")
_TEXT_SUFFIXES = {
    ".py", ".sv", ".svh", ".v", ".vh", ".vhd", ".vhdl", ".md", ".txt",
    ".json", ".jsonl", ".yaml", ".yml", ".csv", ".toml", ".ini", ".cfg",
    ".sc", ".cpp", ".cc", ".c", ".h", ".hpp", ".j2", ".tcl", ".do", ".sh",
    ".bat", ".f", ".sdc", ".xml",
}
_VERIFY_PARTS = {"sv", "tb", "agents", "agent", "env", "tests", "test",
                 "seq", "seqs", "verify", "uvm", "loopback"}
_MODEL_PARTS = {"model", "cmodel", "cmodel_tools", "scmodel", "scmodel_tools",
                "sc", "systemc"}
_SPEC_PARTS = {"specs", "docs", "doc", "reference"}
_ENV_PARTS = {"config", "inputs", "cfg"}
_COVERAGE_PARTS = {"coverage", "cov", "covgs", "ucdb", "coverstore"}
KINDS = ("rtl", "verification", "coverage", "env", "spec", "model")


def _skip(path: Path) -> bool:
    if path.name in _SKIP_NAMES or path.name.startswith(".env"):
        return True
    if any(path.name.endswith(suffix) for suffix in _SKIP_SUFFIXES):
        return True
    return bool(_SKIP_PARTS & set(path.parts))


def _classify(rel: Path) -> str:
    parts = {part.lower() for part in rel.parts[:-1]}
    name = rel.name.lower()
    suffix = rel.suffix.lower()
    if suffix == ".ucdb" or parts & _COVERAGE_PARTS or "coverage" in name:
        return "coverage"
    if parts & _MODEL_PARTS or suffix in {".sc", ".cpp", ".cc", ".c", ".hpp"}:
        return "model"
    if parts & _VERIFY_PARTS or name.endswith(("_tb.sv", "_test.sv")):
        return "verification"
    if "rtl" in parts or (suffix in {".sv", ".svh", ".v", ".vh"}):
        return "rtl"
    if parts & _SPEC_PARTS or suffix in {".md", ".txt"}:
        return "spec"
    if parts & _ENV_PARTS or suffix in {".yaml", ".yml", ".toml", ".ini", ".cfg"}:
        return "env"
    return "other"


class ProjectResources:
    def __init__(self, project_root: str | Path, *,
                 max_read_bytes: int = 200_000):
        self.root = Path(project_root).expanduser().resolve()
        self.max_read_bytes = max_read_bytes

    # ── 路径 ──────────────────────────────────────────────────────────────

    def _confine(self, path: str | Path) -> Path:
        text = str(path).strip().replace("\\", "/")
        if not text:
            raise ValueError("空路径")
        candidate = Path(text)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.root / candidate).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"路径越出项目根：{path}") from exc
        if _skip(resolved):
            raise ValueError(f"敏感/忽略路径不可读：{path}")
        return resolved

    def _files(self) -> Iterable[Path]:
        if not self.root.is_dir():
            return
        for path in self.root.rglob("*"):
            if path.is_file() and not _skip(path):
                yield path

    @staticmethod
    def _rel(path: Path, root: Path) -> str:
        return path.relative_to(root).as_posix()

    # ── 发现 ──────────────────────────────────────────────────────────────

    def inventory(self, kind: str = "", limit: int = 200) -> Dict[str, Any]:
        counts = {name: 0 for name in KINDS + ("other",)}
        items: List[Dict[str, Any]] = []
        for path in self._files():
            rel = path.relative_to(self.root)
            category = _classify(rel)
            counts[category] = counts.get(category, 0) + 1
            if kind and category != kind:
                continue
            if len(items) < limit:
                items.append({"path": self._rel(path, self.root), "kind": category,
                              "suffix": path.suffix.lower(),
                              "bytes": path.stat().st_size})
        matched = counts.get(kind, 0) if kind else sum(counts.values())
        return {"project_root": str(self.root), "kinds": counts, "items": items,
                "truncated": matched > len(items)}

    def list(self, kind: str = "", limit: int = 200) -> Dict[str, Any]:
        return self.inventory(kind, limit)

    def read(self, path: str | Path) -> Dict[str, Any]:
        target = self._confine(path)
        if not target.is_file():
            raise FileNotFoundError(f"文件不存在：{path}")
        size = target.stat().st_size
        rel = self._rel(target, self.root)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if target.suffix.lower() not in _TEXT_SUFFIXES:
            return {"path": rel, "binary": True, "bytes": size, "sha256": digest}
        data = target.read_bytes()
        if b"\x00" in data[:4096]:
            return {"path": rel, "binary": True, "bytes": size, "sha256": digest}
        text = data[: self.max_read_bytes].decode("utf-8", errors="replace")
        return {"path": rel, "binary": False, "bytes": size,
                "sha256": digest, "content": text,
                "truncated": size > self.max_read_bytes}

    def search(self, pattern: str, kind: str = "", glob: str = "*",
               limit: int = 100) -> List[Dict[str, Any]]:
        regex = re.compile(pattern)
        rows: List[Dict[str, Any]] = []
        for path in self._files():
            rel = path.relative_to(self.root)
            if kind and _classify(rel) != kind:
                continue
            if glob and glob != "*" and not path.match(glob):
                continue
            if path.suffix.lower() not in _TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rows.append({"path": self._rel(path, self.root),
                                 "line": number, "text": line.strip()[:300]})
                    if len(rows) >= limit:
                        return rows
        return rows

    # ── 便捷：按 kind 的常见入口 ─────────────────────────────────────────

    def rtl(self, limit: int = 200) -> Dict[str, Any]:
        return self.inventory("rtl", limit)

    def coverage(self, limit: int = 200) -> Dict[str, Any]:
        return self.inventory("coverage", limit)

    def verification(self, limit: int = 200) -> Dict[str, Any]:
        return self.inventory("verification", limit)
