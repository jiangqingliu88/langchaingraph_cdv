"""
PPA Signoff Routes — Power / Performance / Area 签核 API
"""
from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from src.core.auth import require_auth, require_admin, get_current_user
from src.database import repository

router = APIRouter(prefix="/api/ppa", tags=["ppa"])


# ── 请求模型 ──

class PPAMetricImportRequest(BaseModel):
    signoff_id: int
    metrics: list[dict] = Field(default_factory=list)  # [{category, metric_name, target_value, actual_value, unit, ...}]


class PPAReportParseRequest(BaseModel):
    report_text: str = ""
    report_type: str = "pt_power"  # pt_power / pt_timing / dc_area / innovus_area
    signoff_id: int = 0


class PPAConstraintRequest(BaseModel):
    project_id: int = 0
    category: str           # power / performance / area
    metric_name: str        # total_power / fmax / cell_area ...
    threshold_value: float
    unit: str = ''
    constraint_type: str = 'max'
    margin_required_pct: float = 10.0
    severity: str = 'P1'
    description: str = ''


class PPACornerRequest(BaseModel):
    signoff_id: int
    corner_name: str          # ss_0p99v_125c / tt_1p1v_25c / ff_1p21v_m40c
    pvt_desc: str = ''
    total_power_mw: float = 0.0
    dynamic_power_mw: float = 0.0
    leakage_power_mw: float = 0.0
    fmax_mhz: float = 0.0
    setup_worst_ns: float = 0.0
    hold_worst_ns: float = 0.0
    area_mm2: float = 0.0
    cell_count: int = 0
    utilization_pct: float = 0.0
    extra_json: dict = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# PPA Metrics API
# ═══════════════════════════════════════════════════════════

@router.post("/metrics/import")
async def import_ppa_metrics(req: PPAMetricImportRequest, user: dict = Depends(require_auth)):
    """批量导入 PPA 指标数据（从 EDA 报告解析后调用）"""
    if not req.metrics:
        raise HTTPException(status_code=400, detail="metrics list is required")
    for m in req.metrics:
        m['signoff_id'] = req.signoff_id
    ids = await repository.batch_create_ppa_metrics(req.metrics)
    await repository.add_audit_log(
        user["user_id"], user["username"], "ppa_metrics_import",
        f"signoff/{req.signoff_id}",
        f"导入 {len(ids)} 条 PPA 指标",
        role=user.get("role", ""), resource_type="ppa",
    )
    return {"ok": True, "imported": len(ids), "metric_ids": ids}


@router.get("/metrics/{signoff_id}")
async def get_ppa_metrics(signoff_id: int, category: str = ""):
    """获取签核关联的 PPA 指标 — 含 pass/fail/marginal 判定"""
    metrics = await repository.get_ppa_metrics(signoff_id, category or None)
    by_cat = {}
    for m in metrics:
        by_cat.setdefault(m['category'], []).append(m)
    stats = {}
    for cat, items in by_cat.items():
        stats[cat] = {
            'total': len(items),
            'passed': sum(1 for i in items if i['pass_status'] == 'pass'),
            'failed': sum(1 for i in items if i['pass_status'] == 'fail'),
            'marginal': sum(1 for i in items if i['pass_status'] == 'marginal'),
        }
    return {
        "signoff_id": signoff_id,
        "metrics": metrics,
        "total": len(metrics),
        "by_category": by_cat,
        "stats": stats,
        "overall_pass": all(
            s['failed'] == 0 and s['marginal'] == 0 for s in stats.values()
        ) if stats else True,
    }


@router.get("/metrics/{signoff_id}/summary")
async def get_ppa_summary(signoff_id: int):
    """获取签核的 PPA 综合摘要（供签核卡片展示）"""
    summary = await repository.get_ppa_signoff_summary(signoff_id)
    if not summary:
        raise HTTPException(status_code=404, detail="签核不存在或无 PPA 数据")
    return summary


@router.put("/metrics/{metric_id}")
async def update_ppa_metric(metric_id: int, fields: dict,
                            user: dict = Depends(require_auth)):
    """更新单条 PPA 指标"""
    ok = await repository.update_ppa_metric(metric_id, **fields)
    if not ok:
        raise HTTPException(status_code=404, detail="指标不存在")
    await repository.add_audit_log(
        user["user_id"], user["username"], "ppa_metric_update",
        f"metric/{metric_id}", f"更新 PPA 指标",
        role=user.get("role", ""), resource_type="ppa",
    )
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
# PPA Corner API
# ═══════════════════════════════════════════════════════════

