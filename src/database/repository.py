"""数据访问层 —— 企业级 CRUD"""
from sqlalchemy import select, desc, func, delete
from src.database.connection import get_session
from src.database.models import (
    TaskRecord, PipelineRun, User, Project, ProjectMember,
    AuditLog, KnowledgeEntry, Signoff, SignoffEvent,
    Artifact, EvidenceLink, RegressionRecord,
    DocDocument, DocVersion, DocRequirement, DocRelation,
    PPAMetric, PPACorner, PPAConstraint, RoleWorkflowBinding,
)
import hashlib
import re
from datetime import datetime
from typing import Any

# ── 原有 ──

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
    s = await get_session()
    r = RegressionRecord(project_id=project_id, run_name=run_name, status=status,
                         pass_count=passed, fail_count=failed, skip_count=skipped,
                         total_count=total, duration_seconds=duration, results_json=results)
    s.add(r); await s.commit(); await s.close()

async def get_regression_history(project_id: int = None, limit: int = 20):
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
    """回归通过率趋势"""
    s = await get_session()
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=days)
    q = select(RegressionRecord).where(RegressionRecord.created_at >= cutoff).order_by(RegressionRecord.created_at)
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

# ═══════════════════════════════════════════
# MD 文档生态系统
# ═══════════════════════════════════════════

_RE_REQUIREMENT = re.compile(r'\*\*(REQ_\w+)\*\*\s*[:：]?\s*(.*?)(?=\n|$|\*\*)')


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _classify_requirement(req_id: str) -> str:
    if '_BT_' in req_id:
        return 'BT'
    if '_UT_' in req_id:
        return 'UT'
    if '_CHIP_' in req_id:
        return 'CHIP'
    if '_PERF_' in req_id:
        return 'PERF'
    return 'GEN'


def _parse_dsa_spec(content: str) -> dict[str, Any]:
    """解析一种简化的 DSA 风格规格文档。

    设计目标：
    - 以结构化字段为主，便于 Python 解析和后续工具链消费
    - 兼容现有 Markdown 规格的需求提取能力
    - 面向 Agent / 测试 / 数据库写入场景
    """
    lines = [line.rstrip() for line in content.splitlines()]
    result: dict[str, Any] = {
        'title': '',
        'version': '',
        'description': '',
        'requirements': [],
        'interfaces': [],
        'raw': content,
    }

    if not content.strip():
        return result

    current_req: dict[str, Any] | None = None
    current_iface: dict[str, Any] | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('TITLE:'):
            result['title'] = stripped.split(':', 1)[1].strip()
        elif stripped.startswith('VERSION:'):
            result['version'] = stripped.split(':', 1)[1].strip()
        elif stripped.startswith('DESCRIPTION:'):
            result['description'] = stripped.split(':', 1)[1].strip()
        elif stripped.startswith('- ID:'):
            req = {'req_id': '', 'description': '', 'req_type': 'GEN', 'line_number': i + 1}
            m = re.match(r'-\s*ID:\s*(REQ_\S+)', stripped)
            if m:
                req['req_id'] = m.group(1)
                req['req_type'] = _classify_requirement(req['req_id'])
            current_req = req
            result['requirements'].append(req)
        elif stripped.startswith('- NAME:'):
            iface = {'name': '', 'type': '', 'offset': '', 'width': '', 'access': '', 'desc': '', 'line_number': i + 1}
            m = re.match(r'-\s*NAME:\s*(\S+)', stripped)
            if m:
                iface['name'] = m.group(1)
            current_iface = iface
            result['interfaces'].append(iface)
        elif current_req is not None and stripped.startswith('LEVEL:'):
            current_req['req_type'] = stripped.split(':', 1)[1].strip().upper()
        elif current_req is not None and stripped.startswith('DESC:'):
            current_req['description'] = stripped.split(':', 1)[1].strip()
        elif current_iface is not None and stripped.startswith('TYPE:'):
            current_iface['type'] = stripped.split(':', 1)[1].strip()
        elif current_iface is not None and stripped.startswith('OFFSET:'):
            current_iface['offset'] = stripped.split(':', 1)[1].strip()
        elif current_iface is not None and stripped.startswith('WIDTH:'):
            current_iface['width'] = stripped.split(':', 1)[1].strip()
        elif current_iface is not None and stripped.startswith('ACCESS:'):
            current_iface['access'] = stripped.split(':', 1)[1].strip()
        elif current_iface is not None and stripped.startswith('DESC:'):
            current_iface['desc'] = stripped.split(':', 1)[1].strip()

    # 兼容单行的 REQUIREMENTS / INTERFACES 结构；若字段后续跟随缩进块，则补充解析
    for req in result['requirements']:
        if not req['description']:
            req['description'] = ''

    return result


