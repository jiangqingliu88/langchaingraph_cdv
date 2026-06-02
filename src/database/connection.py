"""
数据库连接管理 - Singleton模式
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from config.settings import Settings
import structlog

logger = structlog.get_logger()

Base = declarative_base()

class DatabaseManager:
    _instance = None
    _engine = None
    _session_factory = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._settings = Settings.get_instance()
    
    async def init_db(self):
        if self._engine is None:
            db_url = self._settings.database.url
            self._engine = create_async_engine(db_url, echo=self._settings.database.echo, future=True)
            self._session_factory = async_sessionmaker(self._engine, class_=AsyncSession, expire_on_commit=False)
            async with self._engine.begin() as conn:
                from src.database.models import Base
                await conn.run_sync(Base.metadata.create_all)
            logger.info("数据库初始化完成", url=db_url)
    
    async def get_session(self) -> AsyncSession:
        if self._session_factory is None:
            await self.init_db()
        return self._session_factory()
    
    async def close(self):
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("数据库连接已关闭")

async def get_db_session() -> AsyncSession:
    manager = DatabaseManager.get_instance()
    return await manager.get_session()
