"""
可观测性与运维指标 — 性能追踪 + 指标仪表盘 + 慢查询检测

核心能力:
  1. MetricsCollector — 采集流水线耗时、签核周期、模块失败率、用户活跃度
  2. SlowQueryDetector — 慢查询日志和告警
  3. HealthChecker — 系统健康检查
  4. MetricsAPI — 运维仪表盘数据接口

用法:
  from src.infra.observability import MetricsCollector, get_metrics

  collector = get_metrics()
  collector.record_pipeline_run(run_id, duration, passed, total)
  collector.record_signoff_cycle(signoff_id, from_status, to_status, elapsed)

  stats = collector.get_dashboard_stats()
  # → pipeline_avg_duration, signoff_cycle_time, module_failure_rates...
"""

from __future__ import annotations
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════
# 指标数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class PipelineMetrics:
    """流水线指标"""
    run_id: str
    workflow: str
    state: str
    duration_s: float
    phases_total: int
    phases_passed: int
    phases_failed: int
    coverage_line_pct: float = 0.0
    started_at: str = ""
    completed_at: str = ""


@dataclass
class SignoffMetrics:
    """签核指标"""
    signoff_id: int
    title: str
    cycle_time_minutes: float  # 从提交到审批的耗时
    status: str
    approver: str = ""
    created_at: str = ""
    approved_at: str = ""


@dataclass
class ErrorMetrics:
    """错误指标"""
    module: str
    error_type: str
    count: int = 0
    last_occurred: str = ""
    sample_error: str = ""


# ═══════════════════════════════════════════════════════════
# 指标采集器
# ═══════════════════════════════════════════════════════════