def _extract_requirements(content: str) -> list:
    """从 Markdown 或 DSA 风格内容提取所有需求条目。"""
    if not content:
        return []

    dsa_spec = _parse_dsa_spec(content)
    if dsa_spec['requirements']:
        return [
            {
                'req_id': r['req_id'],
                'description': r['description'] or '',
                'req_type': r['req_type'],
                'line_number': r['line_number'],
            }
            for r in dsa_spec['requirements']
        ]

    reqs = []
    for i, line in enumerate(content.split('\n'), 1):
        m = _RE_REQUIREMENT.search(line)
        if m:
            req_id = m.group(1)
            desc = m.group(2).strip()
            reqs.append({
                'req_id': req_id,
                'description': desc,
                'req_type': _classify_requirement(req_id),
                'line_number': i,
            })
    return reqs

# ── 文档 CRUD ──

async def create_document(project_id: int, path: str, title: str, content: str,
                          author_id: int, level: str = 'module', tags: str = '') -> int:
    """创建新文档，同时解析需求条目"""
    s = await get_session()
    try:
        content_hash = _hash_content(content)
        doc = DocDocument(
            project_id=project_id, path=path, title=title, content=content,
            content_hash=content_hash, level=level, author_id=author_id, tags=tags
        )
        s.add(doc)
        await s.flush()

        v = DocVersion(document_id=doc.id, version='1.0', content=content,
                       content_hash=content_hash, change_summary='初始创建', author_id=author_id)
        s.add(v)

        for r in _extract_requirements(content):
            s.add(DocRequirement(document_id=doc.id, **r))

        await s.commit()
        return doc.id
    finally:
        await s.close()

async def update_document(doc_id: int, content: str, author_id: int,
                          change_summary: str = '') -> int:
    """更新文档内容，自动创建新版本，重新提取需求"""
    s = await get_session()
    try:
        doc = (await s.execute(select(DocDocument).where(DocDocument.id == doc_id))).scalar_one_or_none()
        if not doc:
            return 0

        new_hash = _hash_content(content)
        if new_hash == doc.content_hash:
            return doc.id

        doc.content = content
        doc.content_hash = new_hash
        doc.updated_at = datetime.now()

        last_v = (await s.execute(
            select(DocVersion).where(DocVersion.document_id == doc_id).order_by(desc(DocVersion.id)).limit(1)
        )).scalar_one_or_none()
        ver_num = int(last_v.version.split('.')[0]) + 1 if last_v else 2
        s.add(DocVersion(document_id=doc_id, version=f'{ver_num}.0', content=content,
                         content_hash=new_hash, change_summary=change_summary, author_id=author_id))

        await s.execute(delete(DocRequirement).where(DocRequirement.document_id == doc_id))
        for r in _extract_requirements(content):
            s.add(DocRequirement(document_id=doc_id, **r))

        await s.commit()
        return doc.id
    finally:
        await s.close()

async def get_document(doc_id: int) -> dict | None:
    """获取单个文档及其版本历史和需求列表"""
    s = await get_session()
    try:
        doc = (await s.execute(select(DocDocument).where(DocDocument.id == doc_id))).scalar_one_or_none()
        if not doc:
            return None
        versions = (await s.execute(
            select(DocVersion).where(DocVersion.document_id == doc_id).order_by(desc(DocVersion.id))
        )).scalars().all()
        requirements = (await s.execute(
            select(DocRequirement).where(DocRequirement.document_id == doc_id)
        )).scalars().all()
        return {
            'id': doc.id, 'path': doc.path, 'title': doc.title, 'content': doc.content,
            'content_hash': doc.content_hash, 'level': doc.level, 'status': doc.status,
            'tags': doc.tags, 'metadata_json': doc.metadata_json, 'view_count': doc.view_count,
            'created_at': str(doc.created_at), 'updated_at': str(doc.updated_at),
            'versions': [{'id': v.id, 'version': v.version, 'change_summary': v.change_summary,
                          'created_at': str(v.created_at)} for v in versions],
            'requirements': [{'req_id': r.req_id, 'description': r.description,
                              'req_type': r.req_type, 'line_number': r.line_number,
                              'is_covered': r.is_covered} for r in requirements],
        }
    finally:
        await s.close()

