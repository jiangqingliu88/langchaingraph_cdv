"""
Document routes — MD 规格文档管理 + 结构化编辑器 + v2 文档生态 API
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, desc, func

from src.core.auth import require_auth, require_admin, get_current_user
from src.database import repository
from src.database.connection import get_session
from src.database.models import DocVersion, DocRequirement

# ── 请求模型 ──
from pydantic import BaseModel, Field


class DocCreateRequest(BaseModel):
    project_id: int
    path: str
    title: str
    content: str
    level: str = 'module'
    tags: str = ''


class DocUpdateRequest(BaseModel):
    content: str
    change_summary: str = ''


class DocLinkRequest(BaseModel):
    source_id: int
    target_id: int
    relation_type: str = 'parent'
    description: str = ''


# These are set by api.py when registering the router
router = APIRouter(prefix="/api", tags=["docs"])

# ── Path helpers (will be set from api.py) ──
_specs_dir: Path | None = None
_max_document_bytes: int = 2 * 1024 * 1024


def configure(specs_dir: Path, max_document_bytes: int = 2 * 1024 * 1024):
    """Called by api.py to inject workspace-dependent configuration."""
    global _specs_dir, _max_document_bytes
    _specs_dir = specs_dir
    _max_document_bytes = max_document_bytes


def _resolve_spec_path(value: str) -> Path:
    path = Path(value)
    if path.parts and path.parts[0].lower() == "specs":
        path = Path(*path.parts[1:])
    candidate = Path(value)
    if candidate.is_absolute():
        raise HTTPException(status_code=400, detail="absolute paths are not allowed")
    resolved = (_specs_dir / path).resolve()
    if not resolved.is_relative_to(_specs_dir):
        raise HTTPException(status_code=403, detail="path is outside the allowed workspace")
    if resolved.suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="unsupported file type")
    return resolved


# ═══════════════════════════════════════════════════════════
# 结构化文档编辑器 API
# ═══════════════════════════════════════════════════════════

@router.get("/editor/{path:path}")
async def editor_load(path: str):
    """加载文档为结构化 JSON（供编辑器使用）"""
    fp = _resolve_spec_path(path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    md_text = fp.read_text(encoding="utf-8")
    from src.core.doc_serializer import DocumentSerializer
    serializer = DocumentSerializer()
    doc = serializer.md_to_doc(md_text)
    return {"path": str(fp.relative_to(_specs_dir)), "doc": doc.to_dict(), "md_raw": md_text}


@router.post("/editor/{path:path}")
async def editor_save(path: str, payload: dict, user: dict = Depends(require_auth)):
    """保存结构化 JSON → 渲染 MD → 写回文件 — 仅经理可编辑"""
    role = user.get("role", "")
    if role not in ("admin", "verification_manager"):
        raise HTTPException(status_code=403, detail="仅 SignOff 经理可以编辑规格文档")
    try:
        from src.core.doc_serializer import DocumentSerializer, StructuredDocument
        serializer = DocumentSerializer()

        if "doc" in payload:
            doc = StructuredDocument.from_dict(payload["doc"])
        else:
            doc = serializer.md_to_doc(payload.get("md_raw", ""))

        md_text = serializer.doc_to_md(doc)
        fp = _resolve_spec_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(md_text, encoding="utf-8")

        try:
            await repository.add_audit_log(user["user_id"], user["username"], "doc_editor_save",
                                           str(fp.relative_to(_specs_dir)),
                                           f"requirements={len(doc.requirements)} interfaces={len(doc.interfaces)}")
        except Exception:
            pass

        return {"ok": True, "path": str(fp.relative_to(_specs_dir)), "md": md_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Editor save failed: {str(e)}")


# ═══════════════════════════════════════════════════════════
# 文档库 —— MD 规格文档管理（旧版文件系统 API）
# ═══════════════════════════════════════════════════════════

@router.get("/docs")
async def list_docs(user: dict = Depends(get_current_user)):
    """列出规格文档 — 经理看全部，工程师只看已分配模块的文档"""
    role = user.get("role", "") if user else ""
    user_id = user.get("user_id", 0) if user else 0

    # 工程师只看分配模块的文档
    allowed_dirs = None
    if role not in ("admin", "verification_manager", ""):
        try:
            projects = await repository.list_projects(user_id)
            allowed_dirs = {p["name"] for p in projects}
        except Exception:
            allowed_dirs = set()

    docs = []
    if _specs_dir.exists():
        for f in sorted(_specs_dir.glob("**/*.md")):
            content = f.read_text(encoding="utf-8")
            title = f.stem
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            linked_reqs = []
            for line in content.split("\n"):
                if "**REQ_" in line:
                    for m in re.findall(r'REQ_\w+', line):
                        if m not in linked_reqs:
                            linked_reqs.append(m)
            parent_dir = f.parent.name if f.parent != _specs_dir else ""
            if allowed_dirs is not None and parent_dir and parent_dir not in allowed_dirs:
                continue

            rel = str(f.relative_to(_specs_dir)).replace("\\", "/")
            docs.append({
                "path": str(f),
                "name": f.name,
                "rel_path": rel,
                "title": title,
                "size": len(content),
                "linked_reqs": linked_reqs,
                "req_count": len(linked_reqs),
                "modified": f.stat().st_mtime,
            })
    return {"docs": docs, "count": len(docs)}


@router.get("/docs/{path:path}")
async def read_doc(path: str):
    """读取单个规格文档"""
    fp = _resolve_spec_path(path)
    if not fp.exists():
        raise HTTPException(status_code=404, detail="文档不存在")
    content = fp.read_text(encoding="utf-8")
    req_ids = list(set(re.findall(r'\*\*REQ_\w+\*\*', content)))
    return {"path": str(fp), "name": fp.name, "content": content,
            "lines": len(content.split("\n")), "linked_reqs": req_ids}


@router.post("/docs/{path:path}")
async def write_doc(path: str, content: str = "", user: dict = Depends(require_auth)):
    """保存规格文档 — 文件系统 + SQL 双写 + 版本历史"""
    role = user.get("role", "")
    if role not in ("admin", "verification_manager"):
        raise HTTPException(status_code=403, detail="仅 SignOff 经理可以编辑规格文档")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    if len(content.encode("utf-8")) > _max_document_bytes:
        raise HTTPException(status_code=413, detail="document too large")
    fp = _resolve_spec_path(path)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")

    # 同步到 SQL 文档生态 + 版本历史
    try:
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        existing = await repository.search_documents(keyword=fp.stem, limit=1)
        if existing and len(existing.get("docs", [])) > 0:
            doc = existing["docs"][0]
            await repository.update_document(doc["id"], content, user["user_id"], f"保存于 {fp.name}")
        else:
            title = fp.stem
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            await repository.create_document(0, str(fp.relative_to(_specs_dir)), title, content, user["user_id"])
    except Exception:
        pass

    try:
        await repository.add_audit_log(user["user_id"], user["username"], "doc_save", str(fp))
    except Exception:
        pass
    return {"ok": True, "path": str(fp)}


# ═══════════════════════════════════════════════════════════
# 文档生态 API v2 —— SQL 后端
# ═══════════════════════════════════════════════════════════

@router.post("/v2/docs")
async def v2_create_doc(req: DocCreateRequest, current_user=Depends(require_auth)):
    doc_id = await repository.create_document(
        req.project_id, req.path, req.title, req.content, current_user['id'], req.level, req.tags
    )
    await repository.add_audit_log(current_user['id'], current_user.get('username', ''), 'doc.create',
                                   f'doc/{doc_id}', f'创建文档: {req.path}')
    return {"id": doc_id, "status": "created"}


@router.put("/v2/docs/{doc_id}")
async def v2_update_doc(doc_id: int, req: DocUpdateRequest, current_user=Depends(require_auth)):
    result = await repository.update_document(doc_id, req.content, current_user['id'], req.change_summary)
    if result == 0:
        raise HTTPException(status_code=404, detail="文档不存在")
    await repository.add_audit_log(current_user['id'], current_user.get('username', ''), 'doc.update',
                                   f'doc/{doc_id}', f'更新文档: {req.change_summary}')
    return {"id": result, "status": "updated"}


@router.get("/v2/docs/{doc_id}")
async def v2_get_doc(doc_id: int):
    doc = await repository.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.get("/v2/docs")
async def v2_search_docs(project_id: int = None, level: str = None, keyword: str = '',
                          req_id: str = '', tags: str = '', limit: int = 50):
    return await repository.search_documents(project_id, level, keyword, req_id, tags, limit)


@router.get("/v2/docs/{doc_id}/versions")
async def v2_get_versions(doc_id: int):
    """获取文档的版本历史"""
    s = await get_session()
    rows = (await s.execute(
        select(DocVersion).where(DocVersion.document_id == doc_id)
        .order_by(desc(DocVersion.created_at)).limit(20)
    )).scalars().all()
    versions = [{"id": r.id, "version": r.version, "content_hash": r.content_hash,
                 "change_summary": r.change_summary, "created_at": str(r.created_at),
                 "author_id": r.author_id} for r in rows]
    await s.close()
    return {"doc_id": doc_id, "versions": versions, "count": len(versions)}


@router.get("/v2/docs/{doc_id}/versions/{version_id}")
async def v2_get_version_content(doc_id: int, version_id: int):
    """获取特定版本的内容"""
    s = await get_session()
    v = (await s.execute(
        select(DocVersion).where(DocVersion.id == version_id, DocVersion.document_id == doc_id)
    )).scalar_one_or_none()
    await s.close()
    if not v:
        raise HTTPException(status_code=404, detail="版本不存在")
    return {"id": v.id, "version": v.version, "content": v.content, "content_hash": v.content_hash,
            "change_summary": v.change_summary, "created_at": str(v.created_at)}


@router.post("/v2/docs/{doc_id}/versions/{version_id}/restore")
async def v2_restore_version(doc_id: int, version_id: int, current_user=Depends(require_auth)):
    """回退文档到指定版本"""
    s = await get_session()
    v = (await s.execute(
        select(DocVersion).where(DocVersion.id == version_id, DocVersion.document_id == doc_id)
    )).scalar_one_or_none()
    await s.close()
    if not v:
        raise HTTPException(status_code=404, detail="版本不存在")
    result = await repository.update_document(doc_id, v.content, current_user['id'],
                                               f"回退到版本 {v.version}")
    if result == 0:
        raise HTTPException(status_code=404, detail="文档不存在")
    await repository.add_audit_log(current_user['id'], current_user.get('username', ''), 'doc.restore',
                                   f'doc/{doc_id}', f'回退到版本 {v.version}')
    return {"id": result, "status": "restored", "version": v.version}


# ── 需求追踪 v2 ──

@router.get("/v2/requirements/{req_id}")
async def v2_get_req_trace(req_id: str):
    r = await repository.get_requirement_trace(req_id)
    if not r:
        raise HTTPException(status_code=404, detail="需求 ID 不存在")
    return r


@router.get("/v2/requirements")
async def v2_list_requirements(project_id: int = None):
    return {"requirements": await repository.list_all_requirements(project_id)}


# ── 文档链接 & 文档树 ──

@router.post("/v2/docs/links")
async def v2_link_docs(req: DocLinkRequest, current_user=Depends(require_auth)):
    link_id = await repository.link_documents(req.source_id, req.target_id, req.relation_type, req.description)
    await repository.add_audit_log(current_user['id'], current_user.get('username', ''), 'doc.link',
                                   f'link/{link_id}', f'{req.source_id} -> {req.target_id} ({req.relation_type})')
    return {"id": link_id, "status": "linked"}


@router.get("/v2/docs/tree/{project_id}")
async def v2_get_doc_tree(project_id: int, root: str = None):
    return await repository.get_document_tree(project_id, root)


@router.post("/v2/docs/sync")
async def v2_sync_docs(project_id: int = 1, current_user=Depends(require_admin)):
    from config.settings import Settings
    settings = Settings()
    specs_dir = settings.SPECS_DIR if hasattr(settings, 'SPECS_DIR') else str(_specs_dir)
    result = await repository.sync_fs_to_db(specs_dir, project_id, current_user['id'])
    await repository.add_audit_log(current_user['id'], current_user.get('username', ''), 'doc.sync',
                                   'sync/', f'新建{result["created"]} 更新{result["updated"]} 跳过{result["skipped"]}')
    return result
