"""生成文件操作 —— 签名判定 / 清理 / merge 备份 / 生成报告。

从 `tool_uvm/gen_uvm.py` 搬出；调用方直接从这里导入（门面已删）。
不渲染、不判断业务，只做文件与报告。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .region_injector import BANNER_MARKER, TOOL_VERSION


def backup_merge_source(merge_source: Path) -> Path:
    """备份 merge_source 目录 → <merge_source>_backup_<时间戳>。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = merge_source.with_name(f"{merge_source.name}_backup_{ts}")
    shutil.copytree(merge_source, backup)
    return backup


def _is_generated_file(path: Path) -> bool:
    """文件是否带生成签名（clean 只删除此类文件）。"""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return False
    return BANNER_MARKER in head


def _write_report_json(output_root: Path, *, generated: int, skipped: int,
                       validation_issues: List[Any], merge_reports: List[Any],
                       load_errors: List[str], gate_results: List[Dict[str, str]],
                       schema_issues: Optional[List[Any]] = None,
                       inputs: Optional[List[Path]] = None) -> Path:
    """P2-4: 结构化生成报告（供 Agent 决策 / 签核证据包引用）。"""
    report = {
        "tool": "tool_uvm",
        "version": TOOL_VERSION,
        "inputs": [str(p) for p in (inputs or [])],
        "generated": generated,
        "skipped": skipped,
        "schema": {
            "errors": [i.__dict__ for i in (schema_issues or []) if i.severity == "error"],
            "warnings": [i.__dict__ for i in (schema_issues or []) if i.severity == "warning"],
        },
        "validation": {
            "errors": [i.__dict__ for i in validation_issues if i.severity == "error"],
            "warnings": [i.__dict__ for i in validation_issues if i.severity == "warning"],
        },
        "merge": {
            "blocks": [
                {"file": r.relpath,
                 "items": [b.__dict__ for b in r.blocks],
                 "missing": r.missing}
                for r in merge_reports if r.blocks or r.missing
            ],
            "load_errors": load_errors,
        },
        "gate": gate_results,
    }
    report_path = output_root / "generation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return report_path


def _clean_generated(dest_root: Path) -> int:
    """-c/--clean：删除 dest_dir 下所有带签名的生成文件，并清理空目录。"""
    if not dest_root.is_dir():
        return 0
    removed = 0
    for path in sorted(dest_root.rglob("*"), reverse=True):
        if path.is_file() and _is_generated_file(path):
            path.unlink()
            removed += 1
    for path in sorted(dest_root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return removed