@router.post("/corners")
async def create_ppa_corner(req: PPACornerRequest, user: dict = Depends(require_auth)):
    """创建 PPA corner 记录"""
    fields = {k: v for k, v in req.dict().items()
              if k not in ('signoff_id', 'corner_name')}
    cid = await repository.create_ppa_corner(req.signoff_id, req.corner_name, **fields)
    await repository.add_audit_log(
        user["user_id"], user["username"], "ppa_corner_create",
        f"signoff/{req.signoff_id}",
        f"corner={req.corner_name}",
        role=user.get("role", ""), resource_type="ppa",
    )
    return {"id": cid, "status": "created"}


@router.get("/corners/{signoff_id}")
async def get_ppa_corners(signoff_id: int):
    """获取签核的所有 PVT corner 数据"""
    corners = await repository.get_ppa_corners(signoff_id)
    summary = await repository.get_ppa_corner_summary(signoff_id)
    return {
        "signoff_id": signoff_id,
        "corners": corners,
        "total": len(corners),
        "summary": summary,
    }


# ═══════════════════════════════════════════════════════════
# PPA Constraints API
# ═══════════════════════════════════════════════════════════

@router.post("/constraints")
async def create_ppa_constraint(req: PPAConstraintRequest,
                                user: dict = Depends(require_auth)):
    """创建 PPA 门限规则"""
    cid = await repository.create_ppa_constraint(
        req.project_id, req.category, req.metric_name,
        req.threshold_value, req.unit, req.constraint_type,
        req.margin_required_pct, req.severity, req.description,
        user["user_id"],
    )
    await repository.add_audit_log(
        user["user_id"], user["username"], "ppa_constraint_create",
        f"constraint/{cid}",
        f"{req.category}/{req.metric_name} threshold={req.threshold_value}{req.unit}",
        role=user.get("role", ""), resource_type="ppa",
    )
    return {"id": cid, "status": "created"}


@router.get("/constraints")
async def get_ppa_constraints(project_id: int = 0, category: str = ""):
    """查询 PPA 门限规则"""
    constraints = await repository.get_ppa_constraints(
        project_id if project_id else None,
        category if category else None,
    )
    return {"constraints": constraints, "total": len(constraints)}


@router.put("/constraints/{constraint_id}")
async def update_ppa_constraint(constraint_id: int, fields: dict,
                                user: dict = Depends(require_admin)):
    """更新 PPA 门限规则（需管理员）"""
    ok = await repository.update_ppa_constraint(constraint_id, **fields)
    if not ok:
        raise HTTPException(status_code=404, detail="约束规则不存在")
    await repository.add_audit_log(
        user["user_id"], user["username"], "ppa_constraint_update",
        f"constraint/{constraint_id}", f"更新 PPA 门限",
        role=user.get("role", ""), resource_type="ppa", is_privileged=True,
    )
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
# EDA 报告解析 API
# ═══════════════════════════════════════════════════════════

@router.post("/report/parse")
async def parse_ppa_report(req: PPAReportParseRequest,
                           user: dict = Depends(require_auth)):
    """从 EDA PPA 报告文本自动解析关键指标"""
    if not req.report_text.strip():
        raise HTTPException(status_code=400, detail="report_text is required")

    from src.core.engines import PPAAnalyzer
    analyzer = PPAAnalyzer()
    result = analyzer.parse_report(req.report_text, req.report_type)

    # 如果提供了 signoff_id，自动存入
    if req.signoff_id and result.get('metrics'):
        for m in result['metrics']:
            m['signoff_id'] = req.signoff_id
        ids = await repository.batch_create_ppa_metrics(result['metrics'])
        result['stored'] = len(ids)

    await repository.add_audit_log(
        user["user_id"], user["username"], "ppa_report_parse",
        f"signoff/{req.signoff_id}" if req.signoff_id else "",
        f"type={req.report_type} metrics={len(result.get('metrics', []))}",
        role=user.get("role", ""), resource_type="ppa",
    )
    return result


# ═══════════════════════════════════════════════════════════
# PPA 状态总览 API
# ═══════════════════════════════════════════════════════════

