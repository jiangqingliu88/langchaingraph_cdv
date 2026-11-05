#!/usr/bin/env python3
"""
数据库初始化脚本
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.ext.asyncio import create_async_engine
from src.database.models import Base
from config.settings import Settings

async def init_database():
    """初始化数据库"""
    settings = Settings.get_instance()
    
    # 创建异步引擎
    engine = create_async_engine(
        settings.database.url,
        echo=settings.database.echo
    )
    
    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    print("数据库初始化完成!")
    
    # 关闭引擎
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(init_database())