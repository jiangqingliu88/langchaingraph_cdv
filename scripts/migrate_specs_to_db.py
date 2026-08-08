"""
一次性将现有 specs/ 目录中的 .md 文件导入数据库

Usage:
    python scripts/migrate_specs_to_db.py [--project-id 1] [--author-id 1]
"""
import asyncio
import os
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


async def main(project_id: int, author_id: int):
    from src.database.connection import init_db
    await init_db()

    from src.database.repository import sync_fs_to_db
    from config.settings import Settings

    settings = Settings()
    specs_dir = getattr(settings, 'SPECS_DIR', None)
    if not specs_dir:
        # fallback
        specs_dir = os.path.join(os.path.dirname(__file__), '..', 'specs')
    specs_dir = os.path.abspath(specs_dir)

    if not os.path.isdir(specs_dir):
        print(f"[ERROR] 规格目录不存在: {specs_dir}")
        return

    print(f"[INFO] 同步目录: {specs_dir}")
    print(f"[INFO] project_id={project_id}, author_id={author_id}")

    result = await sync_fs_to_db(specs_dir, project_id, author_id)

    print(f"\n同步完成:")
    print(f"  新建: {result['created']}")
    print(f"  更新: {result['updated']}")
    print(f"  跳过: {result['skipped']}")
    print(f"  错误: {len(result['errors'])}")
    for e in result['errors']:
        print(f"    ERROR: {e['path']} — {e['error']}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='将 specs/ 目录导入 SQL 数据库')
    parser.add_argument('--project-id', type=int, default=1, help='项目 ID')
    parser.add_argument('--author-id', type=int, default=1, help='导入者用户 ID')
    args = parser.parse_args()
    asyncio.run(main(args.project_id, args.author_id))