@router.get("/status/{project_id}")
async def get_ppa_status(project_id: int):
    """一键查看项目 PPA 签核全景"""
    # 获取项目所有 PPA 签核
    from src.database.repository import list_signoffs
    signoffs = await list_signoffs(project_id)

    ppa_signoffs = [s for s in signoffs
                    if s.get('report_type', '').startswith('ppa')]

    result = {
        "project_id": project_id,
        "ppa_signoffs": [],
        "summary": {
            "total": len(ppa_signoffs),
            "approved": 0,
            "pending": 0,
            "rejected": 0,
            "power_ok": False,
            "perf_ok": False,
            "area_ok": False,
        },
    }

    for sf in ppa_signoffs:
        ppa_summary = await repository.get_ppa_signoff_summary(sf['id'])
        cat_summary = {}
        for cat, data in ppa_summary.get('categories', {}).items():
            cat_summary[cat] = {
                'all_pass': data['all_pass'],
                'passed': data['passed'],
                'total': data['total'],
            }
        sf['ppa'] = cat_summary
        sf['overall_pass'] = ppa_summary.get('overall_pass', False)
        result['ppa_signoffs'].append(sf)

        if sf['status'] == 'approved':
            result['summary']['approved'] += 1
        elif sf['status'] == 'pending':
            result['summary']['pending'] += 1
        elif sf['status'] == 'rejected':
            result['summary']['rejected'] += 1

    # 聚合判定
    for sf in result['ppa_signoffs']:
        if sf['status'] == 'approved':
            for cat in ('power', 'performance', 'area'):
                if sf['ppa'].get(cat, {}).get('all_pass', False):
                    result['summary'][f'{cat}_ok'] = True

    return result


# ═══════════════════════════════════════════════════════════
# PPA 签核门限检查 API
# ═══════════════════════════════════════════════════════════

@router.post("/check/{signoff_id}")
async def check_ppa_against_constraints(signoff_id: int):
    """对比 PPA 指标与项目门限规则，返回逐项判定"""
    from src.database.repository import get_signoff_by_id

    sf = await get_signoff_by_id(signoff_id)
    if not sf:
        raise HTTPException(status_code=404, detail="签核不存在")

    project_id = sf.get('project_id', 0)
    metrics = await repository.get_ppa_metrics(signoff_id)
    constraints = await repository.get_ppa_constraints(project_id)

    # 逐条对比
    checks = []
    for c in constraints:
        matched = [m for m in metrics
                   if m['category'] == c['category']
                   and m['metric_name'] == c['metric_name']]
        if matched:
            m = matched[0]
            if c['constraint_type'] == 'max':
                margin = (c['threshold_value'] - m['actual_value']) / max(c['threshold_value'], 0.001) * 100
                ok = m['actual_value'] <= c['threshold_value']
            elif c['constraint_type'] == 'min':
                margin = (m['actual_value'] - c['threshold_value']) / max(c['threshold_value'], 0.001) * 100
                ok = m['actual_value'] >= c['threshold_value']
            else:
                margin = 0
                ok = True

            marginal = ok and margin < c['margin_required_pct']
            status = 'fail' if not ok else ('marginal' if marginal else 'pass')

            checks.append({
                'category': c['category'], 'metric_name': c['metric_name'],
                'threshold': c['threshold_value'], 'unit': c['unit'],
                'actual': m['actual_value'], 'margin_pct': round(margin, 2),
                'margin_required_pct': c['margin_required_pct'],
                'constraint_type': c['constraint_type'],
                'severity': c['severity'], 'status': status,
            })
        else:
            checks.append({
                'category': c['category'], 'metric_name': c['metric_name'],
                'threshold': c['threshold_value'], 'unit': c['unit'],
                'actual': None, 'status': 'no_data',
                'severity': c['severity'],
            })

    # 自动更新 metric 的 pass_status
    for chk in checks:
        for m in metrics:
            if m['category'] == chk['category'] and m['metric_name'] == chk['metric_name']:
                await repository.update_ppa_metric(
                    m['id'], pass_status=chk['status'], margin_pct=chk['margin_pct']
                )

    overall = all(c['status'] in ('pass', 'marginal', 'no_data') for c in checks
                  if c['severity'] == 'P0')
    p0_fails = [c for c in checks if c['status'] == 'fail' and c['severity'] == 'P0']

    return {
        "signoff_id": signoff_id,
        "project_id": project_id,
        "checks": checks,
        "total": len(checks),
        "passed": sum(1 for c in checks if c['status'] == 'pass'),
        "failed": sum(1 for c in checks if c['status'] == 'fail'),
        "marginal": sum(1 for c in checks if c['status'] == 'marginal'),
        "no_data": sum(1 for c in checks if c['status'] == 'no_data'),
        "overall_pass": overall,
        "p0_blockers": p0_fails,
    }
