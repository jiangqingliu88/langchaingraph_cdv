"""
结构化可观测日志 — trace_id + phase duration + error_code

每个请求自动生成 trace_id，贯穿整个请求生命周期。
phase 级别自动记录耗时，错误自动关联 error_code。
"""
from __future__ import annotations

import uuid, time, json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Optional


class TraceLogger:
    """结构化追踪日志器"""

    def __init__(self, log_dir: str = "logs/traces"):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._active_traces: dict[str, dict] = {}
        self._phase_timers: dict[str, float] = {}

    def start_trace(self, trace_id: str = "", context: dict = None) -> str:
        """开始一次追踪，返回 trace_id"""
        tid = trace_id or uuid.uuid4().hex[:12]
        self._active_traces[tid] = {
            "trace_id": tid,
            "started_at": datetime.now().isoformat(),
            "context": context or {},
            "phases": [],
            "errors": [],
        }
        self._phase_timers[tid] = time.time()
        return tid

    def start_phase(self, trace_id: str, phase: str, **ctx):
        """记录阶段开始"""
        if trace_id not in self._active_traces:
            self.start_trace(trace_id)
        trace = self._active_traces[trace_id]
        entry = {
            "phase": phase,
            "started_at": datetime.now().isoformat(),
            "context": ctx,
        }
        trace["phases"].append(entry)
        self._phase_timers[f"{trace_id}:{phase}"] = time.time()

    def end_phase(self, trace_id: str, phase: str, status: str = "ok",
                  error_code: str = "", detail: str = ""):
        """记录阶段结束 — 自动计算耗时"""
        timer_key = f"{trace_id}:{phase}"
        started = self._phase_timers.get(timer_key, time.time())
        duration_ms = round((time.time() - started) * 1000, 1)

        trace = self._active_traces.get(trace_id, {})
        for p in trace.get("phases", []):
            if p["phase"] == phase:
                p["status"] = status
                p["duration_ms"] = duration_ms
                p["error_code"] = error_code
                p["detail"] = detail
                p["completed_at"] = datetime.now().isoformat()
                break

        if status not in ("ok", "passed") and error_code:
            trace.setdefault("errors", []).append({
                "phase": phase, "error_code": error_code,
                "detail": detail, "duration_ms": duration_ms,
            })

    def log_error(self, trace_id: str, error_code: str, message: str,
                  domain: str = "", detail: dict = None):
        """记录错误"""
        if trace_id not in self._active_traces:
            self.start_trace(trace_id)
        self._active_traces[trace_id].setdefault("errors", []).append({
            "error_code": error_code,
            "message": message,
            "domain": domain,
            "detail": detail or {},
            "timestamp": datetime.now().isoformat(),
        })

    def end_trace(self, trace_id: str, status: str = "completed") -> dict:
        """结束追踪，返回结构化摘要并持久化"""
        trace = self._active_traces.pop(trace_id, {})
        total_duration_ms = round(
            (time.time() - self._phase_timers.pop(trace_id, time.time())) * 1000, 1)

        trace["status"] = status
        trace["total_duration_ms"] = total_duration_ms
        trace["completed_at"] = datetime.now().isoformat()

        # 生成摘要
        phases_summary = [{
            "phase": p["phase"],
            "status": p.get("status", "?"),
            "duration_ms": p.get("duration_ms", 0),
        } for p in trace.get("phases", [])]

        summary = {
            "trace_id": trace_id,
            "status": status,
            "total_duration_ms": total_duration_ms,
            "phases": phases_summary,
            "error_count": len(trace.get("errors", [])),
        }

        # 持久化到文件
        try:
            daily_file = self._log_dir / f"trace_{datetime.now().strftime('%Y%m%d')}.jsonl"
            with open(daily_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(trace, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass

        return summary

    def get_recent_traces(self, limit: int = 20) -> list[dict]:
        """获取最近的 trace 记录"""
        traces = []
        daily_file = self._log_dir / f"trace_{datetime.now().strftime('%Y%m%d')}.jsonl"
        if daily_file.exists():
            for line in list(daily_file.read_text(encoding="utf-8").strip().split("\n"))[-limit:]:
                try:
                    traces.append(json.loads(line))
                except Exception:
                    pass
        return traces

    def get_error_traces(self, limit: int = 20) -> list[dict]:
        """获取有错误的 trace"""
        traces = self.get_recent_traces(limit * 3)
        return [t for t in traces if t.get("error_count", 0) > 0][:limit]


# ── 全局单例 ──
_trace_logger: Optional[TraceLogger] = None


def get_trace_logger() -> TraceLogger:
    global _trace_logger
    if _trace_logger is None:
        _trace_logger = TraceLogger()
    return _trace_logger