async def search_documents(project_id: int = None, level: str = None, keyword: str = '',
                           req_id: str = '', tags: str = '', limit: int = 50) -> dict:
    """全文搜索文档，返回 docs 列表 + count"""
    s = await get_session()
    try:
        q = select(DocDocument)
        if project_id:
            q = q.where(DocDocument.project_id == project_id)
        if level:
            q = q.where(DocDocument.level == level)
        if keyword:
            q = q.where(DocDocument.content.contains(keyword))
        if tags:
            q = q.where(DocDocument.tags.contains(tags))
        if req_id:
            doc_ids = (await s.execute(
                select(DocRequirement.document_id).where(DocRequirement.req_id == req_id)
            )).scalars().all()
            if doc_ids:
                q = q.where(DocDocument.id.in_(doc_ids))
            else:
                return {"docs": [], "count": 0}
        q = q.order_by(desc(DocDocument.updated_at)).limit(limit)
        docs = (await s.execute(q)).scalars().all()

        # 批量查询每个文档的需求数量
        doc_ids = [d.id for d in docs]
        req_counts = {}
        if doc_ids:
            from sqlalchemy import func
            req_rows = (await s.execute(
                select(DocRequirement.document_id, func.count(DocRequirement.id))
                .where(DocRequirement.document_id.in_(doc_ids))
                .group_by(DocRequirement.document_id)
            )).all()
            req_counts = {row[0]: row[1] for row in req_rows}

        return {"docs": [{
            'id': d.id, 'path': d.path, 'title': d.title, 'level': d.level,
            'status': d.status, 'tags': d.tags, 'updated_at': str(d.updated_at),
            'created_at': str(d.created_at),
            'size': len(d.content) if d.content else 0,
            'req_count': req_counts.get(d.id, 0),
        } for d in docs], "count": len(docs)}
    finally:
        await s.close()

async def list_all_documents(project_id: int = None) -> list[dict]:
    """列出所有文档（简要信息）"""
    s = await get_session()
    try:
        q = select(DocDocument).order_by(DocDocument.path)
        if project_id:
            q = q.where(DocDocument.project_id == project_id)
        docs = (await s.execute(q)).scalars().all()
        return [{'id': d.id, 'path': d.path, 'title': d.title, 'level': d.level,
                 'status': d.status, 'tags': d.tags, 'req_count': 0,
                 'updated_at': str(d.updated_at)} for d in docs]
    finally:
        await s.close()

# ── 需求查询 ──

async def get_requirement_trace(req_id: str) -> dict | None:
    """需求追溯：哪个文档定义 → 覆盖状态"""
    s = await get_session()
    try:
        req = (await s.execute(
            select(DocRequirement).where(DocRequirement.req_id == req_id)
        )).scalar_one_or_none()
        if not req:
            return None
        doc = (await s.execute(
            select(DocDocument).where(DocDocument.id == req.document_id)
        )).scalar_one()
        return {
            'req_id': req.req_id, 'description': req.description, 'req_type': req.req_type,
            'is_covered': req.is_covered, 'coverage_json': req.coverage_json,
            'source_doc': {'id': doc.id, 'path': doc.path, 'title': doc.title}
        }
    finally:
        await s.close()

async def list_all_requirements(project_id: int = None) -> list[dict]:
    """列出所有需求"""
    s = await get_session()
    try:
        q = select(DocRequirement)
        if project_id:
            doc_ids = (await s.execute(
                select(DocDocument.id).where(DocDocument.project_id == project_id)
            )).scalars().all()
            q = q.where(DocRequirement.document_id.in_(doc_ids))
        reqs = (await s.execute(q.order_by(DocRequirement.req_id))).scalars().all()
        return [{'id': r.id, 'req_id': r.req_id, 'description': r.description,
                 'req_type': r.req_type, 'document_id': r.document_id,
                 'is_covered': r.is_covered} for r in reqs]
    finally:
        await s.close()

