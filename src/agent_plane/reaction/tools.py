"""ReAct 工具的最小契约与受限文本读取（不替代各 EDA 后端）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from src.runtime_plane.core.runtime.atomic import atomic_write_json

MAX_SOURCE_BYTES = 512 * 1024
MAX_BODY_CHARS = 16_000
MAX_DIR_ENTRIES = 200
BLOCKED_PARTS = {".git", ".env", ".signoffai", ".venv", "venv", "venv_broken"}
ALLOWED_TOP_LEVEL = {
    "src",
    "rtl",
    "docs",
    "doc",
    "examples",
    "spec",
    "specs",
    "specification",
    "source",
    "sources",
    "data",
    "inputs",
    "output",
    "review_bundle",
    "logs",
}
TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".sv",
    ".svh",
    ".v",
    ".py",
    ".tcl",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".vh",
}


def named_tool(name: str, description: str, handler: Callable[..., Any]) -> Any:
    """把一个已确认的 callable 适配为现成 tool_loop 的 Tool 协议。"""

    class NamedTool:
        def __init__(self):
            self.name = name
            self.description = description
            self._handler = handler

        def invoke(self, args):
            return self._handler(args or {})

    return NamedTool()


def unavailable_tool(name: str, description: str, reason: str) -> Any:
    """显式未配置能力：调用返回 NOT_RUN，不伪造发现/运行/证明。"""
    return named_tool(
        name,
        description,
        lambda _args: {
            "status": "NOT_RUN",
            "reason": reason or "该角色的执行后端尚未接通",
            "capability_registered": True,
            "capability_executed": False,
        },
    )


def actor_relative(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def bounded_directory(root: str | Path, relative: str = "") -> Path:
    """工作区限制：路径不可越过根，也不读取项目私有会话/环境目录。"""
    workspace = Path(root).resolve()
    suffix = str(relative or "").strip()
    if not suffix:
        return workspace
    candidate = Path(suffix)
    target = (workspace / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
    if not actor_relative(workspace, target):
        raise ValueError(f"路径越过工作区：{suffix}")
    relative_parts = target.relative_to(workspace).parts
    if relative_parts:
        if relative_parts[0] not in ALLOWED_TOP_LEVEL:
            raise ValueError(f"不允许的角色读取范围：{relative_parts[0]}")
    if any(part in BLOCKED_PARTS for part in relative_parts):
        raise ValueError("该目录属于私有会话或执行环境，不提供给普通 Agent 读取")
    return target


def _line_range(arguments: dict[str, Any], total_lines: int) -> tuple[int, int]:
    if any(isinstance(arguments.get(k), bool) for k in ("line_start", "line_end")):
        raise ValueError("行号不能是布尔值")
    try:
        start = int(arguments.get("line_start", 1))
        end = int(arguments.get("line_end", total_lines))
    except (TypeError, ValueError) as exc:
        raise ValueError("line_start/line_end 必须为整数") from exc
    if start < 1 or end < start or end > total_lines:
        raise ValueError(f"非法行范围：{start}..{end}（文档共 {total_lines} 行）")
    return start, end


def read_source(root: str | Path, args: dict[str, Any]) -> str:
    """读取有边界的文本片段/行范围，并记录实际源与字节哈希。"""
    locator = args.get("path") or args.get("file")
    if not isinstance(locator, str) or not locator.strip():
        raise ValueError("read_source 需要明确的 path，不自动猜测全项目文件")
    target = bounded_directory(root, locator)
    if not target.is_file():
        raise FileNotFoundError(f"目标不是文件：{locator}")
    if target.suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError(f"该读取器不支持二进制/未声明格式：{target.suffix}")
    size = target.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise ValueError(f"文本超过 {MAX_SOURCE_BYTES} 字节，拒绝假装已经完整阅读")
    data = target.read_bytes()
    text = data.decode("utf-8")
    lines = text.splitlines()
    start, end = _line_range(args, len(lines)) if lines else (1, 0)
    relative = target.relative_to(Path(root).resolve()).as_posix()
    digest = hashlib.sha256(data).hexdigest()
    selected = "\n".join(lines[start - 1 : end])
    excerpt = selected[:MAX_BODY_CHARS]
    problems = []
    expected_hash = str(args.get("document_sha256") or "")
    if expected_hash and expected_hash != digest:
        problems.append("document_sha256_mismatch")
    quote = args.get("quote")
    if quote and quote not in selected:
        problems.append("quote_not_in_requested_line_range")
    return json.dumps(
        {
            "status": "OBSERVED" if not problems else "INCOMPLETE",
            "locator": relative,
            "document_sha256": digest,
            "line_start": start,
            "line_end": end,
            "literal_quote": excerpt,
            "truncated": len(selected) > len(excerpt),
            "scope": "bounded_text_excerpt; not a complete semantic proof",
            "errors": problems,
        },
        ensure_ascii=False,
    )


def list_source_files(root: str | Path, args: dict[str, Any]) -> str:
    """限定单个声明目录及文本类型，不枚举宿主用户其他目录。"""
    relative = args.get("path") or "examples"
    target = bounded_directory(root, relative)
    if not target.is_dir():
        raise FileNotFoundError(f"目标不是可枚举目录：{relative}")
    rows = []
    for item in target.iterdir():
        if item.stem in BLOCKED_PARTS or not item.is_file() or item.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rows.append(item.relative_to(Path(root).resolve()).as_posix())
        if len(rows) >= MAX_DIR_ENTRIES:
            break
    return json.dumps(
        {
            "status": "OBSERVED",
            "directory": relative,
            "files": rows,
            "count": len(rows),
            "bounded": True,
        },
        ensure_ascii=False,
    )


def write_trace(root: str | Path, marker: str, value: dict[str, Any]) -> dict[str, Any]:
    """只有调用方明确给出可写工作区时才启用；不覆盖同名历史记录。"""
    directory = bounded_directory(root, marker)
    path = directory / f"react_{marker}.json"
    if path.exists():
        raise FileExistsError(f"已有同名 ReAct 记录，拒绝覆盖：{path}")
    atomic_write_json(path, value)
    return {"path": str(path), "status": "OBSERVED"}