class MetricsCollector:
    """运行时指标采集器 — 线程安全"""

    def __init__(self, max_retention: int = 1000):
        self._lock = threading.Lock()
        self._pipeline_runs: List[PipelineMetrics] = []
        self._signoff_cycles: List[SignoffMetrics] = []
        self._errors: Dict[str, List[ErrorMetrics]] = defaultdict(list)
        self._api_calls: Dict[str, int] = defaultdict(int)
        self._api_latencies: Dict[str, List[float]] = defaultdict(list)
        self._user_actions: Dict[str, int] = defaultdict(int)
        self._module_failures: Dict[str, int] = defaultdict(int)
        self._max_retention = max_retention
        self._start_time = time.time()

    # ── 流水线指标 ──

    def record_pipeline_run(self, run_id: str, workflow: str, state: str, duration_s: float,
                            phases_total: int, phases_passed: int, phases_failed: int = 0,
                            coverage_line_pct: float = 0.0,
                            started_at: str = "", completed_at: str = ""):
        with self._lock:
            m = PipelineMetrics(run_id=run_id, workflow=workflow, state=state,
                                duration_s=duration_s, phases_total=phases_total,
                                phases_passed=phases_passed, phases_failed=phases_failed,
                                coverage_line_pct=coverage_line_pct,
                                started_at=started_at, completed_at=completed_at)
            self._pipeline_runs.append(m)
            if len(self._pipeline_runs) > self._max_retention:
                self._pipeline_runs = self._pipeline_runs[-self._max_retention:]

    # ── 签核指标 ──

    def record_signoff_cycle(self, signoff_id: int, title: str, status: str,
                              cycle_time_minutes: float, approver: str = "",
                              created_at: str = "", approved_at: str = ""):
        with self._lock:
            m = SignoffMetrics(signoff_id=signoff_id, title=title, status=status,
                               cycle_time_minutes=cycle_time_minutes, approver=approver,
                               created_at=created_at, approved_at=approved_at)
            self._signoff_cycles.append(m)
            if len(self._signoff_cycles) > self._max_retention:
                self._signoff_cycles = self._signoff_cycles[-self._max_retention:]

    # ── 错误指标 ──

    def record_error(self, module: str, error_type: str, error_msg: str = ""):
        with self._lock:
            key = f"{module}:{error_type}"
            existing = [e for e in self._errors.get(key, [])]
            if existing:
                existing[0].count += 1
                existing[0].last_occurred = datetime.now().isoformat()
                if error_msg:
                    existing[0].sample_error = error_msg[:200]
            else:
                self._errors[key].append(ErrorMetrics(
                    module=module, error_type=error_type, count=1,
                    last_occurred=datetime.now().isoformat(),
                    sample_error=error_msg[:200],
                ))

    # ── API 调用指标 ──

    def record_api_call(self, endpoint: str, latency_ms: float):
        with self._lock:
            self._api_calls[endpoint] += 1
            self._api_latencies[endpoint].append(latency_ms)
            if len(self._api_latencies[endpoint]) > 100:
                self._api_latencies[endpoint] = self._api_latencies[endpoint][-100:]

    # ── 用户活跃度 ──

    def record_user_action(self, username: str, action: str):
        with self._lock:
            self._user_actions[f"{username}:{action}"] += 1

    # ── 模块失败率 ──

    def record_module_failure(self, module_name: str):
        with self._lock:
            self._module_failures[module_name] += 1

    # ── 仪表盘统计 ──

    def get_dashboard_stats(self) -> dict:
        """获取运维仪表盘数据"""
        with self._lock:
            # 流水线统计
            pipeline_durations = [p.duration_s for p in self._pipeline_runs]
            pipeline_avg = sum(pipeline_durations) / max(len(pipeline_durations), 1)
            pipeline_recent = self._pipeline_runs[-20:]
            pipeline_pass_rate = sum(1 for p in pipeline_recent if p.state == "completed") / max(len(pipeline_recent), 1)

            # 签核统计
            signoff_times = [s.cycle_time_minutes for s in self._signoff_cycles]
            signoff_avg = sum(signoff_times) / max(len(signoff_times), 1)
            signoff_approved = sum(1 for s in self._signoff_cycles if s.status == "approved")

            # API 统计
            total_api_calls = sum(self._api_calls.values())
            slow_apis = []
            for endpoint, latencies in self._api_latencies.items():
                avg_latency = sum(latencies) / max(len(latencies), 1)
                p99_latency = sorted(latencies)[int(len(latencies) * 0.99)] if len(latencies) >= 100 else max(latencies) if latencies else 0
                if avg_latency > 500 or p99_latency > 2000:  # >500ms avg or >2s p99
                    slow_apis.append({
                        "endpoint": endpoint,
                        "calls": self._api_calls.get(endpoint, 0),
                        "avg_ms": round(avg_latency, 1),
                        "p99_ms": round(p99_latency, 1),
                    })

            # 错误统计
            error_summary = []
            for key, errs in self._errors.items():
                for e in errs[:1]:  # 每组取第一个
                    error_summary.append({
                        "module": e.module, "error_type": e.error_type,
                        "count": e.count, "last_occurred": e.last_occurred,
                    })

            # 用户活跃度
            user_summary = {}
            for k, v in self._user_actions.items():
                user, action = k.split(":", 1)
                if user not in user_summary:
                    user_summary[user] = {"actions": 0, "top_actions": []}
                user_summary[user]["actions"] += v

            # 模块失败率
            module_failure_rates = []
            for module, failures in sorted(self._module_failures.items(), key=lambda x: -x[1]):
                total_runs = sum(1 for p in self._pipeline_runs if module in (p.run_id or ""))
                rate = failures / max(total_runs, 1)
                if rate > 0:
                    module_failure_rates.append({
                        "module": module, "failures": failures,
                        "rate": round(rate, 3),
                    })

            uptime_seconds = time.time() - self._start_time

            return {
                "system": {
                    "uptime_hours": round(uptime_seconds / 3600, 1),
                    "total_pipelines": len(self._pipeline_runs),
                    "total_signoffs": len(self._signoff_cycles),
                    "total_api_calls": total_api_calls,
                },
                "pipeline": {
                    "avg_duration_s": round(pipeline_avg, 1),
                    "pass_rate_20": round(pipeline_pass_rate, 3),
                    "recent_runs": len(pipeline_recent),
                    "total_tracked": len(self._pipeline_runs),
                },
                "signoff": {
                    "avg_cycle_time_minutes": round(signoff_avg, 1),
                    "total_approved": signoff_approved,
                    "total_tracked": len(self._signoff_cycles),
                },
                "performance": {
                    "slow_apis": slow_apis[:5],
                    "total_endpoints": len(self._api_calls),
                },
                "errors": {
                    "total_types": len(error_summary),
                    "summary": error_summary[:10],
                },
                "users": {
                    "active_users": len(user_summary),
                    "top_users": sorted(
                        [{"username": k, "actions": v["actions"]} for k, v in user_summary.items()],
                        key=lambda x: -x["actions"]
                    )[:10],
                },
                "modules": {
                    "failure_rates": module_failure_rates[:10],
                },
                "generated_at": datetime.now().isoformat(),
            }

    def get_pipeline_timeline(self, limit: int = 30) -> List[dict]:
        """获取流水线时间线（用于趋势图）"""
        with self._lock:
            return [{
                "run_id": p.run_id[:16],
                "workflow": p.workflow,
                "state": p.state,
                "duration_s": p.duration_s,
                "passed": p.phases_passed,
                "total": p.phases_total,
                "coverage": p.coverage_line_pct,
                "started_at": p.started_at,
            } for p in self._pipeline_runs[-limit:]]

    def reset(self):
        """重置所有指标（用于测试）"""
        with self._lock:
            self._pipeline_runs.clear()
            self._signoff_cycles.clear()
            self._errors.clear()
            self._api_calls.clear()
            self._api_latencies.clear()
            self._user_actions.clear()
            self._module_failures.clear()
            self._start_time = time.time()


