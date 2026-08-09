"""
多租户隔离 + 平台自我健康管理

- TenantManager: workspace 级别数据隔离
- PlatformHealthMonitor: 过期规则检测、配置审计、平台自我诊断
"""
from __future__ import annotations

import json, hashlib
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════
# 多租户隔离
# ═══════════════════════════════════════════════════════════

@dataclass
class Tenant:
    """租户/工作空间"""
    tenant_id: str
    name: str
    workspace_root: str = ""
    db_path: str = ""          # 独立数据库路径
    description: str = ""
    is_active: bool = True
    created_at: str = ""
    config: dict = field(default_factory=dict)


class TenantManager:
    """多租户管理器"""

    def __init__(self, base_dir: str = "workspaces"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._tenants: dict[str, Tenant] = {}
        self._load_tenants()

    def create_tenant(self, tenant_id: str, name: str, description: str = "") -> Tenant:
        """创建租户"""
        ws_dir = self.base_dir / tenant_id
        ws_dir.mkdir(parents=True, exist_ok=True)

        tenant = Tenant(
            tenant_id=tenant_id, name=name,
            workspace_root=str(ws_dir.resolve()),
            db_path=str(ws_dir / "ic_verification.db"),
            description=description,
            created_at=datetime.now().isoformat(),
        )
        self._tenants[tenant_id] = tenant
        self._save_tenants()
        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        return self._tenants.get(tenant_id)

    def list_tenants(self) -> list[dict]:
        return [{
            "tenant_id": t.tenant_id, "name": t.name,
            "workspace_root": t.workspace_root,
            "is_active": t.is_active, "created_at": t.created_at,
        } for t in self._tenants.values()]

    def _load_tenants(self):
        config_file = self.base_dir / "tenants.json"
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
                for t_data in data.get("tenants", []):
                    t = Tenant(**t_data)
                    self._tenants[t.tenant_id] = t
            except Exception:
                pass

    def _save_tenants(self):
        config_file = self.base_dir / "tenants.json"
        data = {"tenants": [t.__dict__ for t in self._tenants.values()]}
        config_file.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                               encoding="utf-8")


# ═══════════════════════════════════════════════════════════
# 平台自我健康管理
# ═══════════════════════════════════════════════════════════

@dataclass
class HealthIssue:
    """健康问题"""
    type: str              # expired_rule / unused_template / missing_evidence / stale_config
    severity: str          # critical / warning / info
    description: str
    location: str = ""
    recommendation: str = ""
    detected_at: str = ""


