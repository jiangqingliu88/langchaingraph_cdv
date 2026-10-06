"""运行相关视图的共用件 —— 三个模块（runs / pipeline / evidence）都用到。

为什么放在模块**外面**：模块之间不该互相 import（那会让插件化名存实亡），
但"把一条阶段事件渲染成一行表格"这种事应当只有一份实现。放在 `vms/` 这一层，
它既不是模块、也不被任何模块反向依赖。

这里只有**纯函数与小组件**：不查工具、不碰磁盘、不认识 RunService。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from ...ui import theme

#: 事件种类 → 中文短语。未知种类原样显示 —— 界面里出现一个生词，
#: 好过出现空白（后者会让人以为"这一步什么都没发生"）。
KIND_LABELS = {
    "run.started": "开始",
    "run.finished": "结束",
    "run.failed": "失败",
    "run.cancelled": "已取消",
    "run.interrupted": "等待审批",
    "run.resumed": "已重入",
    "stage.started": "开始",
    "stage.finished": "完成",
    "stage.failed": "失败",
    "coverage.updated": "覆盖率更新",
    "decision": "决策",
    "approval.requested": "等待审批",
    "approval.decided": "审批结果",
    "progress": "进度",
    "note": "说明",
}

#: 运行状态 → 中文。与 RunRepository.journal_summary 的 `state` 对齐。
RUN_STATE_LABELS = {
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
    # "等人" 必须单独一档：归进"运行中"的话，一次暂停的运行看起来就像卡住了
    "waiting": "等待审批",
    "": "未知",
}


def status_color(status: str, *, kind: str = "") -> str:
    """状态 → 颜色。**颜色只是帮助扫读，信息由文字承担**（与 sim_log 同一原则）。"""
    palette = theme.current()
    if kind in ("run.failed", "stage.failed") or status in ("failed", "error"):
        return palette.error
    if kind == "run.cancelled" or status in ("cancelled", "waiting"):
        return palette.warning
    if status in ("ok", "passed", "completed", "approve") or kind == "run.finished":
        return palette.ok
    if status in ("running", "review", "skip", "skipped"):
        return palette.accent
    return palette.muted


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind or "")


def one_line(event: Dict[str, Any]) -> str:
    """一条事件 → 一行摘要。优先级：payload.message > payload.error > 关键字段。"""
    payload = event.get("payload") or {}
    if isinstance(payload, dict):
        for key in ("message", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        bits = [f"{k}={_short(v)}" for k, v in payload.items()
                if k in ("status", "passed", "total", "count", "score",
                         "converged", "final_coverage", "functional", "total_coverage",
                         "action", "decision", "reason")]
        if bits:
            return " ".join(bits)
        delta = payload.get("delta")
        if isinstance(delta, dict) and delta:
            return "、".join(sorted(delta)[:6])
    return ""


def _short(value: Any, limit: int = 60) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def stage_statuses(events: List[Dict[str, Any]]) -> Dict[str, str]:
    """运行日志 → `{stage_id: 最新状态}`。

    后出现的覆盖先出现的 —— 所以拿到的是**每个阶段最后一次的落点**。
    用来给流程图上的节点上色，所以只要"最新那一下"。
    """
    out: Dict[str, str] = {}
    for event in events:
        stage = str(event.get("stage") or "")
        if not stage:
            continue
        if event.get("kind") in ("stage.started", "stage.finished", "stage.failed"):
            out[stage] = str(event.get("status") or "")
    return out


def stage_rows(summary: Dict[str, Any]) -> List[Dict[str, str]]:
    """`journal_summary()` 的 stages → 表格行。"""
    rows = []
    for stage in summary.get("stages", []) or []:
        rows.append({
            "轮次": str(stage.get("round", 0)),
            "阶段": stage.get("title") or stage.get("stage", ""),
            "状态": stage.get("status", ""),
            "耗时": _duration(stage.get("duration_s", 0.0)),
        })
    return rows


def _duration(seconds: Any) -> str:
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    if value < 60:
        return f"{value:.1f}s"
    return f"{int(value // 60)}m{int(value % 60):02d}s"


# ════════════════════════════════════════════════════════════════
# 阶段时间线
# ════════════════════════════════════════════════════════════════

class StageTimeline(QTreeWidget):
    """按轮次分组的阶段时间线。

    两级：`轮次 N` → 各阶段。一轮都还没转完时，阶段直接挂在"第 1 轮"下 ——
    界面不因为"轮次还不知道"就什么都不显示。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["阶段", "状态", "耗时", "摘要"])
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setColumnWidth(0, 200)
        self.setColumnWidth(1, 70)
        self.setColumnWidth(2, 70)

    def set_events(self, events: List[Dict[str, Any]]) -> None:
        """从事件重建整棵树。

        事件量级是几十到几百条，重建比增量维护简单得多，也不会出现
        "状态跟实际对不上"的那种 bug。真到上千条再谈增量。
        """
        self.clear()
        groups: Dict[int, QTreeWidgetItem] = {}
        for event in events:
            stage = event.get("stage") or ""
            kind = event.get("kind") or ""
            if not stage or kind.endswith(".started") or kind == "run.started":
                continue
            # `round_num` 在状态里是"已经推进过几轮"：`round_bump` 把 0 变成 1 之后
            # 才算进入第 1 轮的身体，所以**它本身就是 1-based**，别再加一。
            # 加一的话首轮会被显示成"轮次 2"，而它下面的阶段恰恰是第 1 轮的。
            round_num = max(1, int(event.get("round", 0) or 0))
            parent = groups.get(round_num)
            if parent is None:
                parent = QTreeWidgetItem(self, [f"轮次 {round_num}", "", "", ""])
                parent.setFirstColumnSpanned(True)
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                groups[round_num] = parent
                parent.setExpanded(True)

            color = QColor(status_color(event.get("status", ""), kind=kind))
            item = QTreeWidgetItem(parent, [
                event.get("title") or stage,
                kind_label(kind),
                _duration(event.get("duration_s", 0.0)),
                one_line(event),
            ])
            for column in range(4):
                item.setForeground(column, QBrush(color))
            item.setData(0, Qt.ItemDataRole.UserRole, event)
        self.expandAll()

    def selected_event(self) -> Optional[Dict[str, Any]]:
        items = self.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.ItemDataRole.UserRole)


# ════════════════════════════════════════════════════════════════
# 运行列表
# ════════════════════════════════════════════════════════════════

def run_label(run: Dict[str, Any]) -> str:
    """一行运行标题：状态 + 覆盖率（有的话）。"""
    run_id = run.get("run_id", "")
    state = RUN_STATE_LABELS.get(str(run.get("state", "")), "")
    coverage = run.get("effective_coverage") or run.get("final_coverage")
    bits = [b for b in (state, f"{coverage}%" if coverage else "") if b]
    return f"{run_id}　{' · '.join(bits)}" if bits else run_id


def run_tooltip(run: Dict[str, Any]) -> str:
    lines = [f"运行：{run.get('run_id', '')}",
             f"目录：{run.get('dir', '')}",
             f"状态：{RUN_STATE_LABELS.get(str(run.get('state', '')), '未知')}"]
    if run.get("current_stage"):
        lines.append(f"当前阶段：{run.get('current_title') or run['current_stage']}")
    if run.get("event_count"):
        lines.append(f"事件数：{run['event_count']}")
    if run.get("converged") is not None and run.get("final_coverage"):
        lines.append(f"覆盖率：{run.get('final_coverage')}%"
                     f"{'（达标）' if run.get('converged') else '（未达标）'}")
    return "\n".join(lines)
