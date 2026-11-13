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


async def save_task(role, ttype, inp, out, status, error=None, extime=0):
    s = await get_session()
    r = TaskRecord(agent_role=role, task_type=ttype, input_text=str(inp)[:5000],
                   output_text=str(out)[:10000], status=status, error_msg=error,
                   execution_time=extime)
    s.add(r); await s.commit(); await s.close()

async def save_pipeline_run(wf, spec, total, passed, degraded, ttime, results):
    """Legacy: 兼容旧调用。新代码使用 create/update_pipeline_run。"""
    s = await get_session()
    import uuid
    r = PipelineRun(run_id=str(uuid.uuid4().hex[:12]), workflow=wf, spec_file=spec,
                    total_phases=total, passed=passed, degraded=degraded,
                    total_time=ttime, results=results, state='completed')
    s.add(r); await s.commit(); await s.close()


async def create_pipeline_run(run_id: str, workflow: str, spec: str, total_phases: int) -> None:
    s = await get_session()
    r = PipelineRun(run_id=run_id, workflow=workflow, spec_file=spec[:500],
                    total_phases=total_phases, state='running', passed=0, degraded=0)
    s.add(r); await s.commit(); await s.close()


async def update_pipeline_run(run_id: str, **fields) -> bool:
    """按 run_id 更新流水线运行记录。支持 state / phases_json / results / passed / degraded / total_time / completed_at。"""
    s = await get_session()
    result = await s.execute(select(PipelineRun).where(PipelineRun.run_id == run_id))
    r = result.scalar_one_or_none()
    if not r:
        await s.close(); return False
    for k, v in fields.items():
        if hasattr(r, k):
            setattr(r, k, v)
    await s.commit(); await s.close()
    return True


async def get_pipeline_run_by_run_id(run_id: str):
    """按 run_id 查询流水线运行记录（服务重启后 SSE 回退查询）。"""
    s = await get_session()
    result = await s.execute(select(PipelineRun).where(PipelineRun.run_id == run_id))
    r = result.scalar_one_or_none(); await s.close()
    if not r:
        return None
    return {
        'run_id': r.run_id, 'workflow': r.workflow, 'state': r.state,
        'phases': r.phases_json or [], 'passed': r.passed or 0, 'total': r.total_phases or 0,
        'started_at': str(r.started_at), 'completed_at': str(r.completed_at) if r.completed_at else None,
    }

async def get_recent_tasks(limit=20):
    s = await get_session()
    result = await s.execute(select(TaskRecord).order_by(desc(TaskRecord.created_at)).limit(limit))
    tasks = result.scalars().all(); await s.close()
    return [{'agent': t.agent_role, 'status': t.status, 'time': t.execution_time,
             'created': str(t.created_at)} for t in tasks]

async def get_recent_pipelines(limit=10):
    s = await get_session()
    result = await s.execute(select(PipelineRun).order_by(desc(PipelineRun.created_at)).limit(limit))
    runs = result.scalars().all(); await s.close()
    return [{'workflow': r.workflow, 'passed': r.passed, 'total': r.total_phases,
             'time': r.total_time, 'created': str(r.created_at)} for r in runs]

# ── 用户 ──

async def get_user_by_username(username: str):
    s = await get_session()
    result = await s.execute(select(User).where(User.username == username))
    u = result.scalar_one_or_none(); await s.close(); return u

async def get_user_by_id(uid: int):
    s = await get_session()
    result = await s.execute(select(User).where(User.id == uid))
    u = result.scalar_one_or_none(); await s.close(); return u

async def create_user(username: str, password_hash: str, display_name: str = "", email: str = "", role: str = "engineer"):
    s = await get_session()
    u = User(username=username, password_hash=password_hash, display_name=display_name or username,
             email=email, role=role)
    s.add(u); await s.flush()
    uid = u.id; await s.commit(); await s.close(); return uid

