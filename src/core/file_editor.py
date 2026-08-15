"""
精确文件编辑 —— Claude Code 风格的安全编辑原语（harness 最后一块通用能力）。

与"整体读写"（read_file/write_file）不同，这里提供：
  1. edit_file   精确字符串替换：old_string 必须唯一匹配，否则拒绝（冲突检测）
  2. apply_patch unified diff 应用：标准补丁格式，支持多 hunk

这是自愈/蒸馏/重构"精准改一个地方不碰别处"的基础——避免正则替换的脆弱性，
避免整体重写破坏无关内容。

用法:
    from src.core.file_editor import edit_file, apply_patch
    r = edit_file("rtl/dut.sv", "a + b", "a - b")
    # → {"success": True, "replaced": 1} 或 {"success": False, "error": "..."}
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# edit_file：精确字符串替换 + 冲突检测
# ═══════════════════════════════════════════════════════════════

def edit_file(file_path: str, old_string: str, new_string: str,
              replace_all: bool = False) -> Dict[str, Any]:
    """精确替换文件中的 old_string → new_string。

    冲突检测：
      - old_string 出现 0 次 → 拒绝（找不到，可能文件已被修改）
      - old_string 出现多次且 replace_all=False → 拒绝（不唯一，需更多上下文）

    返回 {success, replaced, error}。
    """
    path = Path(file_path)
    if not path.exists():
        return {"success": False, "replaced": 0, "error": f"文件不存在: {file_path}"}
    if not old_string:
        return {"success": False, "replaced": 0, "error": "old_string 不能为空"}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"success": False, "replaced": 0, "error": f"读取失败: {e}"}

    count = content.count(old_string)
    if count == 0:
        return {"success": False, "replaced": 0,
                "error": f"old_string 未找到（0 次匹配）——文件可能已被修改，需先 read_file"}
    if count > 1 and not replace_all:
        return {"success": False, "replaced": 0,
                "error": f"old_string 不唯一（{count} 次匹配）——请提供更多上下文使匹配唯一"}

    new_content = content.replace(old_string, new_string) if replace_all \
        else content.replace(old_string, new_string, 1)
    try:
        path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return {"success": False, "replaced": 0, "error": f"写入失败: {e}"}

    return {"success": True, "replaced": count if replace_all else 1, "error": ""}


# ═══════════════════════════════════════════════════════════════
# apply_patch：unified diff 应用
# ═══════════════════════════════════════════════════════════════

def apply_patch(patch_text: str, base_dir: str = ".") -> Dict[str, Any]:
    """应用 unified diff 补丁（标准 git diff 格式）。

    支持格式:
      --- a/path/to/file
      +++ b/path/to/file
      @@ -l,count +l,count @@
      -删除行
      +新增行
       上下文行

    返回 {success, files_changed, hunks_applied, error}。
    """
    if not patch_text or not patch_text.strip():
        return {"success": False, "files_changed": 0, "error": "补丁为空"}

    base = Path(base_dir)
    hunks = _parse_patch(patch_text)
    if not hunks:
        return {"success": False, "files_changed": 0,
                "error": "无法解析补丁（缺少 ---/+++ 或 @@ hunk）"}

    files_changed = 0
    errors = []
    for file_path, file_hunks in hunks.items():
        target = base / file_path
        if not target.exists():
            errors.append(f"文件不存在: {file_path}")
            continue
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            errors.append(f"读取失败 {file_path}: {e}")
            continue
        new_content, applied = _apply_hunks(content, file_hunks)
        if applied:
            try:
                target.write_text(new_content, encoding="utf-8")
                files_changed += 1
            except Exception as e:
                errors.append(f"写入失败 {file_path}: {e}")

    if errors and files_changed == 0:
        return {"success": False, "files_changed": 0, "error": "; ".join(errors[:3])}
    return {"success": True, "files_changed": files_changed,
            "error": "; ".join(errors) if errors else ""}


def _parse_patch(patch_text: str) -> Dict[str, List[Dict]]:
    """解析 unified diff，返回 {file_path: [hunk, ...]}。

    hunk = {"old_start", "old_count", "new_start", "new_count", "lines": [(op, text)]}
    op ∈ '+' | '-' | ' '（上下文）
    """
    files: Dict[str, List[Dict]] = {}
    current_file = None
    current_hunk = None
    for line in patch_text.splitlines():
        if line.startswith("--- "):
            # --- a/file 或 --- /dev/null
            m = re.match(r"--- (?:a/)?(\S+)", line)
            current_file = m.group(1) if m else None
            continue
        if line.startswith("+++ "):
            m = re.match(r"\+\+\+ (?:b/)?(\S+)", line)
            if m:
                current_file = m.group(1)
                files.setdefault(current_file, [])
            continue
        if line.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if m and current_file:
                current_hunk = {
                    "old_start": int(m.group(1)),
                    "old_count": int(m.group(2) or 1),
                    "new_start": int(m.group(3)),
                    "new_count": int(m.group(4) or 1),
                    "lines": [],
                }
                files[current_file].append(current_hunk)
            continue
        if current_hunk is not None:
            if line.startswith("+"):
                current_hunk["lines"].append(("+", line[1:]))
            elif line.startswith("-"):
                current_hunk["lines"].append(("-", line[1:]))
            elif line.startswith(" "):
                current_hunk["lines"].append((" ", line[1:]))
            elif line == "":
                current_hunk["lines"].append((" ", ""))
    return files


def _apply_hunks(content: str, hunks: List[Dict]) -> tuple:
    """按 hunk 应用增删，返回 (new_content, applied)。"""
    lines = content.splitlines()
    new_lines = []
    pos = 0  # 当前处理到的行索引
    applied = False

    for hunk in hunks:
        old_start = hunk["old_start"] - 1  # 0-based
        # 跳过 hunk 之前的行
        while pos < old_start and pos < len(lines):
            new_lines.append(lines[pos])
            pos += 1
        # 应用 hunk 内的行
        for op, text in hunk["lines"]:
            if op == " ":
                # 上下文行：验证匹配（若当前行不匹配则跳过，宽松处理）
                if pos < len(lines) and lines[pos] == text:
                    new_lines.append(lines[pos])
                    pos += 1
                else:
                    new_lines.append(text)
            elif op == "-":
                # 删除行：跳过源文件的这一行
                if pos < len(lines):
                    pos += 1
            elif op == "+":
                # 新增行
                new_lines.append(text)
        applied = True

    # 追加剩余行
    while pos < len(lines):
        new_lines.append(lines[pos])
        pos += 1

    return "\n".join(new_lines) + ("\n" if content.endswith("\n") else ""), applied


# ═══════════════════════════════════════════════════════════════
# ITool 封装（接入 ToolHub）
# ═══════════════════════════════════════════════════════════════

from src.core.tool_protocol import (
    BaseTool, ToolManifest, ToolResult, ExecutionContext, ToolRisk,
)


class EditFileTool(BaseTool):
    """精确字符串替换工具（冲突检测）。"""

    @property
    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="file.edit",
            version="1.0.0",
            description="精确替换文件中的字符串（old_string 必须唯一匹配，否则拒绝）。用于精准改一个地方不碰别处。",
            input_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "文件路径"},
                    "old_string": {"type": "string", "description": "要替换的原字符串（须唯一）"},
                    "new_string": {"type": "string", "description": "替换后的字符串"},
                    "replace_all": {"type": "boolean", "description": "替换所有匹配（默认 false）"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
            risk_level=ToolRisk.WRITE,
            category="file_edit",
            tags=["file", "edit", "replace"],
        )

    async def _execute_impl(self, args, context: ExecutionContext) -> ToolResult:
        base = context.output_dir or "."
        r = edit_file(str(Path(base) / args["file_path"]),
                      args["old_string"], args["new_string"],
                      args.get("replace_all", False))
        if r["success"]:
            return ToolResult.ok(r)
        return ToolResult.fail(r["error"], r)


class ApplyPatchTool(BaseTool):
    """unified diff 补丁应用工具。"""

    @property
    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="file.apply_patch",
            version="1.0.0",
            description="应用 unified diff 补丁（标准 git diff 格式），支持多文件多 hunk。",
            input_schema={
                "type": "object",
                "properties": {
                    "patch": {"type": "string", "description": "unified diff 补丁文本"},
                },
                "required": ["patch"],
            },
            risk_level=ToolRisk.WRITE,
            category="file_edit",
            tags=["file", "patch", "diff"],
        )

    async def _execute_impl(self, args, context: ExecutionContext) -> ToolResult:
        base = context.output_dir or "."
        r = apply_patch(args["patch"], base)
        if r["success"]:
            return ToolResult.ok(r)
        return ToolResult.fail(r["error"], r)
