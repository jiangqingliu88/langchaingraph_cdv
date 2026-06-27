"""数据访问层 —— 企业级 CRUD"""
from sqlalchemy import select, desc, func
from src.database.connection import get_session
from src.database.models import (
    TaskRecord, PipelineRun, User, Project, ProjectMember,
    AuditLog, KnowledgeEntry, Signoff, RegressionRecord
)

# ── 原有 ──

async def save_task(role, ttype, inp, out, status, error=None, extime=0):
    s = await get_session()
    r = TaskRecord(agent_role=role, task_type=ttype, input_text=str(inp)[:5000],
                   output_text=str(out)[:10000], status=status, error_msg=error,
                   execution_time=extime)
    s.add(r); await s.commit(); await s.close()

async def save_pipeline_run(wf, spec, total, passed, degraded, ttime, results):
    s = await get_session()
    r = PipelineRun(workflow=wf, spec_file=spec, total_phases=total, passed=passed,
                    degraded=degraded, total_time=ttime, results=results)
    s.add(r); await s.commit(); await s.close()

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

async def add_audit_log(user_id: int, username: str, action: str, resource: str = "", detail: str = "", ip: str = ""):
    s = await get_session()
    a = AuditLog(user_id=user_id, username=username, action=action, resource=resource, detail=detail, ip_address=ip)
    s.add(a); await s.commit(); await s.close()

async def get_audit_logs(limit: int = 50, project_id: str = None):
    s = await get_session()
    q = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    if project_id: q = q.where(AuditLog.resource == project_id)
    result = await s.execute(q)
    logs = result.scalars().all(); await s.close()
    return [{'id': l.id, 'username': l.username, 'action': l.action,
             'resource': l.resource, 'detail': l.detail,
             'created_at': str(l.created_at)} for l in logs]

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

async def create_signoff(project_id: int, title: str, report_type: str, summary: dict, requester_id: int):
    s = await get_session()
    sf = Signoff(project_id=project_id, title=title, report_type=report_type,
                 summary_json=summary, requester_id=requester_id, status='pending')
    s.add(sf); await s.flush()
    sid = sf.id; await s.commit(); await s.close(); return sid

async def list_signoffs(project_id: int = None, limit: int = 20):
    s = await get_session()
    q = select(Signoff).order_by(desc(Signoff.created_at)).limit(limit)
    if project_id: q = q.where(Signoff.project_id == project_id)
    result = await s.execute(q)
    sfs = result.scalars().all(); await s.close()
    return [{'id': sf.id, 'project_id': sf.project_id, 'title': sf.title,
             'report_type': sf.report_type, 'status': sf.status,
             'summary': sf.summary_json, 'comment': sf.comment,
             'created_at': str(sf.created_at)} for sf in sfs]

async def update_signoff(sid: int, status: str, approver_id: int = None, comment: str = ""):
    s = await get_session()
    sf = (await s.execute(select(Signoff).where(Signoff.id == sid))).scalar_one_or_none()
    if sf:
        sf.status = status
        if approver_id: sf.approver_id = approver_id
        if comment: sf.comment = comment
        sf.updated_at = __import__('datetime').datetime.now()
        await s.commit()
    await s.close(); return sf is not None

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
