from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config.settings import Settings
_engine = None
_factory = None
async def init_db():
    global _engine, _factory
    if _engine is None:
        s = Settings.get_instance()
        _engine = create_async_engine(s.database.url, echo=False)

        # 桌面工作台 + CLI 可能同时打开主库；统一 WAL / busy_timeout，
        # 避免“一边 WAL、一边回滚日志”导致 database is locked。
        @event.listens_for(_engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            try:
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()
            except Exception:                       # noqa: BLE001 非 SQLite 后端跳过
                pass

        _factory = async_sessionmaker(_engine, class_=AsyncSession)
        async with _engine.begin() as conn:
            from src.knowledge_plane.persistence.models import Base
            await conn.run_sync(Base.metadata.create_all)
        # 填充默认角色→工作流绑定
        try:
            from src.knowledge_plane.persistence.repository import seed_default_role_workflow_bindings
            await seed_default_role_workflow_bindings()
        except Exception:
            pass
async def get_session():
    if _factory is None:
        await init_db()
    return _factory()
