"""Evidence 1.0 — 内容寻址存储 + 哈希链 + 不可变证据包。"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.objects = self.root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, data: bytes, *, kind: str = "raw") -> Dict[str, str]:
        digest = sha256_bytes(data)
        path = self.objects / digest
        if not path.exists():
            _atomic_write(path, data)
        return {"id": digest, "kind": kind, "path": str(path), "sha256": digest}

    def put_text(self, text: str, *, kind: str = "text") -> Dict[str, str]:
        return self.put_bytes(text.encode("utf-8"), kind=kind)

    def put_file(self, path: str | Path, *, kind: str = "file") -> Dict[str, str]:
        path = Path(path).resolve()
        return self.put_bytes(path.read_bytes(), kind=kind)

    def verify(self, artifact: Dict[str, str]) -> bool:
        path = Path(str(artifact.get("path") or ""))
        return path.is_file() and sha256_file(path) == artifact.get("sha256")


class Provenance:
    """哈希链事件日志；每条事件包含前一条哈希。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: Dict[str, Any]) -> Dict[str, Any]:
        prev = ""
        if self.path.is_file():
            lines = self.path.read_text(encoding="utf-8").splitlines()
            if lines:
                prev = json.loads(lines[-1]).get("hash", "")
        row = dict(event)
        row["prev"] = prev
        row["hash"] = sha256_bytes(json.dumps(
            {**row, "prev": prev}, sort_keys=True,
            ensure_ascii=False).encode("utf-8"))
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return row

    def verify(self) -> List[str]:
        errors: List[str] = []
        prev = ""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ["provenance missing"]
        for index, line in enumerate(lines, 1):
            try:
                row = json.loads(line)
            except ValueError:
                errors.append(f"line {index}: invalid json")
                continue
            if row.get("prev") != prev:
                errors.append(f"line {index}: prev mismatch")
            calc = sha256_bytes(json.dumps(
                {k: v for k, v in row.items() if k != "hash"},
                sort_keys=True, ensure_ascii=False).encode("utf-8"))
            if row.get("hash") != calc:
                errors.append(f"line {index}: hash mismatch")
            prev = row.get("hash", "")
        return errors