class PlatformHealthMonitor:
    """平台自我健康监控器"""

    def __init__(self):
        self._issues: list[HealthIssue] = []
        self._last_check: str = ""

    def check_all(self, db_path: str = "ic_verification.db") -> dict:
        """运行全面健康检查"""
        import sqlite3
        issues: list[HealthIssue] = []
        now = datetime.now()

        try:
            conn = sqlite3.connect(db_path)

            # 1. 检测过期规则（30天未使用的 workflow trigger）
            triggers = conn.execute(
                "SELECT name, created_at FROM workflow_triggers WHERE is_active=1"
            ).fetchall()
            for name, created in triggers:
                try:
                    created_dt = datetime.fromisoformat(created) if created else now
                    if (now - created_dt).days > 30:
                        issues.append(HealthIssue(
                            type="unused_trigger", severity="info",
                            description=f"工作流触发器 '{name}' 创建超过 30 天未更新",
                            recommendation="检查是否仍需要此触发器",
                            detected_at=now.isoformat(),
                        ))
                except Exception:
                    pass

            # 2. 检测未归档的旧签核
            old_signoffs = conn.execute(
                "SELECT COUNT(*) FROM signoffs WHERE is_deleted=0 AND is_archived=0 AND status='approved'"
            ).fetchone()
            if old_signoffs and old_signoffs[0] > 10:
                issues.append(HealthIssue(
                    type="pending_archive", severity="warning",
                    description=f"{old_signoffs[0]} 个已批准的签核未归档",
                    recommendation="批量归档以优化查询性能",
                    detected_at=now.isoformat(),
                ))

            # 3. 检测无证据的已批准签核
            no_evidence = conn.execute(
                "SELECT COUNT(*) FROM signoffs WHERE status='approved' AND manifest_hash=''"
            ).fetchone()
            if no_evidence and no_evidence[0] > 0:
                issues.append(HealthIssue(
                    type="missing_evidence", severity="warning",
                    description=f"{no_evidence[0]} 个已批准签核缺少 manifest_hash",
                    recommendation="补充证据链绑定",
                    detected_at=now.isoformat(),
                ))

            # 4. 检测数据库大小
            import os
            db_size_kb = os.path.getsize(db_path) / 1024
            if db_size_kb > 500 * 1024:  # >500MB
                issues.append(HealthIssue(
                    type="db_size_warning", severity="warning",
                    description=f"数据库大小 {db_size_kb/1024:.1f}MB，建议考虑分表或归档",
                    detected_at=now.isoformat(),
                ))

            # 5. 检测长期 running 的流水线
            stuck = conn.execute(
                "SELECT COUNT(*) FROM pipeline_runs WHERE state='running'"
            ).fetchone()
            if stuck and stuck[0] > 5:
                issues.append(HealthIssue(
                    type="stuck_pipelines", severity="critical",
                    description=f"{stuck[0]} 个流水线处于 running 状态",
                    recommendation="检查是否有卡住的流程需要手动终止",
                    detected_at=now.isoformat(),
                ))

            # 6. 检测索引完整性
            tables = ["signoffs", "pipeline_runs", "audit_logs", "doc_documents",
                      "ppa_metrics", "artifacts", "design_modules"]
            for table in tables:
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})") if c[1]]
                if "created_at" in cols:
                    issues.append(HealthIssue(
                        type="index_check", severity="info",
                        description=f"表 {table} 建议在 created_at, project_id, status 上建索引",
                        recommendation="执行 CREATE INDEX IF NOT EXISTS",
                        detected_at=now.isoformat(),
                    ))

            conn.close()
        except Exception as e:
            issues.append(HealthIssue(
                type="check_error", severity="critical",
                description=f"健康检查失败: {e}",
                detected_at=now.isoformat(),
            ))

        self._issues = issues
        self._last_check = now.isoformat()

        critical = [i for i in issues if i.severity == "critical"]
        return {
            "healthy": len(critical) == 0,
            "total_issues": len(issues),
            "critical": len(critical),
            "warnings": len([i for i in issues if i.severity == "warning"]),
            "info": len([i for i in issues if i.severity == "info"]),
            "last_check": self._last_check,
            "issues": [{
                "type": i.type, "severity": i.severity,
                "description": i.description,
                "recommendation": i.recommendation,
            } for i in issues[:30]],
        }

    def get_expired_rules(self, db_path: str = "ic_verification.db", days: int = 90) -> list[dict]:
        """获取过期规则列表"""
        import sqlite3
        conn = sqlite3.connect(db_path)
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        try:
            rows = conn.execute(
                "SELECT name, created_at, event_type FROM workflow_triggers "
                "WHERE is_active=1 AND created_at < ?", (cutoff,)
            ).fetchall()
            return [{"name": r[0], "created_at": r[1], "event_type": r[2],
                     "days_since_creation": days} for r in rows]
        finally:
            conn.close()


# ── 全局 ──
_tenant_mgr: Optional[TenantManager] = None
_health_monitor: Optional[PlatformHealthMonitor] = None


def get_tenant_mgr() -> TenantManager:
    global _tenant_mgr
    if _tenant_mgr is None:
        _tenant_mgr = TenantManager()
    return _tenant_mgr


def get_health_monitor() -> PlatformHealthMonitor:
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = PlatformHealthMonitor()
    return _health_monitor