async def update_user_login(uid: int):
    s = await get_session()
    u = (await s.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if u: u.last_login = __import__('datetime').datetime.now(); await s.commit()
    await s.close()

async def update_user_password(uid: int, password_hash: str):
    s = await get_session()
    u = (await s.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if u:
        u.password_hash = password_hash
        await s.commit()
    await s.close()

async def list_users():
    s = await get_session()
    result = await s.execute(select(User).order_by(User.id))
    users = result.scalars().all(); await s.close()
    return [{'id': u.id, 'username': u.username, 'display_name': u.display_name,
             'email': u.email, 'role': u.role, 'is_active': u.is_active,
             'created_at': str(u.created_at), 'last_login': str(u.last_login) if u.last_login else None} for u in users]

# ── 项目 ──

async def create_project(name: str, description: str, owner_id: int):
    s = await get_session()
    p = Project(name=name, description=description, owner_id=owner_id)
    s.add(p); await s.flush()
    pid = p.id; pname = p.name
    pm = ProjectMember(project_id=pid, user_id=owner_id, role='owner')
    s.add(pm); await s.commit(); await s.close()
    return {'id': pid, 'name': pname, 'description': description, 'owner_id': owner_id}

async def list_projects(user_id: int = None):
    s = await get_session()
    if user_id:
        result = await s.execute(
            select(Project).join(ProjectMember).where(ProjectMember.user_id == user_id)
        )
    else:
        result = await s.execute(select(Project))
    projects = result.scalars().all(); await s.close()
    return [{'id': p.id, 'name': p.name, 'description': p.description,
             'owner_id': p.owner_id, 'status': p.status, 'created_at': str(p.created_at)} for p in projects]

async def get_project(pid: int):
    s = await get_session()
    result = await s.execute(select(Project).where(Project.id == pid))
    p = result.scalar_one_or_none()
    if p:
        members = await s.execute(select(ProjectMember).where(ProjectMember.project_id == pid))
        ml = []
        for m in members.scalars().all():
            u = (await s.execute(select(User).where(User.id == m.user_id))).scalar_one_or_none()
            ml.append({'user_id': m.user_id, 'role': m.role,
                       'username': u.username if u else '', 'display_name': u.display_name if u else ''})
        await s.close()
        return {'id': p.id, 'name': p.name, 'description': p.description,
                'owner_id': p.owner_id, 'status': p.status, 'members': ml,
                'created_at': str(p.created_at)}
    await s.close(); return None

async def add_project_member(project_id: int, user_id: int, role: str = 'member'):
    s = await get_session()
    pm = ProjectMember(project_id=project_id, user_id=user_id, role=role)
    s.add(pm); await s.commit(); await s.close(); return True

# ── 审计日志 ──

async def add_audit_log(user_id: int, username: str, action: str, resource: str = "", detail: str = "",
                       ip: str = "", role: str = "", resource_type: str = "", access_result: str = "success",
                       is_privileged: bool = False, before_state: str = "", after_state: str = ""):
    """增强审计日志 — 带角色上下文、越权检测、状态变更记录、哈希链"""
    s = await get_session()
    # 如果没有传 role，尝试从用户表查询
    if not role and user_id:
        u = (await s.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        role = u.role if u else ""

    # 获取上一条审计记录的 chain_hash 作为 prev_hash
    last_log = (await s.execute(
        select(AuditLog).order_by(desc(AuditLog.id)).limit(1)
    )).scalar_one_or_none()

    prev_hash = last_log.chain_hash if last_log and last_log.chain_hash else ""
    chain_index = (last_log.chain_index + 1) if last_log else 0

    a = AuditLog(
        user_id=user_id, username=username, role=role,
        action=action, resource_type=resource_type, resource=resource,
        detail=detail, ip_address=ip,
        access_result=access_result, is_privileged_action=is_privileged,
        before_state=before_state, after_state=after_state,
        prev_hash=prev_hash, chain_index=chain_index,
    )
    s.add(a)
    await s.flush()  # 获取 a.id

    # 计算当前记录的链式 hash
    raw = f"{chain_index}|{a.id}|{user_id}|{username}|{action}|{resource}|{detail}|{prev_hash}"
    a.chain_hash = hashlib.sha256(raw.encode()).hexdigest()

    await s.commit()
    await s.close()

async def get_audit_logs(limit: int = 50, project_id: str = None, action_filter: str = None,
                        role_filter: str = None, access_result: str = None):
    """增强审计日志查询 — 支持按操作类型、角色、访问结果过滤"""
    s = await get_session()
    q = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    if project_id: q = q.where(AuditLog.resource == project_id)
    if action_filter: q = q.where(AuditLog.action == action_filter)
    if role_filter: q = q.where(AuditLog.role == role_filter)
    if access_result: q = q.where(AuditLog.access_result == access_result)
    result = await s.execute(q)
    logs = result.scalars().all(); await s.close()
    return [{'id': l.id, 'username': l.username, 'role': l.role,
             'action': l.action, 'resource_type': l.resource_type,
             'resource': l.resource, 'target_id': l.target_id,
             'detail': l.detail, 'access_result': l.access_result,
             'is_privileged_action': l.is_privileged_action,
             'before_state': l.before_state, 'after_state': l.after_state,
             'chain_hash': l.chain_hash, 'chain_index': l.chain_index,
             'created_at': str(l.created_at)} for l in logs]


async def verify_audit_chain() -> dict:
    """验证审计链完整性 — 检测是否有记录被篡改或删除"""
    import hashlib
    s = await get_session()
    logs = (await s.execute(
        select(AuditLog).order_by(AuditLog.chain_index)
    )).scalars().all()
    await s.close()

    issues = []
    prev_hash = ""
    expected_index = 0
    for l in logs:
        # 检查序号连续性
        if l.chain_index != expected_index:
            issues.append({
                "type": "missing_record",
                "index": expected_index,
                "detail": f"审计链缺少序号 {expected_index}，可能被删除",
            })
            expected_index = l.chain_index + 1
        else:
            expected_index += 1

        # 检查 prev_hash 链接
        if l.prev_hash != prev_hash:
            issues.append({
                "type": "hash_broken",
                "id": l.id,
                "index": l.chain_index,
                "expected_prev": prev_hash[:16],
                "actual_prev": l.prev_hash[:16],
                "detail": f"记录 #{l.id} 的前驱哈希不匹配，审计链可能被篡改",
            })
        prev_hash = l.chain_hash

        # 验证自身 hash
        raw = f"{l.chain_index}|{l.id}|{l.user_id}|{l.username}|{l.action}|{l.resource}|{l.detail}|{l.prev_hash}"
        expected_hash = hashlib.sha256(raw.encode()).hexdigest()
        if l.chain_hash != expected_hash:
            issues.append({
                "type": "hash_mismatch",
                "id": l.id,
                "index": l.chain_index,
                "detail": f"记录 #{l.id} 的链哈希不匹配，内容可能被篡改",
            })

    return {
        "valid": len(issues) == 0,
        "total_records": len(logs),
        "issues": issues,
        "latest_hash": logs[-1].chain_hash if logs else "",
        "message": "审计链完整" if len(issues) == 0 else f"发现 {len(issues)} 个问题",
    }

# ── 知识库 ──

async def create_knowledge(title: str, category: str, tags: str, content: str, author_id: int):
    s = await get_session()
    k = KnowledgeEntry(title=title, category=category, tags=tags, content=content, author_id=author_id)
    s.add(k); await s.flush()
    kid = k.id; await s.commit(); await s.close(); return kid

async def search_knowledge(query: str = "", category: str = "", limit: int = 20):
    s = await get_session()
    q = select(KnowledgeEntry).order_by(desc(KnowledgeEntry.usage_count)).limit(limit)
    if query: q = q.where(KnowledgeEntry.title.contains(query) | KnowledgeEntry.content.contains(query))
    if category: q = q.where(KnowledgeEntry.category == category)
    result = await s.execute(q)
    entries = result.scalars().all(); await s.close()
    return [{'id': e.id, 'title': e.title, 'category': e.category, 'tags': e.tags,
             'content': e.content[:500], 'version': e.version,
             'usage_count': e.usage_count, 'created_at': str(e.created_at)} for e in entries]

# ── 签核 ──

async def check_project_membership(user_id: int, project_id: int) -> bool:
    """检查用户是否为项目成员。管理员和经理始终返回 True。"""
    if not project_id:
        return True
    s = await get_session()
    user = (await s.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user and user.role in ("admin", "verification_manager"):
        await s.close(); return True
    member = (await s.execute(
        select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
    )).scalar_one_or_none()
    await s.close(); return member is not None


async def create_signoff(project_id: int, title: str, report_type: str, summary: dict, requester_id: int,
                       run_id: str = "", manifest_hash: str = ""):
    s = await get_session()
    sf = Signoff(project_id=project_id, title=title, report_type=report_type,
                 summary_json=summary, requester_id=requester_id, status='pending',
                 run_id=run_id, manifest_hash=manifest_hash)
    s.add(sf); await s.flush()
    sid = sf.id

    # 记录事件
    username = ""
    u = (await s.execute(select(User).where(User.id == requester_id))).scalar_one_or_none()
    if u: username = u.username
    evt = SignoffEvent(signoff_id=sid, event_type='submitted', actor_id=requester_id,
                       actor_name=username, actor_role=u.role if u else "",
                       before_status='', after_status='pending')
    s.add(evt)
    await s.commit(); await s.close(); return sid


async def list_signoffs(project_id: int = None, limit: int = 20):
    s = await get_session()
    q = select(Signoff).where(Signoff.is_deleted == False).order_by(desc(Signoff.created_at)).limit(limit)
    if project_id: q = q.where(Signoff.project_id == project_id)
    result = await s.execute(q)
    sfs = result.scalars().all(); await s.close()
    return [{'id': sf.id, 'project_id': sf.project_id, 'title': sf.title,
             'report_type': sf.report_type, 'status': sf.status,
             'summary': sf.summary_json, 'comment': sf.comment,
             'manifest_hash': sf.manifest_hash, 'run_id': sf.run_id,
             'approved_by_name': sf.approved_by_name, 'approved_at': str(sf.approved_at) if sf.approved_at else '',
             'reject_reason': sf.reject_reason,
             'version': sf.version, 'is_archived': sf.is_archived,
             'created_at': str(sf.created_at)} for sf in sfs]


async def get_signoff_by_id(sid: int):
    """获取单条签核记录"""
    s = await get_session()
    sf = (await s.execute(select(Signoff).where(Signoff.id == sid, Signoff.is_deleted == False))).scalar_one_or_none()
    if sf:
        result = {"id": sf.id, "project_id": sf.project_id, "title": sf.title,
                  "report_type": sf.report_type, "status": sf.status,
                  "summary": sf.summary_json, "requester_id": sf.requester_id,
                  "approver_id": sf.approver_id, "comment": sf.comment,
                  "manifest_hash": sf.manifest_hash, "evidence_package_hash": sf.evidence_package_hash,
                  "run_id": sf.run_id, "approved_by_name": sf.approved_by_name,
                  "approved_at": str(sf.approved_at) if sf.approved_at else '',
                  "reject_reason": sf.reject_reason,
                  "created_at": str(sf.created_at), "updated_at": str(sf.updated_at)}
        await s.close(); return result
    await s.close(); return None


async def update_signoff(sid: int, status: str, approver_id: int = None, comment: str = "",
                         approver_name: str = "", reject_reason: str = "",
                         expected_version: int = None):
    """更新签核状态 — 支持乐观锁 (expected_version)"""
    s = await get_session()
    sf = (await s.execute(select(Signoff).where(Signoff.id == sid, Signoff.is_deleted == False))).scalar_one_or_none()
    if not sf:
        await s.close(); return False

    # 乐观锁检查
    if expected_version is not None and sf.version != expected_version:
        await s.close()
        raise ConcurrentUpdateError(f"Signoff #{sid} was modified by another user. Expected v{expected_version}, got v{sf.version}")

    old_status = sf.status
    sf.status = status
    if approver_id: sf.approver_id = approver_id
    if comment: sf.comment = comment
    if approver_name: sf.approved_by_name = approver_name
    if reject_reason: sf.reject_reason = reject_reason
    if status == 'approved':
        sf.approved_at = datetime.now()
    sf.updated_at = datetime.now()
    sf.version = (sf.version or 0) + 1

    # 记录事件
    event_type = {'approved': 'approved', 'rejected': 'rejected',
                  'pending': 'submitted', 'draft': 'draft'}.get(status, 'commented')
    actor_role = ""
    actor_name = approver_name
    if approver_id:
        u = (await s.execute(select(User).where(User.id == approver_id))).scalar_one_or_none()
        if u:
            actor_name = actor_name or u.username
            actor_role = u.role
    evt = SignoffEvent(signoff_id=sid, event_type=event_type, actor_id=approver_id,
                       actor_name=actor_name, actor_role=actor_role,
                       comment=comment or reject_reason,
                       before_status=old_status, after_status=status)
    s.add(evt)
    await s.commit()
    await s.close(); return True


class ConcurrentUpdateError(Exception):
    """乐观锁冲突异常"""
    pass


async def soft_delete_signoff(sid: int) -> bool:
    """软删除签核"""
    s = await get_session()
    sf = (await s.execute(select(Signoff).where(Signoff.id == sid))).scalar_one_or_none()
    if sf:
        sf.is_deleted = True
        sf.deleted_at = datetime.now()
        sf.updated_at = datetime.now()
        await s.commit()
    await s.close(); return sf is not None


async def archive_signoff(sid: int) -> bool:
    """归档签核"""
    s = await get_session()
    sf = (await s.execute(select(Signoff).where(Signoff.id == sid))).scalar_one_or_none()
    if sf:
        sf.is_archived = True
        sf.updated_at = datetime.now()
        await s.commit()
    await s.close(); return sf is not None


async def get_signoff_events(sid: int, limit: int = 50):
    """获取签核的所有事件（审批历史）"""
    s = await get_session()
    q = select(SignoffEvent).where(SignoffEvent.signoff_id == sid).order_by(desc(SignoffEvent.created_at)).limit(limit)
    result = await s.execute(q)
    events = result.scalars().all(); await s.close()
    return [{'id': e.id, 'signoff_id': e.signoff_id, 'event_type': e.event_type,
             'actor_id': e.actor_id, 'actor_name': e.actor_name, 'actor_role': e.actor_role,
             'comment': e.comment, 'before_status': e.before_status, 'after_status': e.after_status,
             'evidence_hash': e.evidence_hash, 'created_at': str(e.created_at)} for e in events]


# ── 证据产物 ──

async def create_artifact(project_id: int, run_id: str, signoff_id: int, artifact_type: str,
                          name: str, path: str = "", content_hash: str = "",
                          size_bytes: int = 0, metadata: dict = None):
    s = await get_session()
    a = Artifact(project_id=project_id, run_id=run_id, signoff_id=signoff_id if signoff_id else None,
                 artifact_type=artifact_type, name=name, path=path,
                 content_hash=content_hash, size_bytes=size_bytes,
                 metadata_json=metadata or {})
    s.add(a); await s.flush()
    aid = a.id; await s.commit(); await s.close(); return aid


async def get_artifacts(run_id: str = None, signoff_id: int = None, artifact_type: str = None, limit: int = 50):
    s = await get_session()
    q = select(Artifact).order_by(desc(Artifact.created_at)).limit(limit)
    if run_id: q = q.where(Artifact.run_id == run_id)
    if signoff_id: q = q.where(Artifact.signoff_id == signoff_id)
    if artifact_type: q = q.where(Artifact.artifact_type == artifact_type)
    result = await s.execute(q)
    arts = result.scalars().all(); await s.close()
    return [{'id': a.id, 'project_id': a.project_id, 'run_id': a.run_id,
             'signoff_id': a.signoff_id, 'artifact_type': a.artifact_type,
             'name': a.name, 'path': a.path, 'content_hash': a.content_hash,
             'size_bytes': a.size_bytes, 'metadata': a.metadata_json,
             'created_at': str(a.created_at)} for a in arts]


async def link_evidence(artifact_id: int, object_type: str, object_id: int, relation_type: str = 'attached_to'):
    s = await get_session()
    link = EvidenceLink(artifact_id=artifact_id, object_type=object_type,
                        object_id=object_id, relation_type=relation_type)
    s.add(link); await s.flush()
    lid = link.id; await s.commit(); await s.close(); return lid


async def get_evidence_links(object_type: str = None, object_id: int = None, limit: int = 50):
    s = await get_session()
    q = select(EvidenceLink).order_by(desc(EvidenceLink.created_at)).limit(limit)
    if object_type: q = q.where(EvidenceLink.object_type == object_type)
    if object_id: q = q.where(EvidenceLink.object_id == object_id)
    result = await s.execute(q)
    links = result.scalars().all(); await s.close()
    return [{'id': l.id, 'artifact_id': l.artifact_id, 'object_type': l.object_type,
             'object_id': l.object_id, 'relation_type': l.relation_type,
             'created_at': str(l.created_at)} for l in links]

# ── 回归 ──

async def save_regression(project_id: int, run_name: str, status: str, passed: int, failed: int,
                          skipped: int, total: int, duration: float, results: dict):
    """**Legacy / 无调用方** —— 回归趋势现在由 `TrendDatabase` 写主库 `runs`。

    保留函数是为了外部脚本不突然 ImportError；新代码不要调用它。
    """
    s = await get_session()
    r = RegressionRecord(project_id=project_id, run_name=run_name, status=status,
                         pass_count=passed, fail_count=failed, skip_count=skipped,
                         total_count=total, duration_seconds=duration, results_json=results)
    s.add(r); await s.commit(); await s.close()

def _trend_rows(limit: int = 20):
    """从主库的 `runs` 表读回归历史（`TrendDatabase` 写的唯一真相）。

    读不到表/库（老库、独立运行）时返回空，让调用方回退到 ORM。
    """
    try:
        conn = sqlite3.connect(str(MAIN_DB))
        try:
            return conn.execute(
                "SELECT id, timestamp, total, pass, fail, unknown, pass_rate,"
                " total_time, root_dir FROM runs ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),)).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return []


def _hhmmss_seconds(text: str) -> float:
    try:
        h, m, s = str(text or "0:0:0").split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (TypeError, ValueError):
        return 0.0


async def get_regression_history(project_id: int = None, limit: int = 20):
    # **统一口径**：趋势/历史都读主库 `runs`（TrendDatabase 写的）。
    rows = _trend_rows(limit)
    if rows:
        return [{'id': r[0], 'run_name': r[8] or f"run-{r[0]}",
                 'status': 'completed', 'pass_count': r[3],
                 'fail_count': r[4], 'skip_count': r[5],
                 'total_count': r[2], 'duration_seconds': _hhmmss_seconds(r[7]),
                 'created_at': r[1], 'pass_rate': r[6]} for r in rows]
    # 回退：老库只有 ORM `regression_records`
    s = await get_session()
    q = select(RegressionRecord).order_by(desc(RegressionRecord.created_at)).limit(limit)
    if project_id: q = q.where(RegressionRecord.project_id == project_id)
    result = await s.execute(q)
    runs = result.scalars().all(); await s.close()
    return [{'id': r.id, 'run_name': r.run_name, 'status': r.status,
             'pass_count': r.pass_count, 'fail_count': r.fail_count,
             'skip_count': r.skip_count, 'total_count': r.total_count,
             'duration_seconds': r.duration_seconds, 'created_at': str(r.created_at)} for r in runs]

async def get_regression_trend(project_id: int = None, days: int = 7):
    """回归通过率趋势 —— 统一读主库 `runs`（与 `TrendDatabase` 同源）。"""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    try:
        conn = sqlite3.connect(str(MAIN_DB))
        try:
            rows = conn.execute(
                "SELECT timestamp, total, pass, pass_rate FROM runs"
                " WHERE timestamp >= ? ORDER BY timestamp", (cutoff,)).fetchall()
        finally:
            conn.close()
        if rows:
            return [{'date': str(r[0])[:10], 'pass_rate': r[3],
                     'passed': r[2], 'total': r[1]} for r in rows]
    except (sqlite3.Error, OSError):
        pass
    # 回退：老库只有 ORM `regression_records`
    s = await get_session()
    q = select(RegressionRecord).where(
        RegressionRecord.created_at >= datetime.now() - timedelta(days=days)
    ).order_by(RegressionRecord.created_at)
    if project_id: q = q.where(RegressionRecord.project_id == project_id)
    result = await s.execute(q)
    runs = result.scalars().all(); await s.close()
    trend = []
    for r in runs:
        rate = round(r.pass_count / max(r.total_count, 1) * 100, 1)
        trend.append({'date': str(r.created_at)[:10], 'pass_rate': rate,
                      'passed': r.pass_count, 'total': r.total_count})
    return trend

# ── 仪表盘统计 ──

async def get_dashboard_stats(project_id: int = None):
    s = await get_session()
    # 需求总数（从 signoff summary 估算）
    signoff_count = (await s.execute(select(func.count(Signoff.id)))).scalar() or 0
    # 回归统计
    reg_count = (await s.execute(select(func.count(RegressionRecord.id)))).scalar() or 0
    last_reg = (await s.execute(
        select(RegressionRecord).order_by(desc(RegressionRecord.created_at)).limit(1)
    )).scalar_one_or_none()
    # 流水线统计
    pipeline_count = (await s.execute(select(func.count(PipelineRun.id)))).scalar() or 0
    await s.close()
    return {
        'total_regressions': reg_count,
        'total_pipelines': pipeline_count,
        'total_signoffs': signoff_count,
        'last_regression': {
            'pass_rate': round(last_reg.pass_count / max(last_reg.total_count, 1) * 100, 1),
            'passed': last_reg.pass_count, 'total': last_reg.total_count,
        } if last_reg else None,
    }
