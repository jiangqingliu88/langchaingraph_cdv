"""
ExcludeRegistry —— "允许放弃"的工程化（与"确保不漏测"同等重要）。

100% 覆盖率在真实芯片项目几乎不可能——总有死代码（if(0) 分支）、tie-off 信号、
规格不要求测的场景。强行追最后的 1% 花费十倍时间却毫无意义。所以"放弃"必须
被工程化：走四步闭环，有据可查地放弃，而不是假装覆盖。

四步闭环：
  1. 自动发现：Coverage/Debug Agent 报告"某覆盖点持续 0% 且诊断是结构性死代码"
  2. 归因分类：unreachable（结构死代码）/ excluded_by_design（规格不测）/ not_worth_it（成本高）
  3. 审计门控：Exclude 记录带 approver（工程师签名）+ audit_hash（哈希指纹，接证据链）
  4. 动态调规：有效覆盖率 = coverage / (total - excluded)，决策层按有效覆盖率判断

用法:
    from src.knowledge.exclude_registry import ExcludeRegistry
    reg = ExcludeRegistry("database/exclude_registry.db")
    reg.propose_exclude("opcode[31:16]", "结构死代码，tie-off 固定", "unreachable", "波形+RTL追溯")
    reg.approve_exclude("EXC-2026-001", "张三")
    eff = reg.effective_coverage(95.0, 100)  # → 97.9（Exclude 3 个点后）
"""
from __future__ import annotations

from .sqlite_utils import connect

import hashlib
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Exclude 类型
TYPE_UNREACHABLE = "unreachable"            # 结构死代码，不可能触达
TYPE_EXCLUDED_BY_DESIGN = "excluded_by_design"  # 规格明确不要求测
TYPE_NOT_WORTH_IT = "not_worth_it"          # 可达但成本高，工程师评估放弃

# 状态机
STATUS_PROPOSED = "proposed"     # 提议（待审批）
STATUS_APPROVED = "approved"     # 批准（生效）
STATUS_REJECTED = "rejected"     # 拒绝

_SCHEMA = """
CREATE TABLE IF NOT EXISTS exclude_registry (
    exclude_id      TEXT PRIMARY KEY,
    coverage_point  TEXT NOT NULL,
    exclude_type    TEXT NOT NULL DEFAULT 'unreachable',
    reason          TEXT NOT NULL DEFAULT '',
    evidence        TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'proposed',
    approver        TEXT NOT NULL DEFAULT '',
    audit_hash      TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL DEFAULT ''
);
"""


#: 覆盖率口径 → 覆盖地图里的 bin 归属。
#:
#: 两个口径是**不同分母**：功能口径看 `covergroup` 采到的 bin，代码口径看
#: line/branch/toggle 那些。混在一起算（历史行为）等于让"功能覆盖率 95%"
#: 被代码覆盖率的缺口拖下去 —— 闭环于是永远收敛不了（拿一个它的动作推不动
#: 的数当目标，正是 `planning.py` 里记过的同一类病）。
_METRIC_BIN_KINDS = {
    "functional": lambda b: b.get("metric") == "covergroup" or b.get("type") == "functional",
    "code": lambda b: b.get("type") in ("code", "toggle"),
}


def _bins_for_metric(bins: List[Dict[str, Any]],
                     metric: str = "") -> tuple:
    """按口径挑 bin → `(bins, 是否真的过滤了)`。

    口径为空 / 不认识 / 这个口径一个 bin 都没有 → 原样返回全部（第二项 False），
    调用方据此回退到整体覆盖地图，而不是拿一个空集合算出 0%。
    """
    pick = _METRIC_BIN_KINDS.get((metric or "").strip().lower())
    if pick is None:
        return list(bins), False
    selected = [b for b in bins if pick(b)]
    if not selected:
        return list(bins), False
    return selected, True


