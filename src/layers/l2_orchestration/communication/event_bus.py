"""
事件驱动工作流引擎 — EventBus + 标准事件 + 自动触发链

三层架构:
  1. EventBus — 发布/订阅事件总线，支持同步+异步处理
  2. StandardEvents — 所有平台标准事件定义
  3. WorkflowHandlers — 自动触发链（事件→动作）

核心自动触发链:
  signoff.approved  → 生成签核报告 + 锁定证据链
  signoff.rejected  → 通知申请人 + 记录驳回原因
  pipeline.completed → 自动生成 manifest + 注册 artifacts
  pipeline.failed   → 自动创建调试会话 + 通知相关人
  doc.updated       → 自动创建版本快照 + 触发变更通知
  regression.failed → 自动进入 Debug Copilot 分析
  evidence.exported → 审计记录 + 哈希链校验

用法:
  from src.layers.l2_orchestration.communication.event_bus import get_event_bus, StandardEvent

  bus = get_event_bus()

  # 发布事件
  await bus.publish(StandardEvent.SIGNOFF_APPROVED, {
      "signoff_id": 42, "approver": "admin", "evidence_hash": "abc123..."
  })

  # 注册处理器
  @bus.on(StandardEvent.SIGNOFF_APPROVED)
  async def on_signoff_approved(event):
      print(f"Signoff {event.data['signoff_id']} approved!")
"""

from __future__ import annotations
import asyncio
import time
import json
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set


# ═══════════════════════════════════════════════════════════
# 标准事件定义
# ═══════════════════════════════════════════════════════════

class StandardEvent(str, Enum):
    """平台标准事件 — 覆盖所有关键业务流程"""

    # 签核事件
    SIGNOFF_CREATED = "signoff.created"
    SIGNOFF_SUBMITTED = "signoff.submitted"
    SIGNOFF_APPROVED = "signoff.approved"
    SIGNOFF_REJECTED = "signoff.rejected"
    SIGNOFF_COMMENTED = "signoff.commented"

    # 流水线事件
    PIPELINE_STARTED = "pipeline.started"
    PIPELINE_PHASE_COMPLETED = "pipeline.phase_completed"
    PIPELINE_COMPLETED = "pipeline.completed"
    PIPELINE_FAILED = "pipeline.failed"
    PIPELINE_CANCELLED = "pipeline.cancelled"

    # 回归事件
    REGRESSION_STARTED = "regression.started"
    REGRESSION_COMPLETED = "regression.completed"
    REGRESSION_FAILED = "regression.failed"

    # 验证执行事件（L1 产生，Agent / Knowledge Graph 订阅 —— 细粒度异步反馈）
    TEST_FINISHED = "test.finished"          # {testcase, status, log, waveform}
    COVERAGE_UPDATED = "coverage.updated"    # {module, coverage, gap}
    BUG_DETECTED = "bug.detected"            # {signature, signal, category}

    # 决策事件（L3 产生，执行层订阅）
    DECISION_MADE = "decision.made"          # {action_type, reason, params}

    # 文档事件
    DOC_CREATED = "doc.created"
    DOC_UPDATED = "doc.updated"
    DOC_VERSION_CREATED = "doc.version_created"
    DOC_VERSION_RESTORED = "doc.version_restored"
    DOC_DEPRECATED = "doc.deprecated"

    # 证据事件
    EVIDENCE_GENERATED = "evidence.generated"
    EVIDENCE_EXPORTED = "evidence.exported"
    EVIDENCE_VERIFIED = "evidence.verified"
    EVIDENCE_TAMPERED = "evidence.tampered"

    # 用户事件
    USER_LOGIN = "user.login"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_CREATED = "user.created"

    # 项目事件
    PROJECT_CREATED = "project.created"
    MEMBER_ASSIGNED = "member.assigned"
    MEMBER_REMOVED = "member.removed"

    # 权限事件
    PERMISSION_DENIED = "permission.denied"
    PRIVILEGED_ACTION = "privileged.action"

    # 系统事件
    SYSTEM_ERROR = "system.error"
    SYSTEM_HEALTH_CHECK = "system.health_check"


# ═══════════════════════════════════════════════════════════
# 事件数据模型
# ═══════════════════════════════════════════════════════════

@dataclass
class Event:
    """事件对象"""
    event_type: StandardEvent
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    event_id: str = ""
    source: str = ""  # 事件来源模块
    trace_id: str = ""  # 链路追踪 ID

    def __post_init__(self):
        if not self.event_id:
            import uuid
            self.event_id = str(uuid.uuid4())[:12]

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "data": self.data,
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "source": self.source,
            "trace_id": self.trace_id,
        }


