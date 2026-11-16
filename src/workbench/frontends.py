"""两种前端模式 —— 系统对外的唯一入口清单。

产品口径只有两种：

1. **CLI（headless）**：脚本、回归、CI。每个 agent 都有子命令，输出 JSON /
   退出码，不依赖 Qt、不要求人工待在终端前。
2. **PySide6 UI / TUI（interactive）**：终端 REPL 与 PySide6 桌面窗口。按
   chat / plan / verify 区分任务，能看执行步骤、日志/状态，能浏览/编辑
   Markdown 产物。

`chat / plan / verify` 是**两种模式下共用的交互方式**，不是第三种前端。
本模块只做静态清单与能力描述；真正执行仍走 `modes.interaction` /
`agent_mode_service` / `verify_mode`，不新造执行链。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class FrontendMode:
    id: str
    title: str
    headless: bool
    entrypoints: Tuple[str, ...]
    capabilities: Tuple[str, ...]
    note: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "headless": self.headless,
            "entrypoints": list(self.entrypoints),
            "capabilities": list(self.capabilities),
            "note": self.note,
        }


FRONTEND_MODES: Tuple[FrontendMode, ...] = (
    FrontendMode(
        id="cli",
        title="CLI（headless）",
        headless=True,
        entrypoints=(
            "vagent <agent> chat '<prompt>'",
            "vagent agents chat <agent> '<prompt>'",
            "vagent -p '<task>' --mode agent|verify",
            "vagent chat --mode chat|plan|verify '<goal>'",
            "vagent verify / runs / signoff / regression ...",
        ),
        capabilities=(
            "每个 agent 独立子命令",
            "JSON 输出与稳定退出码",
            "脚本 / 回归 / CI 可无人值守",
            "单次任务，不依赖 Qt",
        ),
        note="chat/plan/verify 均可单次调用；plan 的审批用 --resume 恢复。",
    ),
    FrontendMode(
        id="ui",
        title="PySide6 UI / TUI（interactive）",
        headless=False,
        entrypoints=(
            "vagent gui",
            "vagent",
            "vagent chat --repl [--mode chat|plan|verify]",
        ),
        capabilities=(
            "独立 TUI 主窗口 + 老 PySide6 GUI",
            "按 chat/plan/verify 区分任务",
            "监控执行步骤（run_events.jsonl）",
            "查看日志 / 状态 / 审批",
            "浏览与编辑 Markdown 产物",
        ),
        note="PySide6 窗口与终端 REPL 共用同一套模式与审批语义。",
    ),
)

_BY_ID = {mode.id: mode for mode in FRONTEND_MODES}


def mode(mode_id: str) -> Optional[FrontendMode]:
    return _BY_ID.get(str(mode_id or "").strip().lower())


def mode_ids() -> Tuple[str, ...]:
    return tuple(mode.id for mode in FRONTEND_MODES)


def rows() -> list[Dict[str, object]]:
    return [mode.to_dict() for mode in FRONTEND_MODES]


__all__ = ["FrontendMode", "FRONTEND_MODES", "mode", "mode_ids", "rows"]
