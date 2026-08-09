"""
人工介入与协作系统 — Review Gates + Comments + @Mentions + Task Handoff

四个核心能力:
  1. ReviewGate — 流程中的人工确认节点，可配置触发条件和超时
  2. CommentSystem — 评论/@人/审批意见/讨论线程
  3. TaskAssignment — 任务分配、流程转交
  4. HandoffManager — 审批转交链，确保责任不丢失

设计原则:
  - 每个 ReviewGate 都是显式的，不可跳过
  - 所有评论和审批意见都记录到审计链
  - 转交保留完整历史（谁→谁→谁）
  - @mentions 触发通知

用法:
  from src.infra.collaboration import ReviewGateManager, CommentSystem

  gates = ReviewGateManager()
  gates.add_gate("signoff_final", requires=["verification_manager"], auto_timeout_hours=48)

  comments = CommentSystem()
  comments.add_comment("signoff", 42, "admin", "覆盖率不足,需补充 corner case 测试")
  comments.at_mention("signoff", 42, "engineer1", "请补充 coverage")
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import re


# ═══════════════════════════════════════════════════════════
# 1. 审核门禁 (Review Gates)
# ═══════════════════════════════════════════════════════════

class GateStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    WAIVED = "waived"  # 豁免


class GatePriority(str, Enum):
    CRITICAL = "critical"  # 不可跳过, 不可豁免
    HIGH = "high"          # 不可跳过, 可经理豁免
    MEDIUM = "medium"      # 可跳过 (需记录理由)
    LOW = "low"            # 建议性


@dataclass
class ReviewGate:
    """审核门禁节点"""
    gate_id: str
    name: str
    description: str
    priority: GatePriority = GatePriority.HIGH
    required_roles: List[str] = field(default_factory=list)    # 需要哪些角色审批
    required_users: List[str] = field(default_factory=list)    # 需要哪些具体用户
    min_approvals: int = 1                                      # 最少审批人数
    auto_timeout_hours: int = 48                                # 超时自动 escalation
    depends_on: List[str] = field(default_factory=list)         # 前置 gate
    status: GateStatus = GateStatus.PENDING
    approved_by: List[str] = field(default_factory=list)
    approved_at: str = ""
    comments: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=datetime.now().isoformat)


@dataclass
class GateResult:
    passed: bool
    gate_id: str
    reason: str
    missing_approvals: int = 0
    escalation_required: bool = False


class ReviewGateManager:
    """审核门禁管理器 — 流程中的人工确认节点"""

    def __init__(self):
        self._gates: Dict[str, List[ReviewGate]] = {}  # object_key → gates

    def add_gate(self, object_key: str, gate: ReviewGate):
        """为一个业务对象添加审核门禁"""
        if object_key not in self._gates:
            self._gates[object_key] = []
        self._gates[object_key].append(gate)

    def get_gates(self, object_key: str) -> List[ReviewGate]:
        return self._gates.get(object_key, [])

    def approve_gate(self, object_key: str, gate_id: str, user: str, role: str,
                     comment: str = "") -> GateResult:
        """审批通过一个门禁"""
        gates = self._gates.get(object_key, [])
        for gate in gates:
            if gate.gate_id == gate_id:
                if gate.status == GateStatus.APPROVED:
                    return GateResult(True, gate_id, "已审批")

                # 检查权限
                if gate.required_roles and role not in gate.required_roles:
                    if role not in ("admin", "verification_manager"):
                        return GateResult(False, gate_id, f"需要角色: {gate.required_roles}")

                gate.approved_by.append(user)
                if comment:
                    gate.comments.append(f"{user}({role}): {comment}")

                if len(gate.approved_by) >= gate.min_approvals:
                    gate.status = GateStatus.APPROVED
                    gate.approved_at = datetime.now().isoformat()
                    return GateResult(True, gate_id, f"已通过 ({len(gate.approved_by)}/{gate.min_approvals} 审批)")

                return GateResult(False, gate_id,
                                  f"还需 {gate.min_approvals - len(gate.approved_by)} 人审批",
                                  missing_approvals=gate.min_approvals - len(gate.approved_by))

        return GateResult(False, gate_id, f"门禁不存在: {gate_id}")

    def reject_gate(self, object_key: str, gate_id: str, user: str, reason: str) -> GateResult:
        """驳回门禁"""
        gates = self._gates.get(object_key, [])
        for gate in gates:
            if gate.gate_id == gate_id:
                gate.status = GateStatus.REJECTED
                gate.comments.append(f"{user}: 驳回 — {reason}")
                return GateResult(False, gate_id, reason)
        return GateResult(False, gate_id, f"门禁不存在: {gate_id}")

    def check_all_gates(self, object_key: str) -> Tuple[bool, List[GateResult]]:
        """检查对象的所有门禁是否通过"""
        gates = self._gates.get(object_key, [])
        results = []
        all_passed = True

        for gate in gates:
            # 检查超时
            if gate.status == GateStatus.PENDING and gate.auto_timeout_hours > 0:
                created = datetime.fromisoformat(gate.created_at)
                if datetime.now() - created > timedelta(hours=gate.auto_timeout_hours):
                    gate.status = GateStatus.TIMEOUT
                    results.append(GateResult(False, gate.gate_id, f"超时 ({gate.auto_timeout_hours}h)",
                                              escalation_required=True))
                    all_passed = False
                    continue

            if gate.status == GateStatus.APPROVED:
                results.append(GateResult(True, gate.gate_id, "已通过"))
            elif gate.status == GateStatus.WAIVED:
                results.append(GateResult(True, gate.gate_id, "已豁免"))
            elif gate.priority == GatePriority.LOW:
                results.append(GateResult(True, gate.gate_id, "低优先级,已跳过"))
            else:
                results.append(GateResult(False, gate.gate_id, f"状态: {gate.status.value}",
                                          escalation_required=gate.status == GateStatus.TIMEOUT))
                all_passed = False

        return all_passed, results

    def waive_gate(self, object_key: str, gate_id: str, user: str, reason: str) -> GateResult:
        """豁免门禁 (仅经理/管理员)"""
        gates = self._gates.get(object_key, [])
        for gate in gates:
            if gate.gate_id == gate_id:
                if gate.priority == GatePriority.CRITICAL:
                    return GateResult(False, gate_id, "CRITICAL 门禁不可豁免")
                gate.status = GateStatus.WAIVED
                gate.comments.append(f"{user}: 豁免 — {reason}")
                return GateResult(True, gate_id, "已豁免")
        return GateResult(False, gate_id, f"门禁不存在: {gate_id}")

    def get_pending_gates(self, object_key: str) -> List[ReviewGate]:
        return [g for g in self._gates.get(object_key, []) if g.status == GateStatus.PENDING]

    def get_blocked_objects(self) -> List[str]:
        """获取所有被门禁卡住的对象"""
        blocked = []
        for key, gates in self._gates.items():
            passed, _ = self.check_all_gates(key)
            if not passed:
                blocked.append(key)
        return blocked


# ═══════════════════════════════════════════════════════════
# 2. 评论系统
# ═══════════════════════════════════════════════════════════

@dataclass
class Comment:
    """评论"""
    comment_id: str
    object_type: str      # signoff / pipeline / doc / gate
    object_id: int
    author: str
    author_role: str
    content: str
    parent_id: str = ""   # 回复的评论 ID
    mentions: List[str] = field(default_factory=list)  # @的用户
    is_approval_note: bool = False  # 是否为审批意见
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class CommentSystem:
    """评论系统 — 支持 @mentions 和审批意见"""

    def __init__(self):
        self._comments: Dict[str, List[Comment]] = {}  # object_key → comments
        self._notifications: List[dict] = []

    def _object_key(self, object_type: str, object_id: int) -> str:
        return f"{object_type}:{object_id}"

    def add_comment(self, object_type: str, object_id: int, author: str,
                    content: str, author_role: str = "engineer",
                    parent_id: str = "", is_approval_note: bool = False) -> Comment:
        """添加评论，自动解析 @mentions"""
        import uuid
        key = self._object_key(object_type, object_id)
        if key not in self._comments:
            self._comments[key] = []

        # 解析 @mentions
        mentions = re.findall(r'@(\w[\w.]*)', content)

        comment = Comment(
            comment_id=str(uuid.uuid4())[:12],
            object_type=object_type, object_id=object_id,
            author=author, author_role=author_role,
            content=content, parent_id=parent_id,
            mentions=mentions, is_approval_note=is_approval_note,
        )
        self._comments[key].append(comment)

        # 生成通知
        for mentioned in mentions:
            self._notifications.append({
                "type": "mention", "to_user": mentioned,
                "from_user": author,
                "object_type": object_type, "object_id": object_id,
                "content": content[:100],
                "created_at": datetime.now().isoformat(),
                "read": False,
            })

        return comment

    def get_comments(self, object_type: str, object_id: int) -> List[Comment]:
        key = self._object_key(object_type, object_id)
        return self._comments.get(key, [])

    def get_thread(self, object_type: str, object_id: int) -> List[dict]:
        """获取评论线程（树形结构）"""
        comments = self.get_comments(object_type, object_id)
        # 按 parent_id 分组
        roots = [c for c in comments if not c.parent_id]
        result = []
        for root in roots:
            thread = {
                "comment": self._comment_to_dict(root),
                "replies": [self._comment_to_dict(c) for c in comments if c.parent_id == root.comment_id],
            }
            result.append(thread)
        return result

    def _comment_to_dict(self, c: Comment) -> dict:
        return {
            "comment_id": c.comment_id, "author": c.author,
            "author_role": c.author_role, "content": c.content,
            "mentions": c.mentions, "is_approval_note": c.is_approval_note,
            "created_at": c.created_at,
        }

    def get_notifications(self, username: str, unread_only: bool = False) -> List[dict]:
        """获取用户的通知"""
        notifs = [n for n in self._notifications if n["to_user"] == username]
        if unread_only:
            notifs = [n for n in notifs if not n["read"]]
        return notifs

    def mark_read(self, username: str, notification_indices: List[int] = None):
        """标记通知为已读"""
        user_notifs = [n for n in self._notifications if n["to_user"] == username]
        if notification_indices:
            for idx in notification_indices:
                if 0 <= idx < len(user_notifs):
                    user_notifs[idx]["read"] = True
        else:
            for n in user_notifs:
                n["read"] = True

    def get_unread_count(self, username: str) -> int:
        return len(self.get_notifications(username, unread_only=True))


# ═══════════════════════════════════════════════════════════
# 3. 任务分配与转交
# ═══════════════════════════════════════════════════════════

class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass
class TaskAssignment:
    """任务分配"""
    task_id: str
    title: str
    description: str
    object_type: str       # signoff / pipeline / doc / module
    object_id: int
    assigned_to: str       # 当前负责人
    assigned_by: str       # 分配人
    status: TaskStatus = TaskStatus.TODO
    priority: str = "medium"
    due_date: str = ""
    handoff_history: List[dict] = field(default_factory=list)  # 转交历史
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class TaskManager:
    """任务分配与转交管理"""

    def __init__(self):
        self._tasks: Dict[str, TaskAssignment] = {}

    def assign_task(self, title: str, description: str, object_type: str,
                    object_id: int, assigned_to: str, assigned_by: str,
                    priority: str = "medium", due_date: str = "") -> TaskAssignment:
        """分配任务"""
        import uuid
        task = TaskAssignment(
            task_id=str(uuid.uuid4())[:12],
            title=title, description=description,
            object_type=object_type, object_id=object_id,
            assigned_to=assigned_to, assigned_by=assigned_by,
            priority=priority, due_date=due_date,
        )
        self._tasks[task.task_id] = task
        return task

    def handoff_task(self, task_id: str, from_user: str, to_user: str, reason: str = "") -> bool:
        """转交任务 — 保留完整转交历史"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.handoff_history.append({
            "from": from_user, "to": to_user,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        })
        task.assigned_to = to_user
        task.status = TaskStatus.TODO  # 转交后重置状态
        return True

    def update_status(self, task_id: str, status: TaskStatus, user: str = "") -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.status = status
        return True

    def get_user_tasks(self, username: str, status: TaskStatus = None) -> List[TaskAssignment]:
        tasks = [t for t in self._tasks.values() if t.assigned_to == username]
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def get_overdue_tasks(self) -> List[TaskAssignment]:
        """获取逾期任务"""
        overdue = []
        for task in self._tasks.values():
            if task.due_date and task.status not in (TaskStatus.DONE,):
                try:
                    due = datetime.fromisoformat(task.due_date)
                    if datetime.now() > due:
                        overdue.append(task)
                except: pass
        return overdue

    def get_handoff_chain(self, task_id: str) -> List[dict]:
        task = self._tasks.get(task_id)
        return task.handoff_history if task else []


