"""Job 的输入/输出契约。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class JobSpec:
    """一次 EDA/脚本进程。`argv` 是**适配前**的命令（白名单检查看它）。"""

    name: str
    argv: List[str]
    cwd: Path
    run_id: str = ""
    purpose: str = "tool"          # regression | build | sim | coverage | compile | tool
    timeout_s: Optional[float] = 3600.0   # None = 不限时（不推荐，但允许）
    run_dir: Optional[Path] = None
    env: Dict[str, str] = field(default_factory=dict)
    capture_dir: Optional[Path] = None

    def __post_init__(self) -> None:
        self.cwd = Path(self.cwd)
        if self.run_dir is not None:
            self.run_dir = Path(self.run_dir)
        if self.capture_dir is not None:
            self.capture_dir = Path(self.capture_dir)


@dataclass
class JobResult:
    job_id: str
    name: str
    argv: List[str]
    cwd: str
    purpose: str
    status: str = "completed"       # completed | failed | timeout | denied
    exit_code: Optional[int] = None
    timed_out: bool = False
    killed_tree: bool = False
    duration_s: float = 0.0
    pid: int = 0
    started_at: str = ""
    ended_at: str = ""
    stdout_path: str = ""
    stderr_path: str = ""
    stdout_sha256: str = ""
    stderr_sha256: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