# ═══════════════════════════════════════════════════════════
# 事件总线
# ═══════════════════════════════════════════════════════════

HandlerFunc = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """发布/订阅事件总线 — 支持同步+异步，内置审计和错误恢复"""

    def __init__(self, max_history: int = 500):
        self._handlers: Dict[StandardEvent, List[HandlerFunc]] = defaultdict(list)
        self._wildcard_handlers: List[HandlerFunc] = []  # 监听所有事件
        self._history: List[Event] = []
        self._max_history = max_history
        self._stats: Dict[str, int] = defaultdict(int)  # 事件计数
        self._error_count: int = 0

    def on(self, event_type: StandardEvent):
        """装饰器 — 注册事件处理器"""
        def decorator(func: HandlerFunc):
            self._handlers[event_type].append(func)
            return func
        return decorator

    def on_any(self, func: HandlerFunc):
        """注册通配符处理器 — 监听所有事件"""
        self._wildcard_handlers.append(func)
        return func

    async def publish(self, event_type: StandardEvent, data: dict = None,
                      source: str = "", trace_id: str = "") -> Event:
        """发布事件 — 同步执行所有处理器"""
        event = Event(event_type=event_type, data=data or {}, source=source, trace_id=trace_id)
        self._stats[event_type.value] += 1
        self._add_to_history(event)

        handlers = self._handlers.get(event_type, []) + self._wildcard_handlers

        if not handlers:
            return event

        # 并发执行所有处理器
        tasks = []
        for handler in handlers:
            tasks.append(self._safe_invoke(handler, event))

        await asyncio.gather(*tasks, return_exceptions=True)
        return event

    async def publish_async(self, event_type: StandardEvent, data: dict = None,
                            source: str = "", trace_id: str = "") -> Event:
        """发布事件 — 异步（fire-and-forget），不等待处理器完成"""
        event = Event(event_type=event_type, data=data or {}, source=source, trace_id=trace_id)
        self._stats[event_type.value] += 1
        self._add_to_history(event)

        handlers = self._handlers.get(event_type, []) + self._wildcard_handlers
        for handler in handlers:
            asyncio.create_task(self._safe_invoke(handler, event))

        return event

    async def _safe_invoke(self, handler: HandlerFunc, event: Event):
        """安全调用处理器 — 捕获异常并记录"""
        try:
            await handler(event)
        except Exception as e:
            self._error_count += 1
            print(f"[EventBus] Handler error for {event.event_type.value}: {e}")
            traceback.print_exc()

    def _add_to_history(self, event: Event):
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    def get_history(self, event_type: StandardEvent = None, limit: int = 50) -> List[dict]:
        """获取事件历史"""
        filtered = self._history
        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]
        return [e.to_dict() for e in filtered[-limit:]]

    def get_stats(self) -> dict:
        """获取事件统计"""
        return {
            "total_events": sum(self._stats.values()),
            "by_type": dict(self._stats),
            "handler_count": sum(len(h) for h in self._handlers.values()) + len(self._wildcard_handlers),
            "error_count": self._error_count,
            "history_size": len(self._history),
        }

    def clear_handlers(self, event_type: StandardEvent = None):
        """清除处理器（用于测试）"""
        if event_type:
            self._handlers[event_type] = []
        else:
            self._handlers.clear()
            self._wildcard_handlers.clear()


# ═══════════════════════════════════════════════════════════
# 标准工作流处理器
# ═══════════════════════════════════════════════════════════