# ── 关系管理 ──

async def link_documents(source_id: int, target_id: int,
                         relation_type: str = 'parent', description: str = '') -> int:
    s = await get_session()
    try:
        r = DocRelation(source_id=source_id, target_id=target_id,
                       relation_type=relation_type, description=description)
        s.add(r)
        await s.commit()
        return r.id
    finally:
        await s.close()

async def get_document_tree(project_id: int, root_path: str = None) -> list[dict]:
    """获取文档层级树"""
    s = await get_session()
    try:
        q = select(DocDocument).where(DocDocument.project_id == project_id)
        if root_path:
            q = q.where(DocDocument.path.like(f'{root_path}%'))
        docs = (await s.execute(q.order_by(DocDocument.path))).scalars().all()
        relations = (await s.execute(
            select(DocRelation).where(DocRelation.relation_type.in_(['parent', 'child']))
        )).scalars().all()

        child_of = {}
        for rel in relations:
            if rel.relation_type == 'parent':
                child_of.setdefault(rel.source_id, []).append(rel.target_id)

        doc_map = {d.id: d for d in docs}
        all_parent_ids = set()
        for children in child_of.values():
            all_parent_ids.update(children)

        def _build_node(doc):
            node = {'id': doc.id, 'path': doc.path, 'title': doc.title, 'level': doc.level}
            children = child_of.get(doc.id, [])
            if children:
                node['children'] = [_build_node(doc_map[c]) for c in children if c in doc_map]
            return node

        roots = [d for d in docs if d.id not in all_parent_ids]
        return [_build_node(d) for d in roots]
    finally:
        await s.close()

# ── 文件系统 ↔ DB 同步 ──

async def sync_fs_to_db(specs_dir: str, project_id: int, author_id: int) -> dict:
    """将文件系统中的 .md 文件同步到数据库"""
    import os
    specs_dir = os.path.abspath(specs_dir)
    result = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': []}
    for root, dirs, files in os.walk(specs_dir):
        for f in files:
            if not f.endswith('.md'):
                continue
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, specs_dir).replace('\\', '/')
            with open(full_path, 'r', encoding='utf-8') as fh:
                content = fh.read()
            title_match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else rel_path
            if 'combined' in rel_path:
                level = 'chip'
            elif rel_path.count('/') == 0:
                level = 'subsystem'
            else:
                level = 'module'

            s = await get_session()
            try:
                existing = (await s.execute(
                    select(DocDocument).where(DocDocument.path == rel_path)
                )).scalar_one_or_none()
                if existing:
                    new_hash = _hash_content(content)
                    if new_hash != existing.content_hash:
                        existing.content = content
                        existing.content_hash = new_hash
                        existing.title = title
                        existing.level = level
                        existing.updated_at = datetime.now()
                        await s.commit()
                        result['updated'] += 1
                    else:
                        result['skipped'] += 1
                else:
                    await s.close()
                    await create_document(project_id, rel_path, title, content, author_id, level)
                    result['created'] += 1
                    s = await get_session()  # 重新获取 session（create_document 已关闭）
            except Exception as e:
                result['errors'].append({'path': rel_path, 'error': str(e)})
            finally:
                await s.close()
    return result

# ═══════════════════════════════════════════════════════════
# PPA Signoff CRUD
# ═══════════════════════════════════════════════════════════

# ── PPA Metrics ──

async def create_ppa_metric(signoff_id: int, category: str, metric_name: str,
                            target_value: float = 0.0, actual_value: float = 0.0,
                            unit: str = '', pass_status: str = 'pending',
                            margin_pct: float = 0.0, source_file: str = '',
                            source_hash: str = '', notes: str = '') -> int:
    """创建单条 PPA 指标"""
    s = await get_session()
    m = PPAMetric(signoff_id=signoff_id, category=category, metric_name=metric_name,
                  target_value=target_value, actual_value=actual_value, unit=unit,
                  pass_status=pass_status, margin_pct=margin_pct,
                  source_file=source_file, source_hash=source_hash, notes=notes)
    s.add(m); await s.flush()
    mid = m.id; await s.commit(); await s.close()
    return mid


