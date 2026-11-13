"""
跨项目知识复用（V4）—— 把验证知识从「单项目经验」变成「跨项目资产」

V2 的 KG 按 project_id 隔离存储 bug/fix/bin。V4 让这些知识跨项目复用：

  - 项目 B 遇到 model_mismatch 类 bug → 查项目 A 是否有同类 bug + 修复
  - 项目 B 的某类 gap（constraint 型）→ 查项目 A 同类 gap 用了什么动作最有效

本质是把「跨项目迁移」从 L5 的经验库（fingerprint 维度）提升到
「语义维度」（category / feature / signal），用 KG 的节点/边做检索。

用法:
    from src.layers.l3_decision.knowledge.cross_project import lookup_cross_project_bugs
    bugs = await lookup_cross_project_bugs(category="model_mismatch", exclude_project_id=1)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


async def lookup_cross_project_bugs(category: str, limit: int = 5,
                                    exclude_project_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """跨项目查同类 bug（按 affected_feature/category）。"""
    from sqlalchemy import select, or_
    from src.knowledge.persistence.connection import get_session
    from src.knowledge.persistence.models import VerificationBug

    s = await get_session()
    try:
        q = select(VerificationBug).where(VerificationBug.affected_feature == category)
        if exclude_project_id is not None:
            # NULL project_id 视为「共享/未分配」，不排除
            q = q.where(or_(VerificationBug.project_id.is_(None),
                            VerificationBug.project_id != exclude_project_id))
        bugs = (await s.execute(q.limit(limit))).scalars().all()
        return [{"bug_id": b.bug_id, "description": b.description,
                 "affected_signal": b.affected_signal, "project_id": b.project_id,
                 "status": b.status} for b in bugs]
    finally:
        await s.close()


async def lookup_cross_project_fixes(category: str, limit: int = 5) -> List[Dict[str, Any]]:
    """跨项目查同类 bug 的修复（bug 的 category 匹配 → 关联的 fix）。"""
    from sqlalchemy import select
    from src.knowledge.persistence.connection import get_session
    from src.knowledge.persistence.models import VerificationBug, VerificationFix

    s = await get_session()
    try:
        bug_ids = list((await s.execute(select(VerificationBug.bug_id)
                        .where(VerificationBug.affected_feature == category))).scalars().all())
        if not bug_ids:
            return []
        # bug 的 affected_signal（供置信度门控用）
        bug_map = {b.bug_id: b for b in
                   (await s.execute(select(VerificationBug)
                    .where(VerificationBug.bug_id.in_(bug_ids)))).scalars().all()}
        fixes = (await s.execute(select(VerificationFix)
                 .where(VerificationFix.bug_id.in_(bug_ids)).limit(limit))).scalars().all()
        return [{"bug_id": f.bug_id, "fix_id": f.fix_id, "description": f.description,
                 "affected_signal": (bug_map[f.bug_id].affected_signal
                                     if f.bug_id in bug_map else "")}
                for f in fixes]
    finally:
        await s.close()


def summarize_cross_project(bugs: List[Dict], fixes: List[Dict]) -> Dict[str, Any]:
    """跨项目知识摘要（供决策层/调试层参考）。"""
    return {
        "bugs": bugs,
        "fixes": fixes,
        "hint": (f"跨项目发现 {len(bugs)} 个同类 bug、{len(fixes)} 个修复，"
                 f"建议优先复用: {fixes[0]['fix_id'] if fixes else '无'}"),
    }


def signal_similarity(a: str, b: str) -> float:
    """信号名相似度（0-1，基于编辑距离）。用于跨项目复用的置信度门控。"""
    if not a or not b:
        return 0.0
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def gate_cross_project_fixes(fixes: List[Dict], current_signal: str,
                             threshold: float = 0.8) -> List[Dict]:
    """复用置信度门控：相似度 > threshold 才自动注入，否则仅作参考建议。

    为每个 fix 追加 similarity（信号名相似度）+ auto_apply（是否自动注入）。
    """
    gated = []
    for f in fixes or []:
        sim = signal_similarity(f.get("affected_signal", ""), current_signal)
        gated.append({**f, "similarity": round(sim, 3), "auto_apply": sim >= threshold})
    return gated
