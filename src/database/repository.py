"""数据访问层 —— 企业级 CRUD"""
from sqlalchemy import select, desc, func, delete
from src.database.connection import get_session
from src.database.models import (
    TaskRecord, PipelineRun, User, Project, ProjectMember,
    AuditLog, KnowledgeEntry, Signoff, RegressionRecord,
    DocDocument, DocVersion, DocRequirement, DocRelation,
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

async def get_signoff_by_id(sid: int):
    """获取单条签核记录"""
    s = await get_session()
    sf = (await s.execute(select(Signoff).where(Signoff.id == sid))).scalar_one_or_none()
    if sf:
        result = {"id": sf.id, "project_id": sf.project_id, "title": sf.title,
                  "report_type": sf.report_type, "status": sf.status,
                  "summary": sf.summary_json, "requester_id": sf.requester_id,
                  "approver_id": sf.approver_id, "comment": sf.comment,
                  "created_at": str(sf.created_at), "updated_at": str(sf.updated_at)}
        await s.close(); return result
    await s.close(); return None

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
                           req_id: str = '', tags: str = '', limit: int = 50) -> list[dict]:
    """全文搜索文档"""
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
            q = q.where(DocDocument.id.in_(doc_ids))
        q = q.order_by(desc(DocDocument.updated_at)).limit(limit)
        docs = (await s.execute(q)).scalars().all()
        return [{'id': d.id, 'path': d.path, 'title': d.title, 'level': d.level,
                 'status': d.status, 'tags': d.tags, 'updated_at': str(d.updated_at)} for d in docs]
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
