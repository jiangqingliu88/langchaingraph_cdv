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

SCHEMA = "vplan_review_v1"
REVIEW_SUFFIX = "_review.json"
_ALLOW_ENV = "SIGNOFFAI_ALLOW_UNREVIEWED"
#: 需要人工确认的三块输入（覆盖 LLM 抽出来的全部表与执行资产）。
REVIEW_ITEMS = ("docs_specs", "data", "cases")


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


def _digest(path: Path, exclude: Path = None) -> str:
    """文件/目录的 sha256；目录按相对路径 + 文件哈希排序累加。"""
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
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(_sha256_file(item).encode("utf-8"))
    return digest.hexdigest()


def current_hashes(project: VPlanProject) -> Dict[str, Dict[str, Any]]:
    """当前三块输入的哈希（`exists=False` 时 sha256 为空）。"""
    rp = review_path(project)
    out: Dict[str, Dict[str, Any]] = {}
    for name, path in _item_paths(project).items():
        exists = path.exists()
        out[name] = {
            "path": str(path.relative_to(Path(project.root))).replace("\\", "/"),
            "exists": exists,
            "sha256": _digest(path, exclude=rp) if exists else "",
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