# ═══════════════════════════════════════════════════════════
# 4. 预定义签核流程门禁
# ═══════════════════════════════════════════════════════════

def create_signoff_review_gates(gate_manager: ReviewGateManager, signoff_id: int):
    """为签核创建标准审核门禁链"""
    signoff_key = f"signoff:{signoff_id}"

    gates = [
        ReviewGate(
            gate_id=f"gate_evidence_{signoff_id}",
            name="证据完整性审核",
            description="确认证据链完整、manifest hash 一致、artifact 文件完整",
            priority=GatePriority.CRITICAL,
            required_roles=["verification_manager"],
            min_approvals=1,
        ),
        ReviewGate(
            gate_id=f"gate_coverage_{signoff_id}",
            name="覆盖率达标审核",
            description="确认行覆盖率 >= 85%, 分支 >= 75%, 翻转 >= 60%",
            priority=GatePriority.HIGH,
            required_roles=["verification_manager"],
            min_approvals=1,
        ),
        ReviewGate(
            gate_id=f"gate_regression_{signoff_id}",
            name="回归通过率审核",
            description="确认回归通过率 >= 90%, 无 critical 失败",
            priority=GatePriority.HIGH,
            required_roles=["verification_manager", "senior_engineer"],
            min_approvals=1,
        ),
        ReviewGate(
            gate_id=f"gate_final_{signoff_id}",
            name="最终签核审批",
            description="SignOff 经理最终批准签核",
            priority=GatePriority.CRITICAL,
            required_roles=["verification_manager"],
            min_approvals=1,
            depends_on=[f"gate_evidence_{signoff_id}", f"gate_coverage_{signoff_id}", f"gate_regression_{signoff_id}"],
        ),
    ]

    for gate in gates:
        gate_manager.add_gate(signoff_key, gate)

    return gates


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_gate_manager: Optional[ReviewGateManager] = None
_comment_system: Optional[CommentSystem] = None
_task_manager: Optional[TaskManager] = None


def get_gate_manager() -> ReviewGateManager:
    global _gate_manager
    if _gate_manager is None:
        _gate_manager = ReviewGateManager()
    return _gate_manager


def get_comment_system() -> CommentSystem:
    global _comment_system
    if _comment_system is None:
        _comment_system = CommentSystem()
    return _comment_system


def get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
