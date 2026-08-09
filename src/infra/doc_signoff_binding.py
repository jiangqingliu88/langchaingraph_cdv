"""
文档↔签核工作流绑定 — 文档生态闭环

- 文档变更自动触发签核审查
- 文档版本与签核绑定
- 文档与需求/测试的互联追踪
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from src.database import repository


class DocSignoffBinding:
    """文档-签核绑定服务"""

    # ── 文档变更 → 签核关联检查 ──

    async def on_doc_updated(self, doc_id: int, author_id: int, author_name: str,
                             change_summary: str = ""):
        """文档更新后：检查是否有关联的已批准签核需要重新审查"""
        # 查找关联此文档的所有签核
        signoffs = await self._find_linked_signoffs(doc_id)
        affected = []

        for sf in signoffs:
            if sf.get("status") == "approved":
                # 已批准的签核，文档变更后需要标记审阅
                await repository.add_audit_log(
                    author_id, author_name, "doc_change_requires_review",
                    f"signoff/{sf['id']}",
                    f"文档 doc/{doc_id} 已变更，关联签核 #{sf['id']} 可能需要重新审查",
                    resource_type="signoff",
                    is_privileged=True,
                )
                affected.append({
                    "signoff_id": sf["id"],
                    "action": "review_needed",
                    "reason": f"关联文档已变更: {change_summary}",
                })

        return {
            "doc_id": doc_id,
            "linked_signoffs": len(signoffs),
            "affected": affected,
        }

    async def on_doc_approved(self, doc_id: int, actor_id: int, actor_name: str):
        """文档被批准后：自动绑定到相关签核的证据"""
        signoffs = await self._find_linked_signoffs(doc_id)

        for sf in signoffs:
            # 将文档版本作为证据绑定到签核
            doc = await repository.get_document(doc_id)
            if doc:
                await repository.link_evidence(
                    artifact_id=0,  # 由 create_artifact 创建后赋值
                    object_type="signoff",
                    object_id=sf["id"],
                    relation_type="referenced_by",
                )
                await repository.add_audit_log(
                    actor_id, actor_name, "doc_bound_to_signoff",
                    f"signoff/{sf['id']}",
                    f"文档 doc/{doc_id} v{doc.get('content_hash','')[:12]} 绑定到签核 #{sf['id']}",
                    resource_type="signoff",
                )

        return {
            "doc_id": doc_id,
            "bound_to": len(signoffs),
        }

    async def _find_linked_signoffs(self, doc_id: int) -> list[dict]:
        """查找与此文档关联的签核"""
        doc = await repository.get_document(doc_id)
        if not doc:
            return []

        project_id = doc.get("project_id", 0)
        if project_id:
            return await repository.list_signoffs(project_id)
        return []

    # ── 文档变更追踪链 ──

    async def get_doc_trace(self, doc_id: int) -> dict:
        """获取文档的完整追踪链：版本 → 关联测试 → 关联签核 → 审计记录"""
        doc = await repository.get_document(doc_id)
        if not doc:
            raise ValueError("文档不存在")

        # 获取文档所有审计记录
        audit_logs = await repository.get_audit_logs(limit=200)
        doc_audit = [
            l for l in audit_logs
            if f"doc/{doc_id}" in str(l.get("resource", ""))
            or f"doc/{doc_id}" in str(l.get("target_id", ""))
        ]

        # 获取关联需求
        reqs = []
        for r in doc.get("requirements", []):
            req_id = r.get("req_id", "")
            if req_id:
                trace = await repository.get_requirement_trace(req_id)
                reqs.append(trace if trace else {"req_id": req_id})

        # 获取关联签核
        signoffs = await self._find_linked_signoffs(doc_id)

        return {
            "doc_id": doc_id,
            "title": doc.get("title", ""),
            "path": doc.get("path", ""),
            "current_version": doc.get("content_hash", "")[:16],
            "versions": doc.get("versions", []),
            "requirements": reqs,
            "linked_signoffs": [
                {"id": s["id"], "title": s["title"], "status": s["status"]}
                for s in signoffs
            ],
            "audit_trail": [
                {"action": l.get("action"), "user": l.get("username"),
                 "detail": l.get("detail", ""), "time": l.get("created_at")}
                for l in doc_audit[:20]
            ],
        }


# ── 全局 ──
_binding: Optional[DocSignoffBinding] = None


def get_doc_signoff_binding() -> DocSignoffBinding:
    global _binding
    if _binding is None:
        _binding = DocSignoffBinding()
    return _binding