# ═══════════════════════════════════════════════════════════
# 慢查询检测器
# ═══════════════════════════════════════════════════════════

@dataclass
class SlowQuery:
    query: str
    duration_ms: float
    timestamp: str
    caller: str = ""
    params: str = ""


class SlowQueryDetector:
    """慢查询检测 — 超过阈值的查询自动记录和告警"""

    def __init__(self, threshold_ms: float = 100.0, max_records: int = 200):
        self.threshold_ms = threshold_ms
        self._slow_queries: List[SlowQuery] = []
        self._max_records = max_records

    def check_and_record(self, query: str, duration_ms: float, caller: str = "", params: str = ""):
        if duration_ms >= self.threshold_ms:
            sq = SlowQuery(query=query[:500], duration_ms=duration_ms,
                           timestamp=datetime.now().isoformat(), caller=caller, params=params[:200])
            self._slow_queries.append(sq)
            if len(self._slow_queries) > self._max_records:
                self._slow_queries = self._slow_queries[-self._max_records:]

            # 告警
            if duration_ms >= self.threshold_ms * 5:  # 5x 阈值
                print(f"[SlowQuery] ⚠️ CRITICAL: {duration_ms:.0f}ms — {query[:120]}")

    def get_slow_queries(self, limit: int = 30) -> List[dict]:
        return [{
            "query": sq.query[:150],
            "duration_ms": round(sq.duration_ms, 1),
            "timestamp": sq.timestamp,
            "caller": sq.caller,
        } for sq in self._slow_queries[-limit:]]

    def get_summary(self) -> dict:
        if not self._slow_queries:
            return {"total": 0, "avg_ms": 0, "max_ms": 0, "threshold_ms": self.threshold_ms}
        durations = [sq.duration_ms for sq in self._slow_queries]
        return {
            "total": len(self._slow_queries),
            "avg_ms": round(sum(durations) / len(durations), 1),
            "max_ms": round(max(durations), 1),
            "threshold_ms": self.threshold_ms,
            "over_5x": sum(1 for d in durations if d >= self.threshold_ms * 5),
        }


# ═══════════════════════════════════════════════════════════
# 健康检查器
# ═══════════════════════════════════════════════════════════

class HealthChecker:
    """系统健康检查 — 数据库连接、Agent 状态、磁盘空间"""

    @staticmethod
    async def check_all() -> dict:
        results = {}

        # 数据库连接检查
        try:
            from src.database.connection import get_session
            from sqlalchemy import text
            s = await get_session()
            await s.execute(text("SELECT 1"))
            await s.close()
            results["database"] = {"status": "healthy", "message": "连接正常"}
        except Exception as e:
            results["database"] = {"status": "unhealthy", "message": str(e)[:100]}

        # Agent 状态检查
        try:
            from src.core.execution import PipelineExecutionService
            service = PipelineExecutionService.get_instance()
            results["agents"] = {
                "status": "healthy" if service.initialized else "not_initialized",
                "initialized": service.initialized,
                "agent_count": len(service.registry.get_all_instances()) if service.initialized else 0,
            }
        except Exception as e:
            results["agents"] = {"status": "unhealthy", "message": str(e)[:100]}

        # 磁盘空间检查
        try:
            import shutil
            from pathlib import Path
            usage = shutil.disk_usage(Path.cwd())
            free_gb = usage.free / (1024 ** 3)
            results["disk"] = {
                "status": "healthy" if free_gb > 1 else "warning",
                "free_gb": round(free_gb, 1),
                "total_gb": round(usage.total / (1024 ** 3), 1),
            }
        except Exception as e:
            results["disk"] = {"status": "unknown", "message": str(e)[:100]}

        # 整体健康度
        statuses = [v.get("status", "unknown") for v in results.values()]
        overall = "healthy" if all(s == "healthy" for s in statuses) else (
            "degraded" if "unhealthy" in statuses else "warning"
        )

        return {
            "overall": overall,
            "components": results,
            "checked_at": datetime.now().isoformat(),
        }


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_metrics: Optional[MetricsCollector] = None
_slow_query_detector: Optional[SlowQueryDetector] = None


def get_metrics() -> MetricsCollector:
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics


def get_slow_query_detector() -> SlowQueryDetector:
    global _slow_query_detector
    if _slow_query_detector is None:
        _slow_query_detector = SlowQueryDetector()
    return _slow_query_detector
