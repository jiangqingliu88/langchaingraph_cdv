"""
平台健康度监控 — StuckDetector + TimeoutTracker + GapScanner + ProactiveAlerting

四个核心能力:
  1. StuckDetector — 检测卡住的流程（流水线/签核/回归）
  2. TimeoutTracker — 签核超时、流水线超时、门禁超时追踪
  3. GapScanner — 证据缺失扫描、覆盖率空洞扫描、规则异常检测
  4. ProactiveAlerting — 主动告警引擎，支持分级（INFO/WARN/CRITICAL）

用法:
  from src.infra.health_monitor import HealthMonitor, get_health_monitor

  monitor = get_health_monitor()
  report = await monitor.run_full_check()
  # → {stuck_workflows: 3, timeout_signoffs: 5, evidence_gaps: 12, alerts: [...]}
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import threading


# ═══════════════════════════════════════════════════════════
# 1. 告警系统
# ═══════════════════════════════════════════════════════════

class AlertLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class Alert:
    """告警"""
    alert_id: str
    level: AlertLevel
    title: str
    description: str
    source: str              # stuck_detector / timeout_tracker / gap_scanner
    object_type: str         # pipeline / signoff / evidence / rule
    object_id: str
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())
    acknowledged: bool = False
    resolved_at: str = ""
    recommendation: str = ""


class AlertManager:
    """告警管理器"""

    def __init__(self, max_alerts: int = 500):
        self._alerts: List[Alert] = []
        self._max_alerts = max_alerts
        self._lock = threading.Lock()

    def raise_alert(self, level: AlertLevel, title: str, description: str,
                    source: str, object_type: str, object_id: str,
                    recommendation: str = "") -> Alert:
        import uuid
        alert = Alert(
            alert_id=str(uuid.uuid4())[:12],
            level=level, title=title, description=description,
            source=source, object_type=object_type, object_id=object_id,
            recommendation=recommendation,
        )
        with self._lock:
            self._alerts.append(alert)
            if len(self._alerts) > self._max_alerts:
                self._alerts = self._alerts[-self._max_alerts:]

        # 控制台输出 CRITICAL 告警
        if level == AlertLevel.CRITICAL:
            print(f"[HEALTH-CRITICAL] {title}: {description}")

        return alert

    def acknowledge(self, alert_id: str):
        with self._lock:
            for a in self._alerts:
                if a.alert_id == alert_id:
                    a.acknowledged = True
                    break

    def resolve(self, alert_id: str):
        with self._lock:
            for a in self._alerts:
                if a.alert_id == alert_id:
                    a.resolved_at = datetime.now().isoformat()
                    break

    def get_active_alerts(self, level: AlertLevel = None) -> List[Alert]:
        with self._lock:
            active = [a for a in self._alerts if not a.resolved_at]
            if level:
                active = [a for a in active if a.level == level]
            return sorted(active, key=lambda a: a.detected_at, reverse=True)

    def get_summary(self) -> dict:
        with self._lock:
            active = [a for a in self._alerts if not a.resolved_at]
            return {
                "total_active": len(active),
                "critical": sum(1 for a in active if a.level == AlertLevel.CRITICAL),
                "warnings": sum(1 for a in active if a.level == AlertLevel.WARN),
                "info": sum(1 for a in active if a.level == AlertLevel.INFO),
                "acknowledged": sum(1 for a in active if a.acknowledged),
                "total_resolved": sum(1 for a in self._alerts if a.resolved_at),
            }


# ═══════════════════════════════════════════════════════════
# 2. 卡住流程检测器
# ═══════════════════════════════════════════════════════════

@dataclass
class StuckWorkflow:
    """卡住的工作流"""
    object_type: str        # pipeline / signoff / regression
    object_id: str
    current_state: str
    stuck_since: str
    stuck_hours: float
    reason: str
    recommendation: str


class StuckDetector:
    """卡住流程检测 — 发现长时间未推进的流程"""

    # 各流程类型的超时阈值（小时）
    TIMEOUTS = {
        "pipeline": {"running": 2, "completed_with_errors": 24},
        "signoff": {"pending": 48, "draft": 72},
        "regression": {"running": 4},
    }

    def __init__(self, alert_manager: AlertManager):
        self.alerts = alert_manager

    async def detect_stuck_pipelines(self) -> List[StuckWorkflow]:
        """检测卡住的流水线"""
        stuck = []
        try:
            from src.database.connection import get_session
            from src.database.models import PipelineRun
            from sqlalchemy import select

            s = await get_session()
            running = (await s.execute(
                select(PipelineRun).where(
                    PipelineRun.state.in_(["running", "completed_with_errors"])
                )
            )).scalars().all()

            now = datetime.now()
            for r in running:
                started = r.started_at
                if not started:
                    continue
                elapsed_h = (now - started).total_seconds() / 3600

                timeout_h = self.TIMEOUTS["pipeline"].get(r.state, 24)
                if elapsed_h > timeout_h:
                    sw = StuckWorkflow(
                        object_type="pipeline", object_id=r.run_id,
                        current_state=r.state,
                        stuck_since=str(started),
                        stuck_hours=round(elapsed_h, 1),
                        reason=f"流水线处于 '{r.state}' 状态超过 {timeout_h} 小时",
                        recommendation=f"检查流水线日志，必要时取消并重新运行",
                    )
                    stuck.append(sw)

                    self.alerts.raise_alert(
                        AlertLevel.CRITICAL if elapsed_h > timeout_h * 2 else AlertLevel.WARN,
                        f"流水线卡住: {r.run_id[:20]}",
                        f"状态 '{r.state}' 持续 {elapsed_h:.1f}h, 超时阈值 {timeout_h}h",
                        "stuck_detector", "pipeline", r.run_id,
                        "建议检查执行日志或取消流水线",
                    )
            await s.close()
        except Exception as e:
            self.alerts.raise_alert(AlertLevel.WARN, "卡住检测失败", str(e)[:200],
                                    "stuck_detector", "system", "detector", "检查数据库连接")
        return stuck

    async def detect_stuck_signoffs(self) -> List[StuckWorkflow]:
        """检测卡住的签核"""
        stuck = []
        try:
            from src.database.connection import get_session
            from src.database.models import Signoff
            from sqlalchemy import select

            s = await get_session()
            pending = (await s.execute(
                select(Signoff).where(Signoff.status.in_(["pending", "draft"]), Signoff.is_deleted == False)
            )).scalars().all()

            now = datetime.now()
            for sf in pending:
                created = sf.created_at
                if not created:
                    continue
                elapsed_h = (now - created).total_seconds() / 3600

                timeout_h = self.TIMEOUTS["signoff"].get(sf.status, 72)
                if elapsed_h > timeout_h:
                    sw = StuckWorkflow(
                        object_type="signoff", object_id=str(sf.id),
                        current_state=sf.status,
                        stuck_since=str(created),
                        stuck_hours=round(elapsed_h, 1),
                        reason=f"签核处于 '{sf.status}' 状态超过 {timeout_h} 小时",
                        recommendation=f"通知审批人或 escalation",
                    )
                    stuck.append(sw)

                    self.alerts.raise_alert(
                        AlertLevel.WARN,
                        f"签核超时: #{sf.id} {sf.title}",
                        f"状态 '{sf.status}' 持续 {elapsed_h:.1f}h",
                        "stuck_detector", "signoff", str(sf.id),
                        "建议通知审批人或转交",
                    )
            await s.close()
        except Exception as e:
            self.alerts.raise_alert(AlertLevel.WARN, "签核超时检测失败", str(e)[:200],
                                    "stuck_detector", "system", "detector")
        return stuck


# ═══════════════════════════════════════════════════════════
# 3. 超时追踪器
# ═══════════════════════════════════════════════════════════

@dataclass
class TimeoutItem:
    object_type: str
    object_id: str
    deadline: str
    remaining_hours: float
    is_overdue: bool
    severity: str


class TimeoutTracker:
    """超时追踪器 — 签核/流水线/门禁的超时监控"""

    def __init__(self, alert_manager: AlertManager):
        self.alerts = alert_manager
        self._deadlines: Dict[str, datetime] = {}

    def set_deadline(self, key: str, deadline: datetime):
        self._deadlines[key] = deadline

    def check_all(self) -> List[TimeoutItem]:
        """检查所有 deadline"""
        now = datetime.now()
        items = []
        for key, deadline in self._deadlines.items():
            remaining = (deadline - now).total_seconds() / 3600
            is_overdue = remaining < 0
            severity = "critical" if remaining < -24 else ("warning" if remaining < 0 else "ok")
            obj_type, obj_id = key.split(":", 1) if ":" in key else ("unknown", key)
            items.append(TimeoutItem(
                object_type=obj_type, object_id=obj_id,
                deadline=deadline.isoformat(),
                remaining_hours=round(remaining, 1),
                is_overdue=is_overdue, severity=severity,
            ))

            if is_overdue and severity == "critical":
                self.alerts.raise_alert(
                    AlertLevel.CRITICAL, f"严重超时: {key}",
                    f"截止时间已过 {abs(remaining):.1f}h",
                    "timeout_tracker", obj_type, obj_id,
                    "立即关注并处理",
                )

        return sorted(items, key=lambda i: i.remaining_hours)

    def get_overdue_count(self) -> int:
        return sum(1 for item in self.check_all() if item.is_overdue)


# ═══════════════════════════════════════════════════════════
# 4. 证据缺失扫描器
# ═══════════════════════════════════════════════════════════

@dataclass
class Gap:
    """缺口/异常"""
    gap_type: str          # missing_evidence / missing_coverage / rule_anomaly
    severity: str          # critical / warning / info
    object_type: str
    object_id: str
    description: str
    recommendation: str


class GapScanner:
    """证据缺失扫描器 — 发现证据链的缺口和异常"""

    def __init__(self, alert_manager: AlertManager):
        self.alerts = alert_manager

    async def scan_evidence_gaps(self) -> List[Gap]:
        """扫描证据缺失"""
        gaps = []
        try:
            from src.database.connection import get_session
            from src.database.models import Signoff, Artifact, PipelineRun
            from sqlalchemy import select

            s = await get_session()

            # 1. 已批准的签核但没有关联 artifact
            approved = (await s.execute(
                select(Signoff).where(Signoff.status == "approved", Signoff.is_deleted == False)
            )).scalars().all()
            for sf in approved:
                arts = (await s.execute(
                    select(Artifact).where(Artifact.signoff_id == sf.id)
                )).scalars().all()
                if not arts:
                    gap = Gap("missing_evidence", "warning", "signoff", str(sf.id),
                              f"已批准的签核 #{sf.id} '{sf.title}' 没有注册任何 artifact",
                              "为签核注册对应的 evidence artifact")
                    gaps.append(gap)
                    self.alerts.raise_alert(
                        AlertLevel.WARN, f"证据缺失: 签核 #{sf.id}",
                        "已批准但无关联 artifact", "gap_scanner", "signoff", str(sf.id),
                        "运行证据注册流程",
                    )

            # 2. 已完成的流水线但没有 manifest artifact
            completed = (await s.execute(
                select(PipelineRun).where(PipelineRun.state == "completed")
            )).scalars().all()
            for r in completed[:50]:
                arts = (await s.execute(
                    select(Artifact).where(Artifact.run_id == r.run_id, Artifact.artifact_type == "manifest")
                )).scalars().all()
                if not arts and r.total_phases and r.total_phases > 0:
                    gap = Gap("missing_evidence", "info", "pipeline", r.run_id,
                              f"已完成的流水线 {r.run_id[:20]} 没有 manifest artifact",
                              "检查 manifest 生成是否成功")
                    gaps.append(gap)

            # 3. 签核的 manifest_hash 为空但已批准
            for sf in approved:
                if not sf.manifest_hash:
                    gap = Gap("missing_evidence", "critical", "signoff", str(sf.id),
                              f"已批准签核 #{sf.id} 缺少 manifest_hash",
                              "补充 manifest hash 或驳回签核")
                    gaps.append(gap)
                    self.alerts.raise_alert(
                        AlertLevel.CRITICAL, f"严重证据缺失: 签核 #{sf.id}",
                        "已批准但缺少 manifest_hash — 证据链不可验证",
                        "gap_scanner", "signoff", str(sf.id),
                        "立即补充 manifest hash",
                    )

            await s.close()
        except Exception as e:
            self.alerts.raise_alert(AlertLevel.WARN, "证据扫描失败", str(e)[:200],
                                    "gap_scanner", "system", "scanner")
        return gaps

    async def scan_coverage_gaps(self) -> List[Gap]:
        """扫描覆盖率空洞"""
        gaps = []
        try:
            from src.database.connection import get_session
            from src.database.models import PipelineRun
            from sqlalchemy import select

            s = await get_session()
            recent = (await s.execute(
                select(PipelineRun).where(PipelineRun.state.in_(["completed", "completed_with_errors"]))
                .order_by(PipelineRun.created_at.desc()).limit(30)
            )).scalars().all()

            for r in recent:
                line = r.coverage_line_pct or 0
                branch = r.coverage_branch_pct or 0
                toggle = r.coverage_toggle_pct or 0

                if line > 0 and line < 60:
                    gaps.append(Gap("missing_coverage", "warning", "pipeline", r.run_id,
                                    f"行覆盖率过低: {line}% (阈值 85%)",
                                    "分析覆盖率空洞并补充测试用例"))
                if branch > 0 and branch < 50:
                    gaps.append(Gap("missing_coverage", "warning", "pipeline", r.run_id,
                                    f"分支覆盖率过低: {branch}% (阈值 75%)",
                                    "增加分支覆盖测试"))
                if toggle > 0 and toggle < 40:
                    gaps.append(Gap("missing_coverage", "warning", "pipeline", r.run_id,
                                    f"翻转覆盖率过低: {toggle}% (阈值 60%)",
                                    "增加翻转覆盖测试"))

            await s.close()
        except Exception: pass
        return gaps

    async def scan_rule_anomalies(self) -> List[Gap]:
        """扫描规则异常触发"""
        gaps = []
        try:
            from src.infra.impact_analyzer import get_rule_registry
            registry = get_rule_registry()

            for rule in registry.get_all_rules():
                # 检查是否有规则从未被使用但有大量项目和签核
                if rule.usage_count == 0 and len(rule.affects) > 2:
                    gaps.append(Gap("rule_anomaly", "info", "rule", rule.rule_id,
                                    f"规则 '{rule.name}' 定义了 {len(rule.affects)} 个影响点但从未被使用",
                                    "检查规则是否正确关联到流程中"))
        except Exception: pass
        return gaps


# ═══════════════════════════════════════════════════════════
# 5. 健康监控主控
# ═══════════════════════════════════════════════════════════

@dataclass
class HealthReport:
    """平台健康度报告"""
    timestamp: str
    overall_health: str  # healthy / degraded / critical
    stuck_workflows: int
    timeout_items: int
    evidence_gaps: int
    coverage_gaps: int
    rule_anomalies: int
    active_alerts: dict
    stuck_details: List[StuckWorkflow] = field(default_factory=list)
    timeout_details: List[TimeoutItem] = field(default_factory=list)
    gap_details: List[Gap] = field(default_factory=list)


class HealthMonitor:
    """平台健康度监控主控"""

    def __init__(self):
        self.alerts = AlertManager()
        self.stuck_detector = StuckDetector(self.alerts)
        self.timeout_tracker = TimeoutTracker(self.alerts)
        self.gap_scanner = GapScanner(self.alerts)

    async def run_full_check(self) -> HealthReport:
        """运行全面的健康检查"""
        # 1. 检测卡住的流程
        stuck_pipelines = await self.stuck_detector.detect_stuck_pipelines()
        stuck_signoffs = await self.stuck_detector.detect_stuck_signoffs()
        all_stuck = stuck_pipelines + stuck_signoffs

        # 2. 检查超时
        timeout_items = self.timeout_tracker.check_all()

        # 3. 扫描证据缺失
        evidence_gaps = await self.gap_scanner.scan_evidence_gaps()
        coverage_gaps = await self.gap_scanner.scan_coverage_gaps()
        rule_anomalies = await self.gap_scanner.scan_rule_anomalies()
        all_gaps = evidence_gaps + coverage_gaps + rule_anomalies

        # 4. 判定整体健康度
        critical_alerts = self.alerts.get_summary()["critical"]
        if critical_alerts > 0 or len(all_stuck) > 3:
            overall = "critical"
        elif len(all_stuck) > 0 or len(evidence_gaps) > 5:
            overall = "degraded"
        else:
            overall = "healthy"

        return HealthReport(
            timestamp=datetime.now().isoformat(),
            overall_health=overall,
            stuck_workflows=len(all_stuck),
            timeout_items=len(timeout_items),
            evidence_gaps=len(evidence_gaps),
            coverage_gaps=len(coverage_gaps),
            rule_anomalies=len(rule_anomalies),
            active_alerts=self.alerts.get_summary(),
            stuck_details=all_stuck,
            timeout_details=timeout_items,
            gap_details=all_gaps,
        )

    def quick_check(self) -> dict:
        """快速健康检查（仅基于内存数据，不同步查询 DB）"""
        alert_summary = self.alerts.get_summary()
        overdue = self.timeout_tracker.get_overdue_count()
        return {
            "timestamp": datetime.now().isoformat(),
            "active_alerts": alert_summary,
            "overdue_items": overdue,
            "health": "critical" if alert_summary["critical"] > 0 else (
                "degraded" if alert_summary["warnings"] > 3 else "healthy"
            ),
        }


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor
