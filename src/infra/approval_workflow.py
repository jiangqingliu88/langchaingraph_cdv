"""
审批协作模型 — ApprovalChain + AskBack + ReturnForRevision + ReSubmit

统一"审批/评论/追问/退回/重新提交"模型，让协作信息结构化、可追溯。

状态机:
  draft → submitted → under_review → approved
                    ↓              ↓
                  ask_back ← 退回修改(return_for_revision)
                    ↓              ↓
                  responded → 重新提交(resubmit) → under_review
                    ↓
                  rejected (终态)

每条状态变更都记录:
  - 谁做的操作
  - 操作类型 (submit/approve/reject/ask_back/revise/resubmit)
  - 评论/理由
  - 引用的证据
  - 时间戳

用法:
  from src.infra.approval_workflow import ApprovalWorkflow, ReviewAction

  wf = ApprovalWorkflow()
  wf.submit("signoff", 42, "engineer1")
  wf.ask_back("signoff", 42, "manager1", "Coverage data is incomplete, please add UART corner cases")
  wf.resubmit("signoff", 42, "engineer1", "Added UART corner case coverage, now 92%")
  wf.approve("signoff", 42, "manager1")
  history = wf.get_history("signoff", 42)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import json


# ═══════════════════════════════════════════════════════════
# 统一审批模型
# ═══════════════════════════════════════════════════════════

class ReviewAction(str, Enum):
    """审批动作类型"""
    SUBMIT = "submit"                    # 提交审批
    APPROVE = "approve"                  # 批准
    REJECT = "reject"                    # 驳回（终态）
    ASK_BACK = "ask_back"               # 追问（需要申请人回复）
    RETURN_FOR_REVISION = "return_for_revision"  # 退回修改
    REVISE = "revise"                    # 修改后重新提交
    RESUBMIT = "resubmit"               # 重新提交审批
    COMMENT = "comment"                  # 一般评论
    WITHDRAW = "withdraw"               # 撤回申请
    DELEGATE = "delegate"               # 转交审批
    ESCALATE = "escalate"               # 升级


class ReviewStatus(str, Enum):
    """审批状态"""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    ASKED_BACK = "asked_back"           # 已追问，等待回复
    RETURNED = "returned"               # 已退回，等待修改
    REVISING = "revising"               # 修改中
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    DELEGATED = "delegated"
    ESCALATED = "escalated"


# 状态转移规则
STATUS_TRANSITIONS = {
    ReviewStatus.DRAFT: [ReviewStatus.SUBMITTED],
    ReviewStatus.SUBMITTED: [ReviewStatus.UNDER_REVIEW, ReviewStatus.WITHDRAWN],
    ReviewStatus.UNDER_REVIEW: [
        ReviewStatus.APPROVED, ReviewStatus.REJECTED,
        ReviewStatus.ASKED_BACK, ReviewStatus.RETURNED,
    ],
    ReviewStatus.ASKED_BACK: [ReviewStatus.UNDER_REVIEW],  # 回复后回到审查
    ReviewStatus.RETURNED: [ReviewStatus.REVISING],
    ReviewStatus.REVISING: [ReviewStatus.SUBMITTED],       # 修改完重新提交
    ReviewStatus.APPROVED: [],   # 终态
    ReviewStatus.REJECTED: [],   # 终态
    ReviewStatus.WITHDRAWN: [],  # 终态
}


@dataclass
class ReviewEntry:
    """审批记录条目 — 统一评论/审批/追问/退回归档"""
    entry_id: str
    object_type: str          # signoff / pipeline / doc / rule_change
    object_id: int
    action: ReviewAction
    actor: str                # 操作人
    actor_role: str           # 操作时角色
    comment: str              # 评论/理由/追问内容
    status_before: str        # 变更前状态
    status_after: str         # 变更后状态
    reply_to_entry_id: str = ""     # 回复哪条（追问/退回的回应）
    evidence_refs: List[str] = field(default_factory=list)  # 引用的证据ID
    attachments: List[str] = field(default_factory=list)     # 附件
    round_number: int = 1           # 第几轮审批
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class ApprovalWorkflow:
    """审批工作流引擎 — 统一协作模型"""

    def __init__(self):
        self._states: Dict[str, ReviewStatus] = {}         # object_key → current status
        self._histories: Dict[str, List[ReviewEntry]] = {} # object_key → entries
        self._rounds: Dict[str, int] = {}                  # object_key → current round

    def _key(self, object_type: str, object_id: int) -> str:
        return f"{object_type}:{object_id}"

    def _ensure(self, object_type: str, object_id: int):
        key = self._key(object_type, object_id)
        if key not in self._states:
            self._states[key] = ReviewStatus.DRAFT
            self._histories[key] = []
            self._rounds[key] = 1

    def _add_entry(self, object_type: str, object_id: int, action: ReviewAction,
                   actor: str, actor_role: str, comment: str,
                   old_status: ReviewStatus, new_status: ReviewStatus,
                   reply_to: str = "", evidence_refs: List[str] = None) -> ReviewEntry:
        import uuid
        key = self._key(object_type, object_id)
        entry = ReviewEntry(
            entry_id=str(uuid.uuid4())[:12],
            object_type=object_type, object_id=object_id,
            action=action, actor=actor, actor_role=actor_role,
            comment=comment, status_before=old_status.value, status_after=new_status.value,
            reply_to_entry_id=reply_to, evidence_refs=evidence_refs or [],
            round_number=self._rounds[key],
        )
        self._states[key] = new_status
        self._histories[key].append(entry)
        return entry

    def _check_transition(self, current: ReviewStatus, target: ReviewStatus) -> bool:
        return target in STATUS_TRANSITIONS.get(current, [])

    # ── 工作流操作 ──

    def submit(self, object_type: str, object_id: int, actor: str,
               actor_role: str = "engineer", comment: str = "") -> ReviewEntry:
        """提交审批"""
        self._ensure(object_type, object_id)
        key = self._key(object_type, object_id)
        current = self._states[key]
        if not self._check_transition(current, ReviewStatus.SUBMITTED):
            raise ValueError(f"Cannot submit from '{current.value}'")
        return self._add_entry(object_type, object_id, ReviewAction.SUBMIT,
                                actor, actor_role, comment, current, ReviewStatus.SUBMITTED)

    def start_review(self, object_type: str, object_id: int, actor: str,
                     actor_role: str = "verification_manager", comment: str = "") -> ReviewEntry:
        """开始审查"""
        self._ensure(object_type, object_id)
        key = self._key(object_type, object_id)
        current = self._states[key]
        if not self._check_transition(current, ReviewStatus.UNDER_REVIEW):
            raise ValueError(f"Cannot start review from '{current.value}'")
        return self._add_entry(object_type, object_id, ReviewAction.COMMENT,
                                actor, actor_role, comment, current, ReviewStatus.UNDER_REVIEW)

    def approve(self, object_type: str, object_id: int, actor: str,
                actor_role: str = "verification_manager", comment: str = "") -> ReviewEntry:
        """批准"""
        self._ensure(object_type, object_id)
        key = self._key(object_type, object_id)
        current = self._states[key]
        if not self._check_transition(current, ReviewStatus.APPROVED):
            raise ValueError(f"Cannot approve from '{current.value}'")
        return self._add_entry(object_type, object_id, ReviewAction.APPROVE,
                                actor, actor_role, comment, current, ReviewStatus.APPROVED)

    def reject(self, object_type: str, object_id: int, actor: str,
               actor_role: str = "verification_manager", reason: str = "") -> ReviewEntry:
        """驳回（终态）"""
        self._ensure(object_type, object_id)
        key = self._key(object_type, object_id)
        current = self._states[key]
        if not self._check_transition(current, ReviewStatus.REJECTED):
            raise ValueError(f"Cannot reject from '{current.value}'")
        return self._add_entry(object_type, object_id, ReviewAction.REJECT,
                                actor, actor_role, reason, current, ReviewStatus.REJECTED)

    def ask_back(self, object_type: str, object_id: int, actor: str,
                 actor_role: str = "verification_manager", question: str = "",
                 evidence_refs: List[str] = None) -> ReviewEntry:
        """追问 — 需要申请人回答，状态变为 asked_back"""
        self._ensure(object_type, object_id)
        key = self._key(object_type, object_id)
        current = self._states[key]
        if not self._check_transition(current, ReviewStatus.ASKED_BACK):
            raise ValueError(f"Cannot ask back from '{current.value}'")
        return self._add_entry(object_type, object_id, ReviewAction.ASK_BACK,
                                actor, actor_role, question, current, ReviewStatus.ASKED_BACK,
                                evidence_refs=evidence_refs)

    def respond_to_ask(self, object_type: str, object_id: int, actor: str,
                       actor_role: str = "engineer", response: str = "",
                       reply_to_entry_id: str = "") -> ReviewEntry:
        """回复追问 — 回答审批人的问题"""
        self._ensure(object_type, object_id)
        key = self._key(object_type, object_id)
        current = self._states[key]
        if current != ReviewStatus.ASKED_BACK:
            raise ValueError(f"Cannot respond from '{current.value}', expected 'asked_back'")
        return self._add_entry(object_type, object_id, ReviewAction.COMMENT,
                                actor, actor_role, response, current, ReviewStatus.UNDER_REVIEW,
                                reply_to=reply_to_entry_id)

    def return_for_revision(self, object_type: str, object_id: int, actor: str,
                            actor_role: str = "verification_manager", revision_notes: str = "",
                            evidence_refs: List[str] = None) -> ReviewEntry:
        """退回修改 — 需要补充/修改后重新提交"""
        self._ensure(object_type, object_id)
        key = self._key(object_type, object_id)
        current = self._states[key]
        if not self._check_transition(current, ReviewStatus.RETURNED):
            raise ValueError(f"Cannot return from '{current.value}'")
        return self._add_entry(object_type, object_id, ReviewAction.RETURN_FOR_REVISION,
                                actor, actor_role, revision_notes, current, ReviewStatus.RETURNED,
                                evidence_refs=evidence_refs)

    def start_revision(self, object_type: str, object_id: int, actor: str,
                       actor_role: str = "engineer", comment: str = "") -> ReviewEntry:
        """开始修改"""
        self._ensure(object_type, object_id)
        key = self._key(object_type, object_id)
        current = self._states[key]
        if current != ReviewStatus.RETURNED:
            raise ValueError(f"Cannot revise from '{current.value}', expected 'returned'")
        self._rounds[key] += 1  # 新一轮
        return self._add_entry(object_type, object_id, ReviewAction.REVISE,
                                actor, actor_role, comment, current, ReviewStatus.REVISING)

    def resubmit(self, object_type: str, object_id: int, actor: str,
                 actor_role: str = "engineer", comment: str = "") -> ReviewEntry:
        """修改后重新提交"""
        self._ensure(object_type, object_id)
        key = self._key(object_type, object_id)
        current = self._states[key]
        if not self._check_transition(current, ReviewStatus.SUBMITTED):
            raise ValueError(f"Cannot resubmit from '{current.value}'")
        return self._add_entry(object_type, object_id, ReviewAction.RESUBMIT,
                                actor, actor_role, comment, current, ReviewStatus.SUBMITTED)

    def withdraw(self, object_type: str, object_id: int, actor: str,
                 actor_role: str = "engineer", reason: str = "") -> ReviewEntry:
        """撤回申请"""
        self._ensure(object_type, object_id)
        key = self._key(object_type, object_id)
        current = self._states[key]
        if not self._check_transition(current, ReviewStatus.WITHDRAWN):
            raise ValueError(f"Cannot withdraw from '{current.value}'")
        return self._add_entry(object_type, object_id, ReviewAction.WITHDRAW,
                                actor, actor_role, reason, current, ReviewStatus.WITHDRAWN)

    def comment(self, object_type: str, object_id: int, actor: str,
                actor_role: str, content: str) -> ReviewEntry:
        """添加评论（不改变状态）"""
        self._ensure(object_type, object_id)
        key = self._key(object_type, object_id)
        current = self._states[key]
        return self._add_entry(object_type, object_id, ReviewAction.COMMENT,
                                actor, actor_role, content, current, current)

    # ── 查询 ──

    def get_status(self, object_type: str, object_id: int) -> ReviewStatus:
        key = self._key(object_type, object_id)
        return self._states.get(key, ReviewStatus.DRAFT)

    def get_history(self, object_type: str, object_id: int) -> List[ReviewEntry]:
        key = self._key(object_type, object_id)
        return self._histories.get(key, [])

    def get_round(self, object_type: str, object_id: int) -> int:
        key = self._key(object_type, object_id)
        return self._rounds.get(key, 1)

    def get_ask_backs(self, object_type: str, object_id: int) -> List[ReviewEntry]:
        """获取所有追问记录"""
        return [e for e in self.get_history(object_type, object_id)
                if e.action == ReviewAction.ASK_BACK]

    def get_returns(self, object_type: str, object_id: int) -> List[ReviewEntry]:
        """获取所有退回记录"""
        return [e for e in self.get_history(object_type, object_id)
                if e.action == ReviewAction.RETURN_FOR_REVISION]

    def get_threaded_history(self, object_type: str, object_id: int) -> List[dict]:
        """获取线程化的审批历史（ask_back → response 配对）"""
        entries = self.get_history(object_type, object_id)
        threaded = []
        for e in entries:
            item = {
                "entry_id": e.entry_id, "action": e.action.value,
                "actor": e.actor, "role": e.actor_role,
                "comment": e.comment, "round": e.round_number,
                "status": f"{e.status_before} → {e.status_after}",
                "created_at": e.created_at,
                "evidence_refs": e.evidence_refs,
            }
            if e.reply_to_entry_id:
                item["in_reply_to"] = e.reply_to_entry_id
            threaded.append(item)
        return threaded

    def get_summary(self, object_type: str, object_id: int) -> dict:
        """获取审批摘要"""
        history = self.get_history(object_type, object_id)
        if not history:
            return {"status": "draft", "rounds": 0, "total_actions": 0}

        ask_backs = len(self.get_ask_backs(object_type, object_id))
        returns = len(self.get_returns(object_type, object_id))
        approvers = list(set(e.actor for e in history if e.action == ReviewAction.APPROVE))

        return {
            "status": self.get_status(object_type, object_id).value,
            "rounds": self.get_round(object_type, object_id),
            "total_actions": len(history),
            "ask_backs": ask_backs,
            "returns": returns,
            "approvers": approvers,
            "first_submitted": history[0].created_at,
            "last_action": history[-1].created_at,
            "last_action_type": history[-1].action.value,
            "last_actor": history[-1].actor,
        }

    def can_actor(self, object_type: str, object_id: int,
                  actor_role: str) -> List[ReviewAction]:
        """根据当前状态和角色，列出可以执行的动作"""
        status = self.get_status(object_type, object_id)
        actions = []

        if status == ReviewStatus.DRAFT and actor_role in ("engineer", "senior_engineer", "admin", "verification_manager"):
            actions.append(ReviewAction.SUBMIT)
        if status == ReviewStatus.SUBMITTED and actor_role in ("verification_manager", "admin"):
            actions.extend([ReviewAction.APPROVE, ReviewAction.REJECT, ReviewAction.ASK_BACK, ReviewAction.RETURN_FOR_REVISION])
        if status == ReviewStatus.UNDER_REVIEW and actor_role in ("verification_manager", "admin"):
            actions.extend([ReviewAction.APPROVE, ReviewAction.REJECT, ReviewAction.ASK_BACK, ReviewAction.RETURN_FOR_REVISION])
        if status == ReviewStatus.ASKED_BACK and actor_role in ("engineer", "senior_engineer", "admin"):
            actions.append(ReviewAction.COMMENT)  # respond
        if status == ReviewStatus.RETURNED and actor_role in ("engineer", "senior_engineer", "admin"):
            actions.extend([ReviewAction.REVISE, ReviewAction.RESUBMIT])
        if status == ReviewStatus.SUBMITTED and actor_role in ("engineer", "senior_engineer", "admin"):
            actions.append(ReviewAction.WITHDRAW)

        # 所有人任何时候都可以评论
        if ReviewAction.COMMENT not in actions:
            actions.append(ReviewAction.COMMENT)

        return actions


# ═══════════════════════════════════════════════════════════
# 预定义签核审批链
# ═══════════════════════════════════════════════════════════

def create_signoff_approval_chain(wf: ApprovalWorkflow, signoff_id: int,
                                   requester: str) -> List[ReviewEntry]:
    """为签核创建标准审批链"""
    entries = []
    entries.append(wf.submit("signoff", signoff_id, requester, "engineer",
                              "签核请求已提交，请审核"))
    entries.append(wf.start_review("signoff", signoff_id, "system", "system",
                                    "自动进入审查队列"))
    return entries


# ═══════════════════════════════════════════════════════════
# 全局实例
# ═══════════════════════════════════════════════════════════

_approval_workflow: Optional[ApprovalWorkflow] = None


def get_approval_workflow() -> ApprovalWorkflow:
    global _approval_workflow
    if _approval_workflow is None:
        _approval_workflow = ApprovalWorkflow()
    return _approval_workflow


# ═══════════════════════════════════════════════════════════
# 多步骤审批链 — 角色链 + 超时 + 条件分支
# ═══════════════════════════════════════════════════════════

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class ApprovalStep:
    """审批链中的单步"""
    step_order: int                # 1-based 顺序
    role: str                     # 需要的审批角色
    required: bool = True         # 是否必须
    timeout_hours: int = 0        # 超时小时数，0=不限
    auto_approve_on_timeout: bool = False
    condition: str = ""           # 条件表达式


@dataclass
class ApprovalChain:
    """多步骤审批链配置"""
    chain_id: str
    name: str
    steps: list[ApprovalStep]
    description: str = ""


class MultiStepApprovalEngine:
    """多步骤审批引擎 — 角色链顺序审批 + 超时 + 分支"""

    def __init__(self):
        self._chains: dict[str, ApprovalChain] = {}
        self._active_approvals: dict[str, dict] = {}  # key → {chain, current_step, step_started}
        self._register_builtins()

    def _register_builtins(self):
        """内置审批链"""
        self.register(ApprovalChain(
            chain_id="basic_signoff", name="基础签核审批",
            steps=[ApprovalStep(1, "verification_manager", required=True)],
        ))

        self.register(ApprovalChain(
            chain_id="dual_review", name="双人审批",
            steps=[
                ApprovalStep(1, "senior_engineer", required=True, timeout_hours=48),
                ApprovalStep(2, "verification_manager", required=True, timeout_hours=72),
            ],
        ))

        self.register(ApprovalChain(
            chain_id="tapeout_approval", name="流片签核多级审批",
            steps=[
                ApprovalStep(1, "senior_engineer", required=True, timeout_hours=24),
                ApprovalStep(2, "verification_manager", required=True, timeout_hours=48),
                ApprovalStep(3, "admin", required=True, timeout_hours=72),
            ],
        ))

        self.register(ApprovalChain(
            chain_id="ppa_signoff", name="PPA 签核审批",
            steps=[
                ApprovalStep(1, "senior_engineer", required=True, timeout_hours=48),
                ApprovalStep(2, "verification_manager", required=True,
                            condition="coverage_line_pct >= 95"),
            ],
        ))

    def register(self, chain: ApprovalChain):
        self._chains[chain.chain_id] = chain

    def get_chain(self, chain_id: str) -> ApprovalChain | None:
        return self._chains.get(chain_id)

    def list_chains(self) -> list[dict]:
        return [{
            "chain_id": c.chain_id, "name": c.name,
            "steps": len(c.steps), "description": c.description,
        } for c in self._chains.values()]

    def start_approval(self, object_key: str, chain_id: str) -> dict:
        """启动多步审批"""
        chain = self.get_chain(chain_id)
        if not chain:
            return {"error": f"审批链不存在: {chain_id}"}

        self._active_approvals[object_key] = {
            "chain_id": chain_id,
            "current_step": 1,
            "step_started": datetime.now().isoformat(),
            "step_results": [],
        }
        return {"status": "started", "chain": chain_id,
                "total_steps": len(chain.steps), "current_step": 1}

    def approve_step(self, object_key: str, actor_role: str,
                     actor_name: str = "", comment: str = "") -> dict:
        """审批当前步骤，自动推进到下一步"""
        active = self._active_approvals.get(object_key)
        if not active:
            return {"error": "审批未启动"}

        chain = self.get_chain(active["chain_id"])
        if not chain:
            return {"error": "审批链配置丢失"}

        step_num = active["current_step"]
        step = chain.steps[step_num - 1] if step_num <= len(chain.steps) else None
        if not step:
            return {"status": "completed", "message": "所有步骤已完成"}

        # 检查角色
        if actor_role not in (step.role, "admin"):
            return {"error": f"当前步骤需要 {step.role} 角色审批，你的是 {actor_role}"}

        active["step_results"].append({
            "step": step_num, "role": actor_role,
            "actor": actor_name, "comment": comment,
            "approved_at": datetime.now().isoformat(),
        })

        # 推进到下一步
        next_step = step_num + 1
        if next_step > len(chain.steps):
            active["current_step"] = next_step
            active["completed_at"] = datetime.now().isoformat()
            return {"status": "fully_approved",
                    "total_steps": len(chain.steps),
                    "approved_steps": len(active["step_results"])}

        active["current_step"] = next_step
        active["step_started"] = datetime.now().isoformat()
        return {
            "status": "in_progress",
            "current_step": next_step,
            "total_steps": len(chain.steps),
            "next_role": chain.steps[next_step - 1].role,
        }

    def get_status(self, object_key: str) -> dict:
        """获取审批进度"""
        active = self._active_approvals.get(object_key)
        if not active:
            return {"status": "not_started"}

        chain = self.get_chain(active["chain_id"])
        if not chain:
            return {"status": "error", "message": "chain config missing"}

        current_step = active["current_step"]
        step = chain.steps[current_step - 1] if current_step <= len(chain.steps) else None

        # 检查超时
        timeout_warning = False
        if step and step.timeout_hours > 0:
            try:
                started = datetime.fromisoformat(active["step_started"])
                elapsed = (datetime.now() - started).total_seconds() / 3600
                if elapsed > step.timeout_hours:
                    timeout_warning = True
            except Exception:
                pass

        return {
            "chain_id": active["chain_id"],
            "current_step": current_step,
            "total_steps": len(chain.steps),
            "current_role": step.role if step else "completed",
            "timeout_hours": step.timeout_hours if step else 0,
            "timeout_warning": timeout_warning,
            "completed_steps": active["step_results"],
            "is_complete": current_step > len(chain.steps),
        }

    def check_timeouts(self) -> list[dict]:
        """检查所有超时的审批"""
        timeout_objects = []
        for obj_key, active in self._active_approvals.items():
            status = self.get_status(obj_key)
            if status.get("timeout_warning"):
                timeout_objects.append({
                    "object_key": obj_key,
                    "chain_id": active["chain_id"],
                    "current_step": status["current_step"],
                    "role": status.get("current_role"),
                })
        return timeout_objects


# ── 证据链自动绑定 ──

class SignoffEvidenceBinder:
    """签核生命周期证据自动绑定"""

    async def on_signoff_create(self, signoff_id: int, run_id: str = "",
                                project_id: int = 0):
        """创建签核时：自动扫描并绑定最新 manifest + artifacts"""
        from src.database import repository
        import json

        if not run_id:
            # 尝试自动发现最新 run
            try:
                for mf in sorted(Path("output").glob("**/docs/manifest.json"),
                                 key=lambda p: p.stat().st_mtime, reverse=True):
                    data = json.loads(mf.read_text(encoding="utf-8"))
                    run_id = data.get("run_id", "")
                    break
            except Exception:
                pass

        if run_id:
            # 绑定 manifest artifact
            try:
                aid = await repository.create_artifact(
                    project_id, run_id, signoff_id,
                    "manifest", f"manifest_{run_id}",
                    f"output/{run_id}/docs/manifest.json",
                    content_hash="",
                )
                await repository.link_evidence(aid, "signoff", signoff_id, "attached_to")
            except Exception:
                pass

        return {"signoff_id": signoff_id, "bound_run_id": run_id}

    async def on_signoff_approve(self, signoff_id: int):
        """批准签核时：锁定证据链，hash 写入 signoff"""
        from src.database import repository
        sf = await repository.get_signoff_by_id(signoff_id)
        if not sf:
            return {"error": "签核不存在"}

        # 收集所有关联 artifacts 计算 aggregate evidence hash
        artifacts = await repository.get_artifacts(signoff_id=signoff_id)
        if artifacts:
            import hashlib
            hashes = sorted(a["content_hash"] for a in artifacts if a["content_hash"])
            aggregate = hashlib.sha256("".join(hashes).encode()).hexdigest()
            await repository.update_signoff(signoff_id, sf["status"],
                                           evidence_package_hash=aggregate)

        return {"signoff_id": signoff_id, "artifacts_bound": len(artifacts)}

    async def get_full_trace(self, signoff_id: int) -> dict:
        """获取签核完整追溯链"""
        from src.database import repository
        sf = await repository.get_signoff_by_id(signoff_id)
        if not sf:
            return {"error": "签核不存在"}

        artifacts = await repository.get_artifacts(signoff_id=signoff_id)
        links = await repository.get_evidence_links(object_type="signoff", object_id=signoff_id)
        events = await repository.get_signoff_events(signoff_id)

        trace = {
            "signoff": {"id": sf["id"], "title": sf["title"], "status": sf["status"],
                        "report_type": sf["report_type"],
                        "manifest_hash": sf.get("manifest_hash", ""),
                        "run_id": sf.get("run_id", "")},
            "artifacts": artifacts,
            "evidence_links": links,
            "events": events,
        }

        # 尝试获取 pipeline run 详情
        run_id = sf.get("run_id", "")
        if run_id:
            try:
                run = await repository.get_pipeline_run_by_run_id(run_id)
                trace["pipeline_run"] = run
            except Exception:
                pass

        return trace


# ── 上下文快照差异对比 ──

class ContextDiff:
    """上下文快照差异对比工具"""

    def diff_snapshots(self, snap_a: dict, snap_b: dict) -> dict:
        """对比两个快照的差异"""
        changes = []
        all_keys = set(snap_a.keys()) | set(snap_b.keys())

        for key in sorted(all_keys):
            if key in ("created_at", "completed_at", "snapshot_id", "run_id", "checkpoint_id"):
                continue
            va = snap_a.get(key)
            vb = snap_b.get(key)

            if va != vb:
                changes.append({
                    "key": key,
                    "old": str(va)[:200] if va is not None else "(missing)",
                    "new": str(vb)[:200] if vb is not None else "(missing)",
                })

        return {
            "snapshot_a": snap_a.get("snapshot_id", "?"),
            "snapshot_b": snap_b.get("snapshot_id", "?"),
            "total_changes": len(changes),
            "changes": changes,
        }

    def diff_spec_versions(self, spec_a: str, spec_b: str) -> dict:
        """对比两个 spec 文本的差异"""
        lines_a = spec_a.splitlines() if spec_a else []
        lines_b = spec_b.splitlines() if spec_b else []

        added = [l for l in lines_b if l not in lines_a]
        removed = [l for l in lines_a if l not in lines_b]

        return {
            "lines_a": len(lines_a), "lines_b": len(lines_b),
            "added": len(added), "removed": len(removed),
            "added_lines": added[:20],
            "removed_lines": removed[:20],
        }

    def rollback_analysis(self, snapshots: list[dict]) -> dict:
        """分析回滚路径 — 从最新快照到最早快照的变化序列"""
        if len(snapshots) < 2:
            return {"message": "需要至少 2 个快照进行分析"}

        sequence = []
        for i in range(len(snapshots) - 1, 0, -1):
            newer = snapshots[i]
            older = snapshots[i - 1]
            diff = self.diff_snapshots(newer, older)
            sequence.append({
                "from": newer.get("snapshot_id", "?"),
                "to": older.get("snapshot_id", "?"),
                "changes": diff["total_changes"],
            })

        return {
            "snapshots_count": len(snapshots),
            "rollback_path": sequence,
            "can_rollback_to": snapshots[0].get("snapshot_id", "?"),
        }


# ── 全局 ──
_approval_engine: Optional[MultiStepApprovalEngine] = None
_evidence_binder: Optional[SignoffEvidenceBinder] = None
_context_diff: Optional[ContextDiff] = None


def get_multi_approval_engine() -> MultiStepApprovalEngine:
    global _approval_engine
    if _approval_engine is None:
        _approval_engine = MultiStepApprovalEngine()
    return _approval_engine


def get_evidence_binder() -> SignoffEvidenceBinder:
    global _evidence_binder
    if _evidence_binder is None:
        _evidence_binder = SignoffEvidenceBinder()
    return _evidence_binder


def get_context_diff() -> ContextDiff:
    global _context_diff
    if _context_diff is None:
        _context_diff = ContextDiff()
    return _context_diff
    return _approval_workflow
