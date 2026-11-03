"""Workbench 只读查询层 —— 页面只渲染 ViewModel，不直接读文件/调工具。

写操作走 `src.app.services`；本层只读 run-local facts（events / artifacts /
evidence / soc summary）。没有 Qt 依赖，可在无显示器环境测试。
"""
from src.workbench.query.runs import (
    list_soc_runs, read_events, read_artifact_index, run_summary,
)
from src.workbench.query.evidence import read_envelope, validate_evidence

__all__ = [
    "list_soc_runs", "read_events", "read_artifact_index", "run_summary",
    "read_envelope", "validate_evidence",
]
