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
