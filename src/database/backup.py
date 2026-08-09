"""
数据库备份 & 审计日志保留策略工具

用法:
    python -m src.database.backup                    # 创建备份
    python -m src.database.backup --retention 90     # 创建备份 + 清理90天前的审计日志
"""
import shutil
import sqlite3
import os
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "ic_verification.db"
BACKUP_DIR = Path(__file__).parent.parent.parent / "backups"


def backup_database(db_path: str = None) -> str:
    """创建数据库备份，返回备份文件路径"""
    src = db_path or str(DB_PATH)
    if not Path(src).exists():
        raise FileNotFoundError(f"Database not found: {src}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"ic_verification_{timestamp}.db"

    # 使用 SQLite 在线备份 API 确保一致性
    src_conn = sqlite3.connect(src)
    dst_conn = sqlite3.connect(str(dst))
    src_conn.backup(dst_conn)
    src_conn.close()
    dst_conn.close()

    size_kb = dst.stat().st_size / 1024
    print(f"[backup] Created: {dst.name} ({size_kb:.1f} KB)")

    # 清理旧备份：只保留最近 10 个
    _cleanup_old_backups(keep=10)

    return str(dst)


def _cleanup_old_backups(keep: int = 10):
    """只保留最近 N 个备份"""
    backups = sorted(BACKUP_DIR.glob("ic_verification_*.db"), key=os.path.getmtime, reverse=True)
    for old in backups[keep:]:
        old.unlink()
        print(f"[backup] Removed old backup: {old.name}")


def cleanup_audit_logs(retention_days: int = 90, db_path: str = None):
    """清理超过保留期的审计日志"""
    path = db_path or str(DB_PATH)
    cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()

    conn = sqlite3.connect(path)
    # 先导出归档日志
    archive_rows = conn.execute(
        "SELECT * FROM audit_logs WHERE created_at < ? ORDER BY id", (cutoff,)
    ).fetchall()

    if archive_rows:
        archive_path = BACKUP_DIR / f"audit_archive_{datetime.now().strftime('%Y%m%d')}.sql"
        with open(archive_path, "w", encoding="utf-8") as f:
            f.write("-- Audit Log Archive\n")
            f.write(f"-- Period: before {cutoff}\n")
            f.write(f"-- Records: {len(archive_rows)}\n\n")
            for row in archive_rows:
                f.write(
                    f"INSERT INTO audit_logs VALUES ({','.join(repr(v) for v in row)});\n"
                )
        print(f"[audit] Archived {len(archive_rows)} records to {archive_path.name}")

        deleted = conn.execute("DELETE FROM audit_logs WHERE created_at < ?", (cutoff,))
        print(f"[audit] Purged {deleted.rowcount} old audit records (retention: {retention_days}d)")
    else:
        print(f"[audit] No records older than {retention_days} days")

    conn.commit()
    conn.close()


def get_db_stats(db_path: str = None) -> dict:
    """获取数据库统计信息"""
    path = db_path or str(DB_PATH)
    conn = sqlite3.connect(path)

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    stats = {"tables": {}, "total_size_kb": os.path.getsize(path) / 1024}

    for (name,) in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
        stats["tables"][name] = {"rows": count}

    conn.close()
    return stats


if __name__ == "__main__":
    import sys

    backup_database()

    if "--retention" in sys.argv:
        idx = sys.argv.index("--retention")
        days = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 90
        cleanup_audit_logs(days)

    stats = get_db_stats()
    print(f"\n[db] Tables: {len(stats['tables'])}, Total size: {stats['total_size_kb']:.1f} KB")
    for name, info in stats["tables"].items():
        print(f"  {name}: {info['rows']} rows")
