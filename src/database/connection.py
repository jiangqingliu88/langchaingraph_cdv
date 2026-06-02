from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config.settings import Settings
_engine = None
_factory = None
async def init_db():
    global _engine, _factory
    if _engine is None:
        s = Settings.get_instance()
        _engine = create_async_engine(s.database.url, echo=False)
        _factory = async_sessionmaker(_engine, class_=AsyncSession)
        async with _engine.begin() as conn:
            from src.database.models import Base
            await conn.run_sync(Base.metadata.create_all)
async def get_session():
    if _factory is None:
        await init_db()
    return _factory()
