"""数据访问层 —— 企业级 CRUD（Phase 4 按领域拆分）。"""
from __future__ import annotations

from sqlalchemy import select, desc, func, delete
from src.layers.l4_memory.persistence.connection import get_session
from src.layers.l4_memory.persistence.models import (
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

        doc_id = doc.id  # capture before commit to avoid MissingGreenlet on expired instance

        v = DocVersion(document_id=doc_id, version='1.0', content=content,
                       content_hash=content_hash, change_summary='初始创建', author_id=author_id)
        s.add(v)

        for r in _extract_requirements(content):
            s.add(DocRequirement(document_id=doc_id, **r))

        await s.commit()
        return doc_id
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

        result_id = doc.id  # capture before commit to avoid MissingGreenlet
        await s.commit()
        return result_id
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