class ExcludeRegistry:
    """Exclude 状态库（同步 sqlite，跨 run 持久，接证据链哈希）。"""

    def __init__(self, db_path: Optional[str | Path] = None):
        from config.paths import EXCLUDE_DB

        self.db_path = Path(db_path) if db_path else EXCLUDE_DB
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = connect(self.db_path)
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    def _next_id(self) -> str:
        with self._lock:
            n = self._connect().execute(
                "SELECT COUNT(*) FROM exclude_registry").fetchone()[0]
        return f"EXC-{n + 1:04d}"

    def _last_approved_hash(self) -> str:
        """返回上一条 approved 记录的 audit_hash（哈希链锚点，跨 run/跨实例连续）。"""
        try:
            row = self._connect().execute(
                "SELECT audit_hash FROM exclude_registry WHERE status=? "
                "ORDER BY updated_at DESC, exclude_id DESC LIMIT 1",
                (STATUS_APPROVED,)).fetchone()
            return row[0] if row and row[0] else ""
        except Exception:
            return ""

    # ═══════════════════════════════════════════════════════════
    # 1. 自动发现 → 提议（归因分类）
    # ═══════════════════════════════════════════════════════════

    def propose_exclude(self, coverage_point: str, reason: str,
                        exclude_type: str = TYPE_UNREACHABLE,
                        evidence: str = "") -> str:
        """自动发现 → 提议 Exclude（状态 proposed，待审批）。返回 exclude_id。"""
        exclude_id = self._next_id()
        now = self._now()
        with self._lock:
            self._connect().execute(
                "INSERT INTO exclude_registry "
                "(exclude_id, coverage_point, exclude_type, reason, evidence, status, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (exclude_id, coverage_point, exclude_type, reason, evidence,
                 STATUS_PROPOSED, now, now))
            self._connect().commit()
        return exclude_id

    # ═══════════════════════════════════════════════════════════
    # 2. 审计门控：批准 / 拒绝（带哈希指纹）
    # ═══════════════════════════════════════════════════════════

    def approve_exclude(self, exclude_id: str, approver: str) -> bool:
        """审计门控：工程师批准（记录 approver + audit_hash，接证据链）。"""
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT coverage_point, exclude_type, reason, evidence "
                "FROM exclude_registry WHERE exclude_id=?", (exclude_id,)).fetchone()
            if not row:
                return False
            # 哈希链：前一个 approved 的 hash + 本条记录（从 db 读，跨 run/跨实例连续）
            content = json.dumps({
                "exclude_id": exclude_id, "coverage_point": row[0],
                "type": row[1], "reason": row[2], "evidence": row[3],
                "approver": approver,
            }, sort_keys=True, ensure_ascii=False) + self._last_approved_hash()
            audit_hash = hashlib.sha256(content.encode()).hexdigest()
            conn.execute(
                "UPDATE exclude_registry SET status=?, approver=?, audit_hash=?, "
                "updated_at=? WHERE exclude_id=?",
                (STATUS_APPROVED, approver, audit_hash, self._now(), exclude_id))
            conn.commit()
        return True

    def reject_exclude(self, exclude_id: str, approver: str = "") -> bool:
        """拒绝 Exclude。返回**是否真的改到了**一条。

        原来这里无条件 `return True`：UPDATE 命中 0 行也报成功，于是界面上会出现
        「已拒绝 EXC-9999」而库里根本没有这条 —— 一个撒谎的成功。`approve_exclude`
        一直是先查后改的，两边口径要一致（全仓库的"失败响亮"纪律）。
        """
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "UPDATE exclude_registry SET status=?, approver=?, updated_at=? "
                "WHERE exclude_id=?",
                (STATUS_REJECTED, approver, self._now(), exclude_id))
            conn.commit()
            changed = cur.rowcount > 0
        return changed

    # ═══════════════════════════════════════════════════════════
    # 3. 查询
    # ═══════════════════════════════════════════════════════════

    def get_approved_excludes(self) -> List[Dict[str, Any]]:
        """已批准的 Exclude 点（生效的）。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT * FROM exclude_registry WHERE status=? ORDER BY exclude_id",
                (STATUS_APPROVED,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_pending(self) -> List[Dict[str, Any]]:
        """待审批的 Exclude。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT * FROM exclude_registry WHERE status=? ORDER BY exclude_id",
                (STATUS_PROPOSED,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_excluded_points(self) -> set:
        """已批准的覆盖点集合（供调规排除）。"""
        return {e["coverage_point"] for e in self.get_approved_excludes()}

    def get_all_points(self) -> set:
        """所有已登记（proposed + approved）覆盖点集合（供自动发现去重）。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT coverage_point FROM exclude_registry "
                "WHERE status IN (?, ?)", (STATUS_PROPOSED, STATUS_APPROVED)).fetchall()
        return {r[0] for r in rows}

    def get_point_status(self, coverage_point: str) -> Optional[str]:
        """查询某覆盖点当前状态（approved/proposed/None）。"""
        with self._lock:
            row = self._connect().execute(
                "SELECT status FROM exclude_registry WHERE coverage_point=? "
                "ORDER BY updated_at DESC LIMIT 1", (coverage_point,)).fetchone()
        return row[0] if row else None

    # ═══════════════════════════════════════════════════════════
    # 4. 动态调规
    # ═══════════════════════════════════════════════════════════

    def effective_coverage(self, coverage: float, total_points: int) -> float:
        """动态调规：有效覆盖率 = coverage / (total - excluded)。

        coverage: 当前覆盖率（%）
        total_points: 总覆盖点数
        返回：有效覆盖率（%，Exclude 点数从分母剔除后）
        """
        excluded = len(self.get_excluded_points())
        effective_total = max(total_points - excluded, 1)
        return round(coverage * total_points / 100 / effective_total * 100, 1)

    def effective_coverage_from_map(self, map_data: Dict[str, Any],
                                     metric: str = "") -> Dict[str, Any]:
        """从覆盖地图 + 已批准 Exclude 计算有效覆盖率（bin 级精确调规）。

        Args:
            map_data: CoverageMap.build() 输出 {bins, covered, total, coverage, ...}
            metric: 覆盖率**口径**（`functional` / `code`）。给了就只在这一口径的
                bin 上算 —— 不把代码/toggle 的缺口混进功能口径的分母。
        返回:
            {total, covered, excluded, effective_total, effective_coverage,
             raw_coverage, metric, metric_filtered}
        """
        bins, metric_filtered = _bins_for_metric(map_data.get("bins") or [], metric)
        if metric_filtered:
            total = sum(int(b.get("bins", 0) or 0) for b in bins)
            covered = sum(int(b.get("covered", 0) or 0) for b in bins)
            raw_coverage = round(covered / total * 100, 1) if total else 0.0
        else:
            total = map_data.get("total", 0)
            covered = map_data.get("covered", 0)
            raw_coverage = map_data.get("coverage", 0.0)
        excluded_points = self.get_excluded_points()
        # `total`/`covered` 是 **bin 数**（见 `CoverageMap.build`），所以被豁免的条目
        # 要按它**自己的 bin 数**从分母里扣 —— 扣"条目个数"会和分母不同量纲。
        excluded = sum(int(b.get("bins", 1) or 0) for b in bins
                       if b.get("location") in excluded_points) if excluded_points else 0
        effective_total = max(total - excluded, 1)
        effective_coverage = round(covered / effective_total * 100, 1) if total else 0.0
        return {
            "total": total,
            "covered": covered,
            "excluded": excluded,
            "effective_total": effective_total,
            "raw_coverage": raw_coverage,
            "effective_coverage": effective_coverage,
            "metric": metric,
            "metric_filtered": metric_filtered,
        }

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            total = conn.execute("SELECT COUNT(*) FROM exclude_registry").fetchone()[0]
            approved = conn.execute(
                "SELECT COUNT(*) FROM exclude_registry WHERE status='approved'").fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM exclude_registry WHERE status='proposed'").fetchone()[0]
        return {"total": total, "approved": approved, "pending": pending,
                "excluded_points": len(self.get_excluded_points())}

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        cols = ["exclude_id", "coverage_point", "exclude_type", "reason", "evidence",
                "status", "approver", "audit_hash", "created_at", "updated_at"]
        return dict(zip(cols, row))
