"""VPlan 人工审阅门 —— LLM 抽取的契约/接口表必须人工看过后才能执行。

为什么需要它：bootstrap 产出的 `docs/specs/*`、`data/*`、`cases/*` 全是 LLM
从 spec 抽的，状态一律 `assume`/`planned`。这些表直接决定 RTL、UVM、回归和
覆盖率；**抽错一个模块接口，后面全错**。所以在“执行”之前加一道人工确认：

    python -m src.cli.commands vplan review specs/<module> --by <名字>

审阅记录存 `<project>/docs/specs/<module>_review.json`，内容是**各目录的
sha256**。人工改过任何文件 → 哈希变化 → 审阅自动失效，必须重新 review。
（不是点一次“已读”就永久放行。）

开发调试可显式设 `SIGNOFFAI_ALLOW_UNREVIEWED=1` 跳过；CLI 对应
`vplan execute --allow-unreviewed`，跳过一次会打 warning。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .source import VPlanError, VPlanProject

SCHEMA = "vplan_review_v2"
REVIEW_SUFFIX = "_review.json"
_ALLOW_ENV = "SIGNOFFAI_ALLOW_UNREVIEWED"
#: 需要人工确认的三块输入（覆盖 LLM 抽出来的全部表与执行资产）。
REVIEW_ITEMS = ("docs_specs", "data", "cases")
#: `data/` 下由 bootstrap / 生成器写入的 sidecar —— 它们不是人工审阅对象。
#: 把它们算进 review 哈希，会让一次“重新生成执行资产”把整份审阅打成过期。
GENERATED_DATA_FILES = frozenset({
    "execution_meta.csv",
    "dimensions.csv",
    "behavior.csv",
    "config_space.csv",
    "cross_matrix.csv",
    "sub_objects.csv",
    "assertions.csv",
    "scoreboards.csv",
    "execution_assets.README.md",
})
#: 生成器产出的子目录（同样不进 review 哈希）。
GENERATED_DATA_DIRS = ("generated",)


def review_path(project: VPlanProject) -> Path:
    return Path(project.root) / "docs" / "specs" / \
        f"{project.module}{REVIEW_SUFFIX}"


def _item_paths(project: VPlanProject) -> Dict[str, Path]:
    root = Path(project.root)
    return {
        "docs_specs": root / "docs" / "specs",
        "data": root / "data",
        "cases": root / "cases",
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_generated(root: Path, item: Path) -> bool:
    """`data/` 下是否属于“生成 sidecar”（不进 review 哈希）。"""
    try:
        rel = item.relative_to(root).as_posix()
    except ValueError:
        return False
    parts = rel.split("/")
    if parts[:1] != ["data"]:
        return False
    if parts[1:2] and parts[1] in GENERATED_DATA_DIRS:
        return True
    if len(parts) == 2 and parts[1] in GENERATED_DATA_FILES:
        return True
    return False


def _digest(path: Path, exclude: Path = None,
            root: Path | None = None) -> str:
    """文件/目录的 sha256；目录按相对路径 + 文件哈希排序累加。

    `root` 给出时会跳过 `_is_generated()` 判定的生成 sidecar：
    `data/dimensions.csv` 等由 bootstrap 重写，不该让“权威输入没变”的审阅过期。
    """
    if path.is_file():
        return _sha256_file(path)
    if not path.is_dir():
        return ""
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if not item.is_file():
            continue
        if exclude is not None and item == exclude:
            continue
        if "__pycache__" in item.parts:
            continue
        if root is not None and _is_generated(Path(root), item):
            continue
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(_sha256_file(item).encode("utf-8"))
    return digest.hexdigest()


def _skipped_generated(project: VPlanProject) -> List[str]:
    """当前被排除在哈希之外的生成 sidecar（相对项目的路径）。"""
    root = Path(project.root)
    data = root / "data"
    if not data.is_dir():
        return []
    out = [
        item.relative_to(root).as_posix()
        for item in sorted(data.rglob("*"))
        if item.is_file() and _is_generated(root, item)
    ]
    return out


def current_hashes(project: VPlanProject) -> Dict[str, Dict[str, Any]]:
    """当前三块输入的哈希（`exists=False` 时 sha256 为空）。"""
    root = Path(project.root)
    rp = review_path(project)
    out: Dict[str, Dict[str, Any]] = {}
    for name, path in _item_paths(project).items():
        exists = path.exists()
        out[name] = {
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "exists": exists,
            "sha256": _digest(path, exclude=rp, root=root) if exists else "",
        }
    return out


def review_status(project: VPlanProject) -> Dict[str, Any]:
    """审阅状态：`reviewed` 仅当三块输入都在、且哈希与审阅记录一致。"""
    path = review_path(project)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            manifest = {}
    except (OSError, ValueError):
        manifest = {}
    recorded = manifest.get("items") or {}
    current = current_hashes(project)
    missing = [n for n, v in current.items() if not v["exists"]]
    unreviewed = [n for n in current if n not in recorded]
    stale = [n for n, v in current.items()
             if v["exists"] and n in recorded
             and str((recorded[n] or {}).get("sha256") or "") != v["sha256"]]
    reviewed = bool(manifest.get("reviewed")) and not (
        missing or unreviewed or stale)
    return {
        "schema": SCHEMA,
        "project": str(project.root),
        "review_file": str(path),
        "reviewed": reviewed,
        "reviewer": str(manifest.get("reviewer") or ""),
        "at": str(manifest.get("at") or ""),
        "note": str(manifest.get("note") or ""),
        "missing": missing,
        "unreviewed": unreviewed,
        "stale": stale,
        "items": current,
        # 生成 sidecar 不进哈希 —— 让“哪些文件不参与审阅”是可见的，而不是隐式规则。
        "skipped_generated": _skipped_generated(project),
    }


def record_review(project: VPlanProject, reviewer: str,
                  note: str = "") -> Dict[str, Any]:
    """记录一次人工审阅（对当前三块输入打哈希）。"""
    reviewer = str(reviewer or "").strip()
    if not reviewer:
        raise ValueError("人工审阅必须给审阅人（--by <名字>）")
    current = current_hashes(project)
    missing = [n for n, v in current.items() if not v["exists"]]
    if missing:
        raise ValueError(f"缺少待审阅输入：{', '.join(missing)}")
    manifest = {
        "schema": SCHEMA,
        "reviewed": True,
        "reviewer": reviewer,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": str(note or ""),
        "items": current,
        "skipped_generated": _skipped_generated(project),
    }
    path = review_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return manifest


def _review_hint(project: VPlanProject) -> str:
    return (f"python -m src.cli.commands vplan review {project.root} "
            f"--by <你的名字>")


def require_review(project: VPlanProject) -> Dict[str, Any]:
    """执行前置门：未审阅 / 已过期 → 抛 `VPlanError`。"""
    if os.environ.get(_ALLOW_ENV, "").strip() == "1":
        return review_status(project)
    status = review_status(project)
    if status["reviewed"]:
        return status
    parts: List[str] = []
    if status["missing"]:
        parts.append(f"缺少输入 {status['missing']}")
    if status["unreviewed"]:
        parts.append(f"从未审阅 {status['unreviewed']}")
    if status["stale"]:
        parts.append(f"审阅后又改过 {status['stale']}")
    detail = "；".join(parts) or "未审阅"
    raise VPlanError(
        "VPlan 项目未通过人工审阅 —— LLM 抽取的契约/接口/用例没有被人工确认，"
        f"直接执行会把错误输入带到 RTL/UVM/回归（{detail}）。\n"
        f"请先审阅并修正 docs/specs、data、cases，然后执行：\n  "
        f"{_review_hint(project)}\n"
        f"开发调试可显式加 `--allow-unreviewed`（会记 warning）。")


__all__ = ["SCHEMA", "REVIEW_ITEMS", "review_path", "current_hashes",
           "review_status", "record_review", "require_review"]