async def batch_create_ppa_metrics(metrics: list[dict]) -> list[int]:
    """批量创建 PPA 指标"""
    s = await get_session()
    ids = []
    for d in metrics:
        m = PPAMetric(
            signoff_id=d.get('signoff_id', 0), category=d.get('category', ''),
            metric_name=d.get('metric_name', ''),
            target_value=d.get('target_value', 0.0), actual_value=d.get('actual_value', 0.0),
            unit=d.get('unit', ''), pass_status=d.get('pass_status', 'pending'),
            margin_pct=d.get('margin_pct', 0.0), source_file=d.get('source_file', ''),
            source_hash=d.get('source_hash', ''), notes=d.get('notes', ''),
        )
        s.add(m); await s.flush()
        ids.append(m.id)
    await s.commit(); await s.close()
    return ids


async def get_ppa_metrics(signoff_id: int = None, category: str = None) -> list[dict]:
    """查询 PPA 指标，可按 signoff_id / category 过滤"""
    s = await get_session()
    q = select(PPAMetric).order_by(PPAMetric.category, PPAMetric.metric_name)
    if signoff_id: q = q.where(PPAMetric.signoff_id == signoff_id)
    if category: q = q.where(PPAMetric.category == category)
    result = await s.execute(q)
    rows = result.scalars().all(); await s.close()
    return [{'id': r.id, 'signoff_id': r.signoff_id, 'category': r.category,
             'metric_name': r.metric_name, 'target_value': r.target_value,
             'actual_value': r.actual_value, 'unit': r.unit,
             'pass_status': r.pass_status, 'margin_pct': r.margin_pct,
             'source_file': r.source_file, 'source_hash': r.source_hash,
             'notes': r.notes, 'created_at': str(r.created_at)} for r in rows]


async def update_ppa_metric(metric_id: int, **fields) -> bool:
    """更新单条 PPA 指标"""
    s = await get_session()
    m = (await s.execute(select(PPAMetric).where(PPAMetric.id == metric_id))).scalar_one_or_none()
    if not m:
        await s.close(); return False
    for k, v in fields.items():
        if hasattr(m, k): setattr(m, k, v)
    m.updated_at = datetime.now()
    await s.commit(); await s.close()
    return True


async def delete_ppa_metrics(signoff_id: int) -> int:
    """删除指定签核的所有 PPA 指标（重新导入前清理）"""
    s = await get_session()
    result = await s.execute(select(PPAMetric).where(PPAMetric.signoff_id == signoff_id))
    rows = result.scalars().all()
    count = len(rows)
    for r in rows: await s.delete(r)
    await s.commit(); await s.close()
    return count


# ── PPA Corners ──

async def create_ppa_corner(signoff_id: int, corner_name: str, **fields) -> int:
    """创建 PPA corner 记录"""
    s = await get_session()
    c = PPACorner(signoff_id=signoff_id, corner_name=corner_name)
    for k, v in fields.items():
        if hasattr(c, k): setattr(c, k, v)
    s.add(c); await s.flush()
    cid = c.id; await s.commit(); await s.close()
    return cid


async def get_ppa_corners(signoff_id: int) -> list[dict]:
    """获取签核的所有 PVT corner 数据"""
    s = await get_session()
    q = select(PPACorner).where(PPACorner.signoff_id == signoff_id).order_by(PPACorner.corner_name)
    result = await s.execute(q)
    rows = result.scalars().all(); await s.close()
    return [{'id': r.id, 'signoff_id': r.signoff_id, 'corner_name': r.corner_name,
             'pvt_desc': r.pvt_desc, 'total_power_mw': r.total_power_mw,
             'dynamic_power_mw': r.dynamic_power_mw, 'leakage_power_mw': r.leakage_power_mw,
             'fmax_mhz': r.fmax_mhz, 'setup_worst_ns': r.setup_worst_ns,
             'hold_worst_ns': r.hold_worst_ns, 'area_mm2': r.area_mm2,
             'cell_count': r.cell_count, 'utilization_pct': r.utilization_pct,
             'extra_json': r.extra_json, 'created_at': str(r.created_at)} for r in rows]


