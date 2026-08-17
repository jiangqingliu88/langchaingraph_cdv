"""
数据库迁移系统 — Schema versioning + 平滑升级

用法:
    python -m src.layers.l4_memory.persistence.migrations          # 执行所有待处理的迁移
    python -m src.layers.l4_memory.persistence.migrations --check  # 仅检查，不执行
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "ic_verification.db"

MIGRATIONS = [
    {
        "version": "1.0",
        "description": "初始 schema — 核心表创建",
        "script": """
        -- 此版本为初始 SQLAlchemy create_all
        -- 由 models.py 自动生成，无需手动 SQL
        SELECT 1;
        """,
    },
    {
        "version": "1.1",
        "description": "企业级模型: users, projects, audit_logs, knowledge, signoffs, signoff_events",
        "script": """
        SELECT 1;
        """,
    },
    {
        "version": "1.2",
        "description": "证据链: artifacts, evidence_links; 文档生态: doc_documents, doc_versions, doc_requirements, doc_relations",
        "script": """
        SELECT 1;
        """,
    },
    {
        "version": "1.3",
        "description": "设计三层映射: design_modules, design_features, req_feature_map, feature_testpoint_map",
        "script": """
        SELECT 1;
        """,
    },
    {
        "version": "1.4",
        "description": "doc_versions 补充字段: parent_version_id, is_restored",
        "script": """
        ALTER TABLE doc_versions ADD COLUMN parent_version_id INTEGER;
        ALTER TABLE doc_versions ADD COLUMN is_restored BOOLEAN DEFAULT 0;
        """,
    },
    {
        "version": "1.5",
        "description": "PPA 签核: ppa_metrics, ppa_corners, ppa_constraints",
        "script": """
        SELECT 1;
        """,
    },
    {
        "version": "2.0",
        "description": "平台基础设施: schema_versions, permissions, role_permissions, workflow_triggers; 软删除/乐观锁/归档字段",
        "script": """
        -- 平台表
        CREATE TABLE IF NOT EXISTS schema_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version VARCHAR(20) UNIQUE NOT NULL,
            description VARCHAR(300),
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            checksum VARCHAR(64) DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code VARCHAR(50) UNIQUE NOT NULL,
            name VARCHAR(100) NOT NULL,
            resource_type VARCHAR(30) DEFAULT '',
            action VARCHAR(30) DEFAULT '',
            description VARCHAR(200) DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS role_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role VARCHAR(30) NOT NULL,
            permission_id INTEGER NOT NULL REFERENCES permissions(id),
            granted_by INTEGER REFERENCES users(id),
            granted_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role);

        CREATE TABLE IF NOT EXISTS workflow_triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            event_type VARCHAR(50) NOT NULL,
            trigger_action VARCHAR(50) NOT NULL,
            target_type VARCHAR(30) DEFAULT '',
            target_value VARCHAR(200) DEFAULT '',
            is_active BOOLEAN DEFAULT 1,
            config_json JSON DEFAULT '{}',
            created_by INTEGER REFERENCES users(id),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- Signoff 软删除/归档/乐观锁
        ALTER TABLE signoffs ADD COLUMN deleted_at DATETIME;
        ALTER TABLE signoffs ADD COLUMN is_archived BOOLEAN DEFAULT 0;
        ALTER TABLE signoffs ADD COLUMN version INTEGER DEFAULT 1;

        -- DocDocument 软删除/归档/乐观锁
        ALTER TABLE doc_documents ADD COLUMN is_deleted BOOLEAN DEFAULT 0;
        ALTER TABLE doc_documents ADD COLUMN deleted_at DATETIME;
        ALTER TABLE doc_documents ADD COLUMN is_archived BOOLEAN DEFAULT 0;
        ALTER TABLE doc_documents ADD COLUMN version INTEGER DEFAULT 1;

        -- Project 软删除
        ALTER TABLE projects ADD COLUMN deleted_at DATETIME;

        -- PipelineRun 归档
        ALTER TABLE pipeline_runs ADD COLUMN is_archived BOOLEAN DEFAULT 0;

        -- AuditLog 哈希链字段
        ALTER TABLE audit_logs ADD COLUMN prev_hash VARCHAR(64) DEFAULT '';
        ALTER TABLE audit_logs ADD COLUMN chain_hash VARCHAR(64) DEFAULT '';
        ALTER TABLE audit_logs ADD COLUMN chain_index INTEGER DEFAULT 0;
        """,
    },
    {
        "version": "2.1",
        "description": "角色→工作流绑定: role_workflow_bindings",
        "script": """
        CREATE TABLE IF NOT EXISTS role_workflow_bindings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role VARCHAR(30) NOT NULL,
            workflow_name VARCHAR(100) NOT NULL,
            is_default BOOLEAN DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            description VARCHAR(300) DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_rwb_role ON role_workflow_bindings(role);
        """,
    },
]


def _ensure_schema_versions_table(conn: sqlite3.Connection):
    """确保 schema_versions 表存在（用于 v1.x 升级到 v2.0 时的 bootstrap）"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version VARCHAR(20) UNIQUE NOT NULL,
            description VARCHAR(300),
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            checksum VARCHAR(64) DEFAULT ''
        )
    """)


def _get_applied_versions(conn: sqlite3.Connection) -> set[str]:
    """获取已应用的迁移版本"""
    _ensure_schema_versions_table(conn)
    rows = conn.execute("SELECT version FROM schema_versions ORDER BY id").fetchall()
    return {r[0] for r in rows}


def _apply_migration(conn: sqlite3.Connection, migration: dict, dry_run: bool = False) -> bool:
    """执行单个迁移"""
    version = migration["version"]
    script = migration["script"].strip()

    if not script or script == "SELECT 1;":
        # 纯 SQLAlchemy 创建的版本，仅记录
        if not dry_run:
            checksum = hashlib.sha256(migration["description"].encode()).hexdigest()[:16]
            conn.execute(
                "INSERT INTO schema_versions (version, description, checksum) VALUES (?, ?, ?)",
                (version, migration["description"], checksum),
            )
            conn.commit()
        return True

    try:
        if not dry_run:
            for stmt in script.split(";"):
                stmt = stmt.strip()
                if not stmt or stmt.startswith("--"):
                    continue
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                        continue  # 幂等：跳过已存在的列/表
                    raise
            checksum = hashlib.sha256(script.encode()).hexdigest()[:16]
            conn.execute(
                "INSERT INTO schema_versions (version, description, checksum) VALUES (?, ?, ?)",
                (version, migration["description"], checksum),
            )
            conn.commit()
        return True
    except Exception as e:
        print(f"  [FAIL] v{version}: {e}")
        return False


def run_migrations(db_path: str = None, dry_run: bool = False):
    """执行所有待处理的迁移"""
    path = db_path or str(DB_PATH)
    if not Path(path).exists():
        print(f"[migrations] Database not found: {path}")
        return

    conn = sqlite3.connect(path)
    applied = _get_applied_versions(conn)

    pending = [m for m in MIGRATIONS if m["version"] not in applied]
    if not pending:
        print(f"[migrations] All {len(MIGRATIONS)} migrations applied. Database is up to date.")
        conn.close()
        return

    print(f"[migrations] {len(pending)} pending migration(s):")
    for m in pending:
        marker = " (dry-run)" if dry_run else ""
        print(f"  v{m['version']}: {m['description']}{marker}")
        if not _apply_migration(conn, m, dry_run):
            print(f"[migrations] Aborted at v{m['version']}")
            conn.close()
            return

    conn.close()
    print(f"[migrations] Done. {len(pending)} migration(s) applied.")


def seed_permissions(conn: sqlite3.Connection = None):
    """初始化权限数据"""
    should_close = conn is None
    if should_close:
        conn = sqlite3.connect(str(DB_PATH))

    permissions = [
        ("project.read", "查看项目", "project", "read"),
        ("project.create", "创建项目", "project", "write"),
        ("project.delete", "删除项目", "project", "delete"),
        ("project.manage_members", "管理项目成员", "project", "admin"),
        ("signoff.read", "查看签核", "signoff", "read"),
        ("signoff.create", "创建签核", "signoff", "write"),
        ("signoff.approve", "批准签核", "signoff", "approve"),
        ("signoff.reject", "驳回签核", "signoff", "approve"),
        ("doc.read", "查看文档", "doc", "read"),
        ("doc.edit", "编辑文档", "doc", "write"),
        ("doc.delete", "删除文档", "doc", "delete"),
        ("evidence.read", "查看证据", "evidence", "read"),
        ("evidence.export", "导出证据包", "evidence", "export"),
        ("pipeline.run", "运行流水线", "pipeline", "write"),
        ("pipeline.read", "查看流水线", "pipeline", "read"),
        ("regression.run", "运行回归", "regression", "write"),
        ("regression.read", "查看回归", "regression", "read"),
        ("user.manage", "管理用户", "user", "admin"),
        ("audit.read", "查看审计日志", "audit", "read"),
        ("ppa.read", "查看 PPA 数据", "ppa", "read"),
        ("ppa.write", "管理 PPA 数据", "ppa", "write"),
        ("ppa.constraint.manage", "管理 PPA 门限", "ppa", "admin"),
    ]

    # 角色-权限分配
    role_perms = {
        "admin": [p[0] for p in permissions],  # admin 拥有所有权限
        "verification_manager": [
            "project.read", "project.create", "project.manage_members",
            "signoff.read", "signoff.create", "signoff.approve", "signoff.reject",
            "doc.read", "doc.edit",
            "evidence.read", "evidence.export",
            "pipeline.run", "pipeline.read",
            "regression.run", "regression.read",
            "audit.read",
            "ppa.read", "ppa.write", "ppa.constraint.manage",
        ],
        "senior_engineer": [
            "project.read",
            "signoff.read", "signoff.create",
            "doc.read", "doc.edit",
            "evidence.read",
            "pipeline.run", "pipeline.read",
            "regression.run", "regression.read",
            "ppa.read", "ppa.write",
        ],
        "engineer": [
            "project.read",
            "signoff.read",
            "doc.read",
            "evidence.read",
            "pipeline.read",
            "regression.read",
            "ppa.read",
        ],
        "viewer": [
            "project.read",
            "signoff.read",
            "doc.read",
            "pipeline.read",
            "regression.read",
        ],
    }

    # 清空旧数据
    conn.execute("DELETE FROM role_permissions")
    conn.execute("DELETE FROM permissions")

    # 插入权限
    perm_ids = {}
    for code, name, resource, action in permissions:
        cursor = conn.execute(
            "INSERT INTO permissions (code, name, resource_type, action) VALUES (?, ?, ?, ?)",
            (code, name, resource, action),
        )
        perm_ids[code] = cursor.lastrowid

    # 分配角色权限
    for role, perm_codes in role_perms.items():
        for code in perm_codes:
            if code in perm_ids:
                conn.execute(
                    "INSERT INTO role_permissions (role, permission_id) VALUES (?, ?)",
                    (role, perm_ids[code]),
                )

    conn.commit()
    if should_close:
        conn.close()
    print(f"[permissions] Seeded {len(permissions)} permissions across {len(role_perms)} roles")


if __name__ == "__main__":
    import sys
    dry_run = "--check" in sys.argv
    run_migrations(dry_run=dry_run)
    if not dry_run:
        seed_permissions()
