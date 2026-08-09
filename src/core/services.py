"""
服务层 — 业务规则收敛点

- 所有业务规则在此处集中
- API 层只做路由和参数校验
- Repository 层只做纯持久化
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.database import repository
from src.core.domain_registry import require_valid_transition, is_terminal_state


class SignoffService:
    """签核业务服务"""

    async def create(self, project_id: int, title: str, report_type: str,
                     summary: dict, requester_id: int, run_id: str = "",
                     manifest_hash: str = "") -> dict:
        """创建签核 — 初始状态 draft"""
        sid = await repository.create_signoff(
            project_id, title, report_type, summary, requester_id,
            run_id=run_id, manifest_hash=manifest_hash)
        return {"id": sid, "status": "pending"}

    async def submit(self, signoff_id: int, actor_id: int, actor_name: str,
                     actor_role: str) -> dict:
        """提交签核 draft → pending"""
        sf = await repository.get_signoff_by_id(signoff_id)
        if not sf:
            raise ValueError("签核不存在")

        from_state = sf["status"]
        require_valid_transition("signoff", from_state, "pending")

        ok = await repository.update_signoff(signoff_id, "pending")
        await repository.add_audit_log(
            actor_id, actor_name, "signoff_submit", str(signoff_id),
            f"{from_state}→pending", role=actor_role,
            resource_type="signoff", before_state=from_state, after_state="pending")
        return {"id": signoff_id, "status": "pending", "from": from_state}

    async def approve(self, signoff_id: int, approver_id: int, approver_name: str,
                      approver_role: str, comment: str = "") -> dict:
        """批准签核 pending → approved"""
        if approver_role not in ("admin", "verification_manager"):
            raise PermissionError("仅 SignOff 经理可以批准签核")

        sf = await repository.get_signoff_by_id(signoff_id)
        if not sf:
            raise ValueError("签核不存在")

        from_state = sf["status"]
        require_valid_transition("signoff", from_state, "approved")

        ok = await repository.update_signoff(
            signoff_id, "approved", approver_id, comment,
            approver_name=approver_name)
        await repository.add_audit_log(
            approver_id, approver_name, "signoff_approve", str(signoff_id),
            f"{from_state}→approved | {comment[:100]}",
            role=approver_role, resource_type="signoff",
            access_result="success", is_privileged=True,
            before_state=from_state, after_state="approved")

        # Trigger workflows
        try:
            from src.infra.workflow_triggers import get_trigger_service
            await get_trigger_service().evaluate("signoff_approved", {
                "signoff_id": signoff_id, "approver": approver_name,
                "project_id": sf.get("project_id", 0),
            })
        except Exception:
            pass

        return {"id": signoff_id, "status": "approved", "from": from_state, "locked": True}

    async def reject(self, signoff_id: int, rejector_id: int, rejector_name: str,
                     rejector_role: str, reason: str = "") -> dict:
        """驳回签核 pending → rejected"""
        if rejector_role not in ("admin", "verification_manager"):
            raise PermissionError("仅 SignOff 经理可以驳回答核")

        sf = await repository.get_signoff_by_id(signoff_id)
        if not sf:
            raise ValueError("签核不存在")

        from_state = sf["status"]
        require_valid_transition("signoff", from_state, "rejected")

        ok = await repository.update_signoff(
            signoff_id, "rejected", rejector_id, reason,
            reject_reason=reason)
        await repository.add_audit_log(
            rejector_id, rejector_name, "signoff_reject", str(signoff_id),
            f"{from_state}→rejected | {reason[:100]}",
            role=rejector_role, resource_type="signoff",
            access_result="success", is_privileged=True,
            before_state=from_state, after_state="rejected")

        try:
            from src.infra.workflow_triggers import get_trigger_service
            await get_trigger_service().evaluate("signoff_rejected", {
                "signoff_id": signoff_id, "reason": reason,
                "project_id": sf.get("project_id", 0),
            })
        except Exception:
            pass

        return {"id": signoff_id, "status": "rejected", "from": from_state}

    async def reopen(self, signoff_id: int, actor_id: int, actor_name: str,
                     actor_role: str) -> dict:
        """重新打开 rejected → draft"""
        sf = await repository.get_signoff_by_id(signoff_id)
        if not sf:
            raise ValueError("签核不存在")
        from_state = sf["status"]
        require_valid_transition("signoff", from_state, "draft")

        ok = await repository.update_signoff(signoff_id, "draft")
        await repository.add_audit_log(
            actor_id, actor_name, "signoff_reopen", str(signoff_id),
            f"{from_state}→draft", role=actor_role,
            resource_type="signoff", before_state=from_state, after_state="draft")
        return {"id": signoff_id, "status": "draft"}

    async def soft_delete(self, signoff_id: int, actor_id: int, actor_name: str,
                          actor_role: str) -> dict:
        """软删除"""
        ok = await repository.soft_delete_signoff(signoff_id)
        if not ok:
            raise ValueError("签核不存在")
        await repository.add_audit_log(
            actor_id, actor_name, "signoff_soft_delete", str(signoff_id),
            "软删除", role=actor_role, resource_type="signoff", is_privileged=True)
        return {"id": signoff_id, "status": "deleted"}

    async def archive(self, signoff_id: int, actor_id: int, actor_name: str,
                      actor_role: str) -> dict:
        """归档"""
        ok = await repository.archive_signoff(signoff_id)
        if not ok:
            raise ValueError("签核不存在")
        await repository.add_audit_log(
            actor_id, actor_name, "signoff_archive", str(signoff_id),
            "归档", role=actor_role, resource_type="signoff")
        return {"id": signoff_id, "status": "archived"}


class DocService:
    """文档业务服务"""

    async def update(self, doc_id: int, content: str, author_id: int,
                     change_summary: str = "") -> dict:
        """更新文档 — 自动版本管理 + 状态校验"""
        doc = await repository.get_document(doc_id)
        if not doc:
            raise ValueError("文档不存在")

        # 审批中的文档不可直接编辑
        if doc.get("status") == "review":
            raise ValueError("文档正在审批中，无法编辑。请先退回或等审批完成")

        result = await repository.update_document(doc_id, content, author_id, change_summary)
        if result == 0:
            raise ValueError("更新失败")

        await repository.add_audit_log(
            author_id, "", "doc_update", f"doc/{doc_id}",
            f"更新: {change_summary}", resource_type="doc",
            before_state=doc.get("status", ""), after_state=doc.get("status", ""))

        return {"id": result, "status": "updated"}

    async def submit_for_review(self, doc_id: int, actor_id: int, actor_name: str) -> dict:
        """提交审批 draft → review"""
        doc = await repository.get_document(doc_id)
        if not doc:
            raise ValueError("文档不存在")
        require_valid_transition("doc", doc.get("status", "draft"), "review")

        # 更新数据库中的状态
        from src.database.connection import get_session
        from src.database.models import DocDocument
        from sqlalchemy import select
        s = await get_session()
        d = (await s.execute(select(DocDocument).where(DocDocument.id == doc_id))).scalar_one_or_none()
        if d:
            d.status = "review"
            d.updated_at = datetime.now()
            await s.commit()
        await s.close()

        await repository.add_audit_log(
            actor_id, actor_name, "doc_submit_review", f"doc/{doc_id}",
            "draft→review", resource_type="doc",
            before_state="draft", after_state="review")
        return {"id": doc_id, "status": "review"}

    async def approve(self, doc_id: int, actor_id: int, actor_name: str) -> dict:
        """批准文档 review → approved"""
        doc = await repository.get_document(doc_id)
        if not doc:
            raise ValueError("文档不存在")
        require_valid_transition("doc", doc.get("status", "review"), "approved")

        from src.database.connection import get_session
        from src.database.models import DocDocument
        from sqlalchemy import select
        s = await get_session()
        d = (await s.execute(select(DocDocument).where(DocDocument.id == doc_id))).scalar_one_or_none()
        if d:
            d.status = "approved"
            d.updated_at = datetime.now()
            await s.commit()
        await s.close()

        await repository.add_audit_log(
            actor_id, actor_name, "doc_approve", f"doc/{doc_id}",
            "review→approved", resource_type="doc",
            before_state="review", after_state="approved")
        return {"id": doc_id, "status": "approved"}

    async def deprecate(self, doc_id: int, actor_id: int, actor_name: str) -> dict:
        """废弃文档 approved → deprecated"""
        doc = await repository.get_document(doc_id)
        if not doc:
            raise ValueError("文档不存在")
        require_valid_transition("doc", doc.get("status", "approved"), "deprecated")

        from src.database.connection import get_session
        from src.database.models import DocDocument
        from sqlalchemy import select
        s = await get_session()
        d = (await s.execute(select(DocDocument).where(DocDocument.id == doc_id))).scalar_one_or_none()
        if d:
            d.status = "deprecated"
            d.updated_at = datetime.now()
            await s.commit()
        await s.close()

        await repository.add_audit_log(
            actor_id, actor_name, "doc_deprecate", f"doc/{doc_id}",
            "approved→deprecated", resource_type="doc",
            before_state="approved", after_state="deprecated")
        return {"id": doc_id, "status": "deprecated"}


class PipelineService:
    """流水线业务服务"""

    async def cancel(self, run_id: str, actor_id: int, actor_name: str) -> dict:
        """取消流水线 running → cancelled"""
        from src.database.repository import get_pipeline_run_by_run_id, add_audit_log
        run = await get_pipeline_run_by_run_id(run_id)
        if not run:
            raise ValueError("流水线不存在")

        require_valid_transition("pipeline",
                                 run.get("state", "running"),
                                 "cancelled")

        from src.database.connection import get_session
        from src.database.models import PipelineRun
        from sqlalchemy import select
        s = await get_session()
        r = (await s.execute(select(PipelineRun).where(PipelineRun.run_id == run_id))).scalar_one_or_none()
        if r:
            r.state = "cancelled"
            r.completed_at = datetime.now()
            await s.commit()
        await s.close()

        await add_audit_log(
            actor_id, actor_name, "pipeline_cancel", run_id,
            "running→cancelled", resource_type="pipeline",
            before_state="running", after_state="cancelled")
        return {"run_id": run_id, "state": "cancelled"}


# ── 全局服务单例 ──
_signoff_service: Optional[SignoffService] = None
_doc_service: Optional[DocService] = None
_pipeline_service: Optional[PipelineService] = None


def get_signoff_service() -> SignoffService:
    global _signoff_service
    if _signoff_service is None:
        _signoff_service = SignoffService()
    return _signoff_service


def get_doc_service() -> DocService:
    global _doc_service
    if _doc_service is None:
        _doc_service = DocService()
    return _doc_service


def get_pipeline_service() -> PipelineService:
    global _pipeline_service
    if _pipeline_service is None:
        _pipeline_service = PipelineService()
    return _pipeline_service
