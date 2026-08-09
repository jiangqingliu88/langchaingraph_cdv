"""
用户操作行为分析 + 文档-代码一致性检查

- BehaviorTracker: 追踪用户操作，分析瓶颈和卡点
- DocConsistencyChecker: Spec 变更时检查关联规则/测试是否需要同步
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


# ═══════════════════════════════════════════════════════════
# 用户行为追踪
# ═══════════════════════════════════════════════════════════

@dataclass
class UserAction:
    """单次用户操作"""
    username: str
    action: str            # pipeline_run / signoff_create / doc_edit / approve / reject
    page: str = ""         # dashboard / signoff / docs / vplan / pipeline
    duration_ms: float = 0  # 在此操作上花费的时间
    result: str = "success"  # success / failed / cancelled
    timestamp: str = ""
    detail: str = ""


class BehaviorTracker:
    """用户行为追踪器"""

    def __init__(self):
        self._actions: list[UserAction] = []
        self._page_views: Counter = Counter()
        self._action_sequences: list[list[str]] = []  # 用户操作序列
        self._current_session: dict[str, list[str]] = {}  # username -> action sequence

    def track(self, username: str, action: str, page: str = "",
              duration_ms: float = 0, result: str = "success", detail: str = ""):
        """记录一次操作"""
        ua = UserAction(username=username, action=action, page=page,
                        duration_ms=duration_ms, result=result,
                        timestamp=datetime.now().isoformat(), detail=detail)
        self._actions.append(ua)
        self._page_views[page] += 1

        # 追踪操作序列
        if username not in self._current_session:
            self._current_session[username] = []
        self._current_session[username].append(action)

        # 截断过长序列
        if len(self._actions) > 10000:
            self._actions = self._actions[-5000:]

    def get_analysis(self, days: int = 7) -> dict:
        """获取用户行为分析报告"""
        cutoff = datetime.now() - timedelta(days=days)
        recent = [a for a in self._actions
                  if a.timestamp and datetime.fromisoformat(a.timestamp) > cutoff]

        if not recent:
            return {"period_days": days, "total_actions": 0, "message": "暂无数据"}

        # 用户活跃度
        user_stats = Counter()
        for a in recent:
            user_stats[a.username] += 1

        # 页面访问分布
        page_dist = Counter()
        for a in recent:
            page_dist[a.page or "unknown"] += 1

        # 操作成功率
        action_success = defaultdict(lambda: {"total": 0, "success": 0, "failed": 0, "cancelled": 0})
        for a in recent:
            action_success[a.action]["total"] += 1
            action_success[a.action][a.result] += 1

        action_rates = {}
        for action, stats in action_success.items():
            action_rates[action] = {
                "total": stats["total"],
                "success_rate": round(stats["success"] / max(stats["total"], 1) * 100, 1),
                "failure_rate": round(stats["failed"] / max(stats["total"], 1) * 100, 1),
                "cancel_rate": round(stats["cancelled"] / max(stats["total"], 1) * 100, 1),
            }

        # 高频操作序列（2-3 步连续模式）
        sequences = []
        for username, seq in self._current_session.items():
            for i in range(len(seq) - 1):
                sequences.append(f"{seq[i]} -> {seq[i+1]}")
        common_flows = Counter(sequences).most_common(10)

        # 瓶颈识别：失败率最高的操作
        bottlenecks = sorted(
            [{"action": a, "stats": s} for a, s in action_rates.items()
             if s["failure_rate"] > 10 or s["cancel_rate"] > 20],
            key=lambda x: -(x["stats"]["failure_rate"] + x["stats"]["cancel_rate"])
        )

        return {
            "period_days": days,
            "total_actions": len(recent),
            "unique_users": len(user_stats),
            "top_users": [{"username": u, "actions": c} for u, c in user_stats.most_common(10)],
            "page_distribution": dict(page_dist.most_common()),
            "action_success_rates": action_rates,
            "common_flows": [{"flow": f, "count": c} for f, c in common_flows],
            "bottlenecks": bottlenecks[:5],
        }

    def get_stuck_points(self) -> list[dict]:
        """识别最常卡住的步骤"""
        stuck = []
        for a in self._actions[-1000:]:
            if a.result in ("failed", "cancelled"):
                stuck.append({
                    "action": a.action, "page": a.page,
                    "username": a.username,
                    "detail": a.detail[:200],
                    "timestamp": a.timestamp,
                })
        return stuck[-20:]


# ═══════════════════════════════════════════════════════════
# 文档-代码一致性检查
# ═══════════════════════════════════════════════════════════

@dataclass
class ConsistencyIssue:
    """一致性问题的严重程度"""
    type: str              # missing_req / stale_test / orphaned_doc / hash_mismatch
    severity: str          # critical / warning / info
    description: str
    spec_file: str = ""
    related_file: str = ""
    fix_suggestion: str = ""


class DocConsistencyChecker:
    """文档与代码一致性检查器"""

    def check_spec_vs_tests(self, spec_dir: str = "specs", test_dir: str = "output/testcases") -> list[ConsistencyIssue]:
        """检查 spec 中的需求是否有对应的测试用例"""
        issues = []
        spec_path = Path(spec_dir)
        test_path = Path(test_dir)

        if not spec_path.exists():
            return [ConsistencyIssue("missing_dir", "critical", f"Spec 目录不存在: {spec_dir}")]

        # 收集所有 spec 中的需求 ID
        import re
        spec_reqs: dict[str, str] = {}  # req_id -> spec_file
        for md in spec_path.glob("**/*.md"):
            content = md.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'REQ_\w+', content):
                spec_reqs[m.group(0)] = str(md.relative_to(spec_path))

        # 收集所有测试用例中的关联需求
        test_reqs: set[str] = set()
        if test_path.exists():
            for f in test_path.glob("**/*"):
                if f.is_file() and f.suffix in (".sv", ".svh", ".yaml", ".json"):
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                        for m in re.finditer(r'REQ_\w+', content):
                            test_reqs.add(m.group(0))
                    except Exception:
                        pass

        # 检查：有 spec 但无测试
        for req_id, spec_file in spec_reqs.items():
            if req_id not in test_reqs:
                issues.append(ConsistencyIssue(
                    type="missing_test",
                    severity="warning",
                    description=f"需求 {req_id} 在 {spec_file} 中定义，但无对应测试用例",
                    spec_file=spec_file,
                    fix_suggestion=f"为 {req_id} 生成测试用例",
                ))

        # 检查：有测试但 spec 中已不存在
        for req_id in test_reqs:
            if req_id not in spec_reqs:
                issues.append(ConsistencyIssue(
                    type="orphaned_test",
                    severity="info",
                    description=f"测试引用了不存在的需求 {req_id}",
                    fix_suggestion="更新测试注释或删除无效引用",
                ))

        return issues

    def check_spec_hash_integrity(self, doc_id: int) -> list[ConsistencyIssue]:
        """检查数据库文档 hash 与文件系统是否一致"""
        import asyncio
        issues = []

        async def _check():
            from src.database.repository import get_document
            doc = await get_document(doc_id)
            if not doc:
                issues.append(ConsistencyIssue(
                    type="missing_doc", severity="critical",
                    description=f"文档 ID={doc_id} 在数据库中不存在",
                ))
                return

            fs_path = Path(doc.get("path", ""))
            if fs_path.exists():
                actual_hash = hashlib.sha256(fs_path.read_bytes()).hexdigest()
                db_hash = doc.get("content_hash", "")
                if actual_hash != db_hash:
                    issues.append(ConsistencyIssue(
                        type="hash_mismatch", severity="warning",
                        description=f"文档 {doc.get('path')} 文件系统 hash ({actual_hash[:12]}...) 与数据库 ({db_hash[:12]}...) 不一致",
                        spec_file=str(fs_path),
                        fix_suggestion="重新同步文档到数据库",
                    ))
            else:
                issues.append(ConsistencyIssue(
                    type="missing_file", severity="warning",
                    description=f"文档 {doc.get('path')} 在文件系统中不存在",
                    fix_suggestion="从数据库恢复或删除该记录",
                ))

        try:
            asyncio.run(_check())
        except Exception as e:
            issues.append(ConsistencyIssue(
                type="check_error", severity="warning",
                description=f"一致性检查出错: {e}",
            ))

        return issues

    def check_all(self, spec_dir: str = "specs") -> dict:
        """运行全部一致性检查"""
        issues = self.check_spec_vs_tests(spec_dir)
        critical = [i for i in issues if i.severity == "critical"]
        warnings = [i for i in issues if i.severity == "warning"]

        return {
            "total_issues": len(issues),
            "critical": len(critical),
            "warnings": len(warnings),
            "healthy": len(critical) == 0,
            "issues": [{
                "type": i.type, "severity": i.severity,
                "description": i.description, "spec_file": i.spec_file,
                "related_file": i.related_file, "fix_suggestion": i.fix_suggestion,
            } for i in issues[:50]],
        }


# ── 全局实例 ──
_behavior_tracker: Optional[BehaviorTracker] = None
_doc_checker: Optional[DocConsistencyChecker] = None


def get_behavior_tracker() -> BehaviorTracker:
    global _behavior_tracker
    if _behavior_tracker is None:
        _behavior_tracker = BehaviorTracker()
    return _behavior_tracker


def get_doc_checker() -> DocConsistencyChecker:
    global _doc_checker
    if _doc_checker is None:
        _doc_checker = DocConsistencyChecker()
    return _doc_checker
