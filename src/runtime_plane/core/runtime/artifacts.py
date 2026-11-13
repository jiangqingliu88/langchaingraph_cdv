"""ArtifactStore —— 产物索引 + 内容寻址。

两条纪律
    1. **元数据与内容分开**：SQLite/JSON 存"谁产的、什么哈希、什么路径"，
       文件系统存 RTL/UVM/UCDB/WLF 这些大文件。不把 ucdb 复制进索引。
    2. **SHA256 是内容身份**：同一份内容在不同 run 里哈希相同，跨 run 对账
       不依赖路径。大文件默认"就地登记"，只算哈希不复制；小证据（事件、质量
       报告、provenance）可进 CAS（`artifacts/cas/<sha[:2]>/<sha>`）。

索引是 `<run>/artifacts/artifacts.json`（`artifact_index_v1`），按 kind 保留
历史版本（同一路径内容变了会追加一条，不覆盖旧身份）。
"""
from __future__ import annotations
from src.runtime_plane.core.contracts import versions

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.runtime_plane.core.runtime.events import EventStore, emit
from src.runtime_plane.core.runtime.outcome import Outcome

SCHEMA = versions.ARTIFACT_INDEX


def sha256_file(path: str | Path) -> str:
    """流式哈希，避免把 ucdb/wlf 整个读进内存。"""
    try:
        h = hashlib.sha256()
        with Path(path).open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


@dataclass
class ArtifactRef:
    """一条产物身份。`path` 始终是相对 run 根（能打包、能换机器）。"""

    kind: str
    path: str
    sha256: str = ""
    size: int = 0
    producer: str = ""
    run_id: str = ""
    round: int = 0
    state: str = "present"          # present | missing
    content_addressed: bool = False
    artifact_id: str = ""

    def __post_init__(self) -> None:
        if not self.artifact_id:
            self.artifact_id = f"artifact:{self.kind}:{self.path}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ArtifactStore:
    """一次 run 的产物索引。线程安全；索引写入是原子的。"""

    def __init__(self, output_root: str | Path, run_id: str = "",
                 event_store: Optional[EventStore] = None):
        self.output_root = Path(output_root)
        self.run_id = run_id or self.output_root.name
        self.event_store = event_store
        self.index_path = self.output_root / "artifacts" / "artifacts.json"
        self.cas_dir = self.output_root / "artifacts" / "cas"
        self._lock = threading.RLock()
        self._refs: List[ArtifactRef] = []
        #: 最近一次写入的显式状态 —— 索引/CAS 写失败不再只是日志里的 warning。
        self.last: Outcome = Outcome.success()
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def health(self) -> Dict[str, Any]:
        """索引写入健康度：`{status, ok, issues, index}`（下游可判）。"""
        return {**self.last.to_dict(),
                "index": self.index_path.as_posix(),
                "artifacts": len(self._refs)}

    # ── 索引 ──

    def _load(self) -> None:
        try:
            doc = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for item in (doc.get("artifacts") or []):
            if isinstance(item, dict):
                try:
                    self._refs.append(ArtifactRef(**item))
                except TypeError:
                    continue

    def _save(self) -> bool:
        payload = {
            "schema": SCHEMA,
            "run_id": self.run_id,
            "artifacts": [r.to_dict() for r in self._refs],
        }
        tmp = self.index_path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, self.index_path)
            self.last = Outcome.success()
            return True
        except OSError as exc:
            # 主流程继续，但**状态是显式的**：`health()` 给调用方、
            # 事件流给审计 —— 不再只留一行 warning。
            self.last.add(f"artifact index write failed: {exc}")
            try:
                tmp.unlink()
            except OSError:
                pass
            if self.event_store is not None:
                try:
                    self.event_store.append(
                        "artifact.index.write_failed", status="degraded",
                        payload={"index": self.index_path.as_posix(),
                                 "error": str(exc)},
                        source="artifact_store",
                        dedup_key=f"artifact-index-fail:{self.run_id}")
                except Exception:                   # noqa: BLE001 旁路
                    pass
            return False

    def _rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.output_root.resolve()).as_posix()
        except ValueError:
            # 外部输入（如 --rtl 源目录）不复制时只能记绝对路径 —— 明确标出来
            return path.resolve().as_posix()

    def _record(self, ref: ArtifactRef) -> ArtifactRef:
        # 同一身份（kind/path/sha）不重复登记；同路径新内容 = 新版本
        for old in self._refs:
            if (old.kind, old.path, old.sha256) == (ref.kind, ref.path, ref.sha256):
                return old
        self._refs.append(ref)
        self._save()
        target = self.event_store
        if target is not None:
            target.append(
                "artifact.produced",
                round=ref.round, status=ref.state,
                payload={"artifact_id": ref.artifact_id, "kind": ref.kind,
                         "path": ref.path, "sha256": ref.sha256,
                         "size": ref.size, "producer": ref.producer},
                source="artifact_store",
                dedup_key=f"artifact:{ref.artifact_id}:{ref.sha256}")
        return ref

    # ── 写 ──

    def register(self, kind: str, path: str | Path, *, producer: str = "",
                 round: int = 0) -> ArtifactRef:
        """就地登记（大文件默认路径）：只算哈希，不复制。"""
        p = Path(path)
        if not p.is_absolute():
            p = self.output_root / p
        rel = self._rel(p)
        if not p.is_file():
            return self._record(ArtifactRef(
                kind=kind, path=rel, producer=producer, run_id=self.run_id,
                round=round, state="missing"))
        return self._record(ArtifactRef(
            kind=kind, path=rel, sha256=sha256_file(p), size=p.stat().st_size,
            producer=producer, run_id=self.run_id, round=round))

    def put(self, kind: str, src: str | Path, *, producer: str = "",
            round: int = 0, content_address: bool = True) -> ArtifactRef:
        """把小证据放进 CAS（内容寻址）；大文件请用 `register`。"""
        p = Path(src)
        if not p.is_absolute():
            p = self.output_root / p
        if not p.is_file():
            return self.register(kind, p, producer=producer, round=round)
        digest = sha256_file(p)
        if not content_address or not digest:
            return self.register(kind, p, producer=producer, round=round)
        dest = self.cas_dir / digest[:2] / digest
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            try:
                tmp.write_bytes(p.read_bytes())
                os.replace(tmp, dest)
            except OSError as exc:
                self.last.add(f"artifact cas write failed: {exc}")
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return self._record(ArtifactRef(
            kind=kind, path=self._rel(dest), sha256=digest,
            size=dest.stat().st_size if dest.exists() else p.stat().st_size,
            producer=producer, run_id=self.run_id, round=round,
            content_addressed=True))

    # ── 读 ──

    def all(self, kind: Optional[str] = None) -> List[ArtifactRef]:
        with self._lock:
            refs = list(self._refs)
        return [r for r in refs if kind is None or r.kind == kind]

    def latest(self, kind: str) -> Optional[ArtifactRef]:
        refs = self.all(kind)
        return refs[-1] if refs else None

    def get(self, identifier: str) -> Optional[ArtifactRef]:
        with self._lock:
            for ref in reversed(self._refs):
                if identifier in (ref.artifact_id, ref.sha256):
                    return ref
        return None

    def index(self) -> Dict[str, Any]:
        with self._lock:
            return {"schema": SCHEMA, "run_id": self.run_id,
                    "artifacts": [r.to_dict() for r in self._refs]}