async def get_ppa_corner_summary(signoff_id: int) -> dict:
    """获取 PPA corner 聚合摘要（用于签核总览卡片）"""
    corners = await get_ppa_corners(signoff_id)
    if not corners:
        return {'corner_count': 0, 'best_power': {}, 'best_perf': {}, 'worst_power': {}, 'worst_perf': {}}
    best_power = min(corners, key=lambda c: c['total_power_mw'] or float('inf'))
    worst_power = max(corners, key=lambda c: c['total_power_mw'] or 0)
    best_perf = max(corners, key=lambda c: c['fmax_mhz'] or 0)
    worst_perf = min(corners, key=lambda c: c['fmax_mhz'] or float('inf'))
    return {
        'corner_count': len(corners),
        'corners': [c['corner_name'] for c in corners],
        'best_power': f"{best_power['total_power_mw']}mW @ {best_power['corner_name']}",
        'worst_power': f"{worst_power['total_power_mw']}mW @ {worst_power['corner_name']}",
        'best_perf': f"{best_perf['fmax_mhz']}MHz @ {best_perf['corner_name']}",
        'worst_perf': f"{worst_perf['fmax_mhz']}MHz @ {worst_perf['corner_name']}",
    }


# ── PPA Constraints ──

async def create_ppa_constraint(project_id: int, category: str, metric_name: str,
                                threshold_value: float, unit: str = '',
                                constraint_type: str = 'max', margin_required_pct: float = 10.0,
                                severity: str = 'P1', description: str = '',
                                created_by: int = None) -> int:
    """创建 PPA 门限规则"""
    s = await get_session()
    c = PPAConstraint(project_id=project_id, category=category, metric_name=metric_name,
                      threshold_value=threshold_value, unit=unit,
                      constraint_type=constraint_type, margin_required_pct=margin_required_pct,
                      severity=severity, description=description, created_by=created_by)
    s.add(c); await s.flush()
    cid = c.id; await s.commit(); await s.close()
    return cid


async def get_ppa_constraints(project_id: int = None, category: str = None) -> list[dict]:
    """查询 PPA 门限规则"""
    s = await get_session()
    q = select(PPAConstraint).where(PPAConstraint.is_active == True).order_by(PPAConstraint.category, PPAConstraint.metric_name)
    if project_id: q = q.where(PPAConstraint.project_id == project_id)
    if category: q = q.where(PPAConstraint.category == category)
    result = await s.execute(q)
    rows = result.scalars().all(); await s.close()
    return [{'id': r.id, 'project_id': r.project_id, 'category': r.category,
             'metric_name': r.metric_name, 'constraint_type': r.constraint_type,
             'threshold_value': r.threshold_value, 'unit': r.unit,
             'margin_required_pct': r.margin_required_pct, 'severity': r.severity,
             'description': r.description, 'created_at': str(r.created_at)} for r in rows]


async def update_ppa_constraint(constraint_id: int, **fields) -> bool:
    """更新 PPA 门限规则"""
    s = await get_session()
    c = (await s.execute(select(PPAConstraint).where(PPAConstraint.id == constraint_id))).scalar_one_or_none()
    if not c:
        await s.close(); return False
    for k, v in fields.items():
        if hasattr(c, k): setattr(c, k, v)
    c.updated_at = datetime.now()
    await s.commit(); await s.close()
    return True


async def get_ppa_signoff_summary(signoff_id: int) -> dict:
    """获取签核的 PPA 综合摘要 — 指标 + corner 聚合"""
    metrics = await get_ppa_metrics(signoff_id)
    corners = await get_ppa_corner_summary(signoff_id)

    by_category = {}
    for m in metrics:
        by_category.setdefault(m['category'], []).append(m)

    summary = {'signoff_id': signoff_id, 'total_metrics': len(metrics),
               'categories': {}, 'corners': corners, 'overall_pass': True}
    for cat, items in by_category.items():
        passed = sum(1 for i in items if i['pass_status'] == 'pass')
        failed = sum(1 for i in items if i['pass_status'] == 'fail')
        marginal = sum(1 for i in items if i['pass_status'] == 'marginal')
        summary['categories'][cat] = {
            'total': len(items), 'passed': passed, 'failed': failed, 'marginal': marginal,
            'all_pass': failed == 0 and marginal == 0,
            'items': items,
        }
        if failed > 0 or marginal > 0:
            summary['overall_pass'] = False

    return summary


# ═══════════════════════════════════════════════════════════
# 角色→工作流绑定 (Role-Workflow Binding)
# ═══════════════════════════════════════════════════════════

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
