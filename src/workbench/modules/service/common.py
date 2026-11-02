"""三个服务入口共用的小工具 —— 只做「读 run 列表 / 打开已有模块」。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


def load_runs(ctx, limit: int = 30) -> List[Dict[str, Any]]:
    """通过绑定表读运行列表；失败返回空列表（界面显示"没有运行"而不是炸）。"""
    try:
        payload = ctx.tools.call("pipeline.runs", limit=limit)
    except Exception:                       # noqa: BLE001 界面入口不该因读失败崩
        return []
    runs = payload.get("runs") if isinstance(payload, dict) else None
    return [r for r in (runs or []) if isinstance(r, dict)]


def run_dir(run: Dict[str, Any]) -> Optional[Path]:
    text = str(run.get("dir") or run.get("output_root") or "")
    if not text:
        return None
    path = Path(text)
    return path if path.is_dir() else None


def open_module(ctx, module_id: str) -> bool:
    """打开/聚焦一个已有模块 —— 服务入口只负责导航，不重做那些页面。"""
    window = getattr(ctx, "window", None)
    if window is None:
        return False
    manager = getattr(window, "manager", None)
    if manager is not None:
        return bool(manager.open(module_id))
    focus = getattr(window, "focus_center", None)
    return bool(focus(module_id)) if callable(focus) else False


def selected_run(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return str(payload.get("run_id") or payload.get("id") or "")
    return ""


def publish_run(ctx, run_id: str) -> None:
    if not run_id:
        return
    try:
        from ...bus import TOPIC_RUN_SELECTED
        ctx.bus.publish_run_selected(run_id)
    except Exception:                       # noqa: BLE001
        pass
