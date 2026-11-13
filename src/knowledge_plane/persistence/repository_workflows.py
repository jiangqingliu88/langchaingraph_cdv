"""数据访问层 —— 企业级 CRUD（Phase 4 按领域拆分）。"""
from __future__ import annotations

from sqlalchemy import select, desc, func, delete
from src.knowledge_plane.persistence.connection import get_session
from src.knowledge_plane.persistence.models import (
    TaskRecord, PipelineRun, User, Project, ProjectMember,
    AuditLog, KnowledgeEntry, Signoff, SignoffEvent,
    Artifact, EvidenceLink, RegressionRecord,
    DocDocument, DocVersion, DocRequirement, DocRelation,
    PPAMetric, PPACorner, PPAConstraint, RoleWorkflowBinding,
)
import hashlib
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from config.paths import MAIN_DB


async def seed_default_role_workflow_bindings():
    """首次启动时填充默认角色→工作流映射（幂等：仅在表为空时填充）"""
    defaults = [
        ("admin", "full_verification", True, "系统默认"),
        ("verification_manager", "full_verification", True, "系统默认"),
        ("senior_engineer", "full_verification", True, "系统默认"),
        ("engineer", "full_verification", True, "系统默认"),
        ("viewer", "quick_check", True, "系统默认"),
    ]
    s = await get_session()
    count = (await s.execute(select(func.count()).select_from(RoleWorkflowBinding))).scalar()
    if count == 0:
        for role, wf, is_default, desc in defaults:
            s.add(RoleWorkflowBinding(role=role, workflow_name=wf, is_default=is_default,
                                       description=desc))
        await s.commit()
    await s.close()


async def list_role_workflow_bindings(role: str = "") -> list[dict]:
    """列出角色→工作流绑定，可按角色过滤"""
    s = await get_session()
    q = select(RoleWorkflowBinding).order_by(RoleWorkflowBinding.role, RoleWorkflowBinding.workflow_name)
    if role:
        q = q.where(RoleWorkflowBinding.role == role)
    result = await s.execute(q)
    bindings = result.scalars().all()
    await s.close()
    return [{"id": b.id, "role": b.role, "workflow_name": b.workflow_name,
             "is_default": b.is_default, "is_active": b.is_active,
             "description": b.description or "",
             "created_at": str(b.created_at) if b.created_at else ""} for b in bindings]


async def get_role_workflow_binding(binding_id: int):
    """获取单条绑定"""
    s = await get_session()
    b = (await s.execute(
        select(RoleWorkflowBinding).where(RoleWorkflowBinding.id == binding_id)
    )).scalar_one_or_none()
    await s.close()
    return b


async def create_role_workflow_binding(role: str, workflow_name: str, is_default: bool = False,
                                       description: str = "", created_by: int = None) -> int:
    """创建角色→工作流绑定。如设为默认，先清除该角色其他默认标记"""
    s = await get_session()
    if is_default:
        existing = (await s.execute(
            select(RoleWorkflowBinding).where(
                RoleWorkflowBinding.role == role,
                RoleWorkflowBinding.is_default == True
            )
        )).scalars().all()
        for ex in existing:
            ex.is_default = False
    b = RoleWorkflowBinding(role=role, workflow_name=workflow_name, is_default=is_default,
                            description=description, created_by=created_by)
    s.add(b)
    await s.flush()
    bid = b.id
    await s.commit()
    await s.close()
    return bid


async def update_role_workflow_binding(binding_id: int, **fields) -> bool:
    """更新绑定。如设 is_default=True，先清除同角色其他默认标记"""
    s = await get_session()
    b = (await s.execute(
        select(RoleWorkflowBinding).where(RoleWorkflowBinding.id == binding_id)
    )).scalar_one_or_none()
    if not b:
        await s.close(); return False
    if fields.get("is_default"):
        existing = (await s.execute(
            select(RoleWorkflowBinding).where(
                RoleWorkflowBinding.role == b.role,
                RoleWorkflowBinding.is_default == True,
                RoleWorkflowBinding.id != binding_id
            )
        )).scalars().all()
        for ex in existing:
            ex.is_default = False
    for k, v in fields.items():
        if hasattr(b, k):
            setattr(b, k, v)
    b.updated_at = datetime.now()
    await s.commit()
    await s.close()
    return True


async def delete_role_workflow_binding(binding_id: int) -> bool:
    """删除绑定"""
    s = await get_session()
    b = (await s.execute(
        select(RoleWorkflowBinding).where(RoleWorkflowBinding.id == binding_id)
    )).scalar_one_or_none()
    if b:
        await s.delete(b)
        await s.commit()
        await s.close()
        return True
    await s.close()
    return False


async def get_default_workflow_for_role(role: str) -> str:
    """获取角色的默认工作流，fallback: full_verification"""
    s = await get_session()
    b = (await s.execute(
        select(RoleWorkflowBinding).where(
            RoleWorkflowBinding.role == role,
            RoleWorkflowBinding.is_default == True,
            RoleWorkflowBinding.is_active == True
        )
    )).scalar_one_or_none()
    await s.close()
    return b.workflow_name if b else "full_verification"


async def get_allowed_workflows_for_role(role: str) -> list[str]:
    """获取角色可用的工作流列表，fallback: full_verification + quick_check"""
    s = await get_session()
    result = await s.execute(
        select(RoleWorkflowBinding.workflow_name).where(
            RoleWorkflowBinding.role == role,
            RoleWorkflowBinding.is_active == True
        )
    )
    names = list(dict.fromkeys(r[0] for r in result.all()))  # 去重保序
    await s.close()
    return names if names else ["full_verification", "quick_check"]