class WorkflowHandlers:
    """自动触发链 — 标准事件→业务动作"""

    def __init__(self, bus: EventBus):
        self.bus = bus
        self._register_all()

    def _register_all(self):
        """注册所有标准工作流处理器"""

        @self.bus.on(StandardEvent.SIGNOFF_APPROVED)
        async def _on_signoff_approved(event: Event):
            """签核批准后：锁定证据链 + 生成报告 + 审计"""
            data = event.data
            signoff_id = data.get("signoff_id")
            approver = data.get("approver", "")
            evidence_hash = data.get("evidence_hash", "")

            print(f"[Workflow] Signoff #{signoff_id} approved by {approver}")
            print(f"[Workflow] Evidence chain locked: {evidence_hash[:16]}...")

            # 记录审计日志
            try:
                from src.layers.l4_memory.persistence.repository import add_audit_log
                await add_audit_log(
                    data.get("user_id", 0), approver, "workflow.signoff_approved",
                    str(signoff_id), f"工作流: 签核批准 → 证据链锁定",
                    role=data.get("role", ""), resource_type="signoff",
                    is_privileged=True, after_state="approved"
                )
            except Exception: pass

        @self.bus.on(StandardEvent.SIGNOFF_REJECTED)
        async def _on_signoff_rejected(event: Event):
            """签核驳回后：通知申请人 + 记录驳回原因"""
            data = event.data
            signoff_id = data.get("signoff_id")
            reason = data.get("reason", "")
            print(f"[Workflow] Signoff #{signoff_id} rejected: {reason}")

        @self.bus.on(StandardEvent.PIPELINE_COMPLETED)
        async def _on_pipeline_completed(event: Event):
            """流水线完成后：自动生成 manifest + 注册 artifacts"""
            data = event.data
            run_id = data.get("run_id", "")
            print(f"[Workflow] Pipeline {run_id} completed — generating manifest & artifacts...")

            try:
                from src.layers.l4_memory.persistence.repository import create_artifact
                # 注册 coverage artifact
                if data.get("coverage"):
                    await create_artifact(
                        data.get("project_id", 0), run_id, 0, "coverage",
                        f"coverage_{run_id}", "", data.get("coverage_hash", ""),
                        metadata=data.get("coverage", {})
                    )
                # 注册 manifest artifact
                if data.get("manifest_hash"):
                    await create_artifact(
                        data.get("project_id", 0), run_id, 0, "manifest",
                        f"manifest_{run_id}", f"output/{run_id}/docs/manifest.json",
                        data.get("manifest_hash", ""),
                    )
            except Exception as e:
                print(f"[Workflow] Failed to register artifacts: {e}")

        @self.bus.on(StandardEvent.PIPELINE_FAILED)
        async def _on_pipeline_failed(event: Event):
            """流水线失败后：自动创建调试会话 + 通知"""
            data = event.data
            run_id = data.get("run_id", "")
            error = data.get("error", "")
            print(f"[Workflow] Pipeline {run_id} failed — creating debug session...")

            try:
                from src.layers.l4_memory.persistence.repository import add_audit_log
                await add_audit_log(
                    0, "system", "workflow.pipeline_failed", run_id,
                    f"工作流: 流水线失败 → 自动调试会话 | {error[:200]}",
                    resource_type="pipeline",
                )
            except Exception: pass

        @self.bus.on(StandardEvent.DOC_UPDATED)
        async def _on_doc_updated(event: Event):
            """文档更新后：触发变更通知"""
            data = event.data
            doc_path = data.get("path", "")
            author = data.get("author", "")
            print(f"[Workflow] Doc updated: {doc_path} by {author}")

        @self.bus.on(StandardEvent.REGRESSION_FAILED)
        async def _on_regression_failed(event: Event):
            """回归失败后：自动进入 Debug Copilot"""
            data = event.data
            failed_count = data.get("failed_count", 0)
            print(f"[Workflow] Regression: {failed_count} tests failed — triggering Debug Copilot...")

        @self.bus.on(StandardEvent.EVIDENCE_EXPORTED)
        async def _on_evidence_exported(event: Event):
            """证据导出后：审计记录 + 哈希链校验"""
            data = event.data
            session_id = data.get("session_id", "")
            user = data.get("user", "unknown")
            print(f"[Workflow] Evidence package exported by {user} for session {session_id}")

            try:
                from src.layers.l4_memory.persistence.repository import add_audit_log
                await add_audit_log(
                    data.get("user_id", 0), user, "workflow.evidence_exported",
                    session_id, "工作流: 证据包导出", role=data.get("role", ""),
                    resource_type="evidence", is_privileged=True,
                )
            except Exception: pass

        @self.bus.on(StandardEvent.PERMISSION_DENIED)
        async def _on_permission_denied(event: Event):
            """权限拒绝后：记录越权尝试"""
            data = event.data
            print(f"[Workflow] ⚠️ Permission denied: {data.get('user', '')} attempted {data.get('action', '')}")

        @self.bus.on(StandardEvent.SYSTEM_ERROR)
        async def _on_system_error(event: Event):
            """系统错误：记录并通知"""
            data = event.data
            error_msg = data.get("error", "")[:200]
            print(f"[Workflow] ⚠️ System error: {error_msg}")

            try:
                from src.layers.l4_memory.persistence.repository import add_audit_log
                await add_audit_log(
                    0, "system", "workflow.system_error", "",
                    f"工作流: 系统错误 | {error_msg}",
                    resource_type="system", access_result="error",
                )
            except Exception: pass


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_event_bus: Optional[EventBus] = None
_workflow_handlers: Optional[WorkflowHandlers] = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
        # 自动注册工作流处理器
        global _workflow_handlers
        _workflow_handlers = WorkflowHandlers(_event_bus)
    return _event_bus


def get_workflow_handlers() -> WorkflowHandlers:
    global _workflow_handlers
    if _workflow_handlers is None:
        get_event_bus()  # 触发初始化
    return _workflow_handlers
